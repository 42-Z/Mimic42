"""Общая обвязка реальных TG-тестов бэкенда: настоящий app и проверяющий."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from dotenv import load_dotenv
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from mimic42.testing.real_tg.checker import Checker

ROOT = Path(__file__).resolve().parents[3]
# real_tg работает с боевой конфигурацией: .env грузится ПОВЕРХ тестовых
# переопределений (.env.test выставляет заглушки телеги и правит базу).
load_dotenv(ROOT / ".env", override=True)

from mimic42.api.app import create_app  # noqa: E402
from tests.real_tg.backend.helpers import media_storage, real_app_settings  # noqa: E402


@pytest_asyncio.fixture
async def real_app() -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    settings = real_app_settings()
    # Медиа-архив: настоящий Storage при SUPABASE_SERVICE_ROLE_KEY, иначе
    # хранилище в памяти — сценарий «архив переживает потерю файла» (#98)
    # должен быть достижим и без сервисного ключа.
    media = media_storage()
    app = create_app(settings=settings, media_uploader=media)
    try:
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                yield app, client
    finally:
        # Переданное снаружи хранилище приложение не закрывает: незакрытый
        # httpx-клиент Supabase иначе всплывает ResourceWarning, а с -W error
        # это ошибка прогона.
        close = getattr(media, "close", None)
        if callable(close):
            close()


@pytest_asyncio.fixture
async def checker() -> AsyncIterator[Checker]:
    instance = Checker(
        api_id=int(os.environ["TG_CHECKER_API_ID"]),
        api_hash=os.environ["TG_CHECKER_API_HASH"],
        session_string=os.environ["TG_CHECKER_SESSION"],
    )
    await instance.start()
    yield instance
    await instance.stop()


@pytest_asyncio.fixture
async def started_mimics(
    real_app: tuple[FastAPI, AsyncClient], checker: Checker
) -> list[tuple[str, str]]:
    """Запускает агентов-мимиков через API; возвращает [(agent_id, phone)]."""
    _, client = real_app
    from tests.real_tg.backend.helpers import (
        agent_id_for_phone,
        disable_auto_restore,
        ensure_free_model,
        jwt,
        user_id_from_token,
    )

    token = await jwt()
    owner_id = user_id_from_token(token)
    dsn = os.environ["DATABASE_CONNECTION_STRING"]
    await disable_auto_restore(dsn, owner_id)
    phones = await checker.mimic_phones(dsn, owner_id)
    agents: list[tuple[str, str]] = []
    for phone in phones:
        agent_id = await agent_id_for_phone(dsn, phone, owner_id)
        await ensure_free_model(dsn, agent_id)
        response = await client.post(
            f"/api/v1/agents/{agent_id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 204, response.text
        agents.append((agent_id, phone))
    return agents
