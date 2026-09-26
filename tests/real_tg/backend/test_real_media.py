"""Медиа в реальном Telegram: архив переживает исчезновение файла (issue #98).

Живой сценарий «нескачиваемой картинки»: мимику приходит фото с таймером
самоуничтожения (как капча бота верификации). Повторно скачать такой файл
Telegram не даёт — но байты должны быть заархивированы при получении и
доступны через API дашборда.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, cast
from uuid import UUID

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from PIL import Image

from mimic42.testing.real_tg.checker import Checker
from mimic42.testing.slots import plain_dsn
from tests.real_tg.backend.helpers import jwt

pytestmark = pytest.mark.real_tg

TTL_SECONDS = 30
MEDIA_TIMEOUT_SECONDS = 90


def png(color: tuple[int, int, int]) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (320, 240), color).save(buffer, format="PNG")
    return buffer.getvalue()


async def archived_photo_path(agent_id: str, since: datetime) -> str | None:
    """Путь заархивированного входящего фото в Storage (или None, не дождались)."""
    dsn = os.environ["DATABASE_CONNECTION_STRING"]
    loop = asyncio.get_running_loop()
    deadline = loop.time() + MEDIA_TIMEOUT_SECONDS
    while loop.time() < deadline:
        conn = await asyncpg.connect(plain_dsn(dsn))
        try:
            rows = await conn.fetch(
                "select payload from agent_messages where agent_id = $1"
                " and direction = 'incoming' and created_at >= $2"
                " order by created_at desc limit 20",
                UUID(agent_id),
                since,
            )
        finally:
            await conn.close()
        for row in rows:
            payload = json.loads(row["payload"] or "{}")
            for item in payload.get("media") or []:
                path = item.get("storage_path")
                if path and item.get("kind") == "photo":
                    return str(path)
        await asyncio.sleep(2)
    return None


async def test_self_destructing_photo_is_archived_before_telegram_loses_it(
    real_app: tuple[FastAPI, AsyncClient],
    checker: Checker,
    started_mimics: list[tuple[str, str]],
) -> None:
    agent_id, phone = started_mimics[0]
    _, client = real_app
    await checker.import_contact(phone)
    # Мимик должен увидеть проверяющего до медиа: телефон резолвится из
    # контактов, числовой id — из кэша сессии после первого сообщения.
    await checker.send_and_wait_reply(phone, "Разогрев перед фото", timeout=300)

    started = datetime.now(UTC)
    stream = BytesIO(png((60, 160, 90)))
    stream.name = "verify.png"
    message = cast(Any, await checker.client.send_file(phone, stream, ttl=TTL_SECONDS))

    storage_path = await archived_photo_path(agent_id, started)
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
    # Фото в пути хранится как jpeg (пережатое Telegram).
    assert response.content[:2] == b"\xff\xd8"
