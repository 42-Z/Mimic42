"""Медиа в реальном Telegram: архив переживает исчезновение файла (issue #98).

Живой сценарий «нескачиваемой картинки»: мимику приходит фото с таймером
самоуничтожения (как капча бота верификации), байты архивируются при
получении, а после исчезновения файла из Telegram (таймер самоуничтожения
запускает получатель; или удаление сообщения — как капчу) копия остаётся
доступной через API дашборда. Отказ Telegram проверяется на стороне
мимика-получателя: у отправителя своя копия файла и она не исчезает.

Тест намеренно не ждёт ответов LLM: архив пишется при получении сообщения,
до хода модели, а ходы бесплатных моделей в общем прогоне могут быть
медленными.
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from PIL import Image
from telethon import functions

from mimic42.testing.real_tg.checker import Checker
from tests.real_tg.backend.helpers import jwt

pytestmark = pytest.mark.real_tg

TTL_SECONDS = 30
ARCHIVE_TIMEOUT_SECONDS = 120


def png(color: tuple[int, int, int]) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (320, 240), color).save(buffer, format="PNG")
    return buffer.getvalue()


async def archived_files(uploader: Any, agent_id: str) -> list[str]:
    """Пути файлов агента в хранилище (память или настоящий Supabase Storage)."""
    collect = getattr(uploader, "_collect_files", None)
    if callable(collect):
        return list(await collect(str(agent_id), 0))
    files = getattr(uploader, "_files", {})
    return [path for path in files if path.startswith(f"{agent_id}/")]


async def wait_archived_photo(app: FastAPI, agent_id: str, previous_paths: set[str]) -> str | None:
    """Ждёт, пока входящее фото мимика окажется в хранилище.

    Проверяет само хранилище, а не запись в БД: строка `agent_messages`
    появляется только после полного хода LLM, а архив — сразу при получении.
    Среди путей берётся только появившийся после отправки: прошлые прогоны
    могли оставить собственные `photo.jpeg`.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + ARCHIVE_TIMEOUT_SECONDS
    uploader = app.state.media_uploader
    while loop.time() < deadline:
        paths = await archived_files(uploader, agent_id)
        photos = [
            path for path in paths if path.endswith("photo.jpeg") and path not in previous_paths
        ]
        if photos:
            return photos[0]
        await asyncio.sleep(2)
    return None


async def recipient_side(app: FastAPI, agent_id: str, sender_id: int) -> tuple[Any, Any]:
    """Клиент мимика и его копия входящего фото.

    В приватном чате id сообщения у каждого аккаунта свой (core.telegram.org/api/updates,
    «Message ID sequences»: ids «will not be the same for different accounts»),
    поэтому фото ищем в истории мимика — последнее сообщение с
    самоуничтожающимся фото. Его id нужен и для readMessageContents, который
    запускает таймер, и для повторного скачивания.
    """
    runtime = await app.state.agent_manager.get_agent(UUID(agent_id))
    client = runtime._telegram_client
    async for message in client.iter_messages(sender_id, limit=10):
        media = getattr(message, "media", None)
        if media is not None and getattr(media, "ttl_seconds", None) == TTL_SECONDS:
            return client, message
    return client, None


async def recipient_can_download(client: Any, message: Any) -> bool:
    # file=bytes — в память: без него Telethon складывает фото в рабочий каталог.
    try:
        data = await client.download_media(message, file=bytes)
    except Exception:
        return False
    return bool(data)


async def telegram_loses_the_file(
    checker: Checker, mimic_client: Any, received: Any, phone: str, sender_message_id: int
) -> str:
    """Пытается заставить Telegram потерять файл у получателя; диагноз.

    Файл теряет получатель: по core.telegram.org/api/views («Non-secret
    expiring media») таймер самоуничтожения запускает messages.readMessageContents
    с id сообщения получателя, после чего его file_reference перестаёт
    работать. Копия отправителя остаётся живой, поэтому проверяем сторону
    мимика — тот самый отказ из issue #98.
    """
    if not await recipient_can_download(mimic_client, received):
        return "уже недоступно"

    # Получатель открывает медиа — таймер самоуничтожения стартует.
    try:
        await mimic_client(functions.messages.ReadMessageContentsRequest(id=[received.id]))
    except Exception:
        pass
    await asyncio.sleep(TTL_SECONDS + 5)
    if not await recipient_can_download(mimic_client, received):
        return "просмотр получателем + таймер TTL"

    await checker.client.delete_messages(phone, [sender_message_id], revoke=True)
    if not await recipient_can_download(mimic_client, received):
        return "удаление сообщения"
    return "файл ещё доступен"


async def test_self_destructing_photo_is_archived_before_telegram_loses_it(
    real_app: tuple[FastAPI, AsyncClient],
    checker: Checker,
    started_mimics: list[tuple[str, str]],
) -> None:
    agent_id, phone = started_mimics[0]
    app, client = real_app
    await checker.import_contact(phone)
    previous_paths = set(await archived_files(app.state.media_uploader, agent_id))

    stream = BytesIO(png((60, 160, 90)))
    stream.name = "verify.png"
    message = cast(Any, await checker.client.send_file(phone, stream, ttl=TTL_SECONDS))
    # Фото действительно самоуничтожающееся — как капча бота верификации.
    assert getattr(getattr(message, "media", None), "ttl_seconds", None) == TTL_SECONDS

    storage_path = await wait_archived_photo(app, agent_id, previous_paths)
    assert storage_path, "Входящее фото не заархивировалось в Storage"

    mimic_client, received = await recipient_side(app, agent_id, await checker.my_id())
    assert received is not None, "Мимик не видит входящее самоуничтожающееся фото"

    # Файл пытаются потерять в Telegram — диагноз попадает в лог прогона.
    mechanism = await telegram_loses_the_file(checker, mimic_client, received, phone, message.id)
    print("потеря файла из Telegram:", mechanism)  # noqa: T201 — диагностика живого прогона
    assert mechanism != "файл ещё доступен", (
        "Telegram продолжает отдавать файл: сценарий «нескачиваемой картинки» не воспроизвёлся"
    )

    # Главное живое свойство: байты реального Telegram-файла переживают
    # исчезновение сообщения и отдаются через API дашборда.
    token = await jwt()
    response = await client.get(
        f"/api/v1/agents/{agent_id}/media/{storage_path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    # Фото в хранилище лежит как jpeg (пережатое Telegram).
    assert response.content[:2] == b"\xff\xd8"
