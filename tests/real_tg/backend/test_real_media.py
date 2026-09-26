"""Медиа в реальном Telegram: архив переживает исчезновение файла (issue #98).

Живой сценарий «нескачиваемой картинки»: мимику приходит фото с таймером
самоуничтожения (как капча бота верификации). Повторно скачать такой файл
Telegram не даёт — но байты должны быть заархивированы при получении и
доступны через API дашборда.

Тест намеренно не ждёт ответов LLM: архив пишется при получении сообщения,
до хода модели, а ходы бесплатных моделей в общем прогоне могут быть
медленными.
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from PIL import Image

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


async def wait_archived_photo(app: FastAPI, agent_id: str) -> str | None:
    """Ждёт, пока входящее фото мимика окажется в хранилище.

    Проверяет само хранилище, а не запись в БД: строка `agent_messages`
    появляется только после полного хода LLM, а архив — сразу при получении.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + ARCHIVE_TIMEOUT_SECONDS
    uploader = app.state.media_uploader
    while loop.time() < deadline:
        paths = await archived_files(uploader, agent_id)
        photos = [path for path in paths if path.endswith("photo.jpeg")]
        if photos:
            return photos[0]
        await asyncio.sleep(2)
    return None


async def test_self_destructing_photo_is_archived_before_telegram_loses_it(
    real_app: tuple[FastAPI, AsyncClient],
    checker: Checker,
    started_mimics: list[tuple[str, str]],
) -> None:
    agent_id, phone = started_mimics[0]
    app, client = real_app
    await checker.import_contact(phone)

    stream = BytesIO(png((60, 160, 90)))
    stream.name = "verify.png"
    message = cast(Any, await checker.client.send_file(phone, stream, ttl=TTL_SECONDS))

    storage_path = await wait_archived_photo(app, agent_id)
    assert storage_path, "Входящее фото не заархивировалось в Storage"

    # Таймер самоуничтожения пошёл с просмотра: ждём, пока Telegram перестанет
    # отдавать файл (то самое «cannot be resent» из issue #98).
    await asyncio.sleep(TTL_SECONDS + 5)
    gone = False
    try:
        await checker.client.download_media(message)
    except Exception:
        gone = True
    assert gone, "Telegram всё ещё отдаёт самоуничтожившееся фото — сценарий не воспроизвёлся"

    # Архивная копия доступна через API дашборда: Telegram её уже не отдаёт.
    token = await jwt()
    response = await client.get(
        f"/api/v1/agents/{agent_id}/media/{storage_path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    # Фото в хранилище лежит как jpeg (пережатое Telegram).
    assert response.content[:2] == b"\xff\xd8"
