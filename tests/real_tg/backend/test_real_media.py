"""Медиа в реальном Telegram: архив переживает исчезновение файла (issue #98).

Живой сценарий «нескачиваемой картинки»: мимику приходит фото с таймером
самоуничтожения (как капча бота верификации), байты архивируются при
получении, а после исчезновения файла из Telegram (таймер самоуничтожения
или удаление сообщения — как капчу) копия остаётся доступной через API
дашборда.

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


async def still_downloadable(checker: Checker, message: Any) -> bool:
    try:
        data = await checker.client.download_media(message)
    except Exception:
        return False
    return bool(data)


async def mark_viewed_by_recipient(app: FastAPI, agent_id: str, message_id: int) -> bool:
    """Отметить фото просмотренным от лица мимика-получателя.

    Таймер самоуничтожения запускает именно ReadMessageContents получателя
    (так делает openMessageContent в TDLib); у отправителя — клиента
    проверяющего — этот запрос медиа не открывает.
    """
    runtime = await app.state.agent_manager.get_agent(UUID(agent_id))
    client = runtime._telegram_client
    try:
        await client(functions.messages.ReadMessageContentsRequest(id=[message_id]))
    except Exception:
        return False
    return True


async def telegram_loses_the_file(
    checker: Checker, app: FastAPI, agent_id: str, phone: str, message: Any
) -> str:
    """Пытается заставить Telegram потерять файл; возвращает диагноз.

    Юзербот-API не умеет гарантированно убить файл: таймер TTL стартует от
    просмотра получателем, TTL-сообщения нельзя редактировать
    (MediaTtlInvalidError), а удаление сообщения не инвалидирует
    file_reference немедленно. Поэтому идём по нарастающей и честно
    сообщаем, что сработало: обработка отказов Telegram покрыта
    юнит-тестами (FileReferenceExpiredError/MediaEmptyError → архив).
    """
    if not await still_downloadable(checker, message):
        return "уже недоступно"

    # Просмотр содержимого получателем — серверное «медиа открыто»: только
    # он запускает таймер самоуничтожения.
    if await mark_viewed_by_recipient(app, agent_id, message.id):
        await asyncio.sleep(TTL_SECONDS + 5)
        if not await still_downloadable(checker, message):
            return "просмотр получателем + таймер TTL"

    await checker.client.delete_messages(phone, [message.id], revoke=True)
    if not await still_downloadable(checker, message):
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

    # Файл пытаются потерять в Telegram — диагноз попадает в лог прогона.
    mechanism = await telegram_loses_the_file(checker, app, agent_id, phone, message)
    print("потеря файла из Telegram:", mechanism)  # noqa: T201 — диагностика живого прогона

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
