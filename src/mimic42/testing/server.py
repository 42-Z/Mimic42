"""Точка входа сервера для тестов: настоящая база и настоящий API,
поддельные Telegram и модель.

Запуск: uv run uvicorn mimic42.testing.server:app --port 8000
"""

from __future__ import annotations

import os
from uuid import UUID

from fastapi import FastAPI
from pydantic import BaseModel

from mimic42.api.app import create_app
from mimic42.api.auth import AuthVerifier
from mimic42.config import Settings
from mimic42.testing import registry
from mimic42.testing.cleanup import purge_slot_data
from mimic42.testing.llm import ScriptedAgentFactory
from mimic42.testing.slots import SLOTS
from mimic42.testing.telegram import FakeTelegramAuthClientFactory, FakeTelegramClient


class ResetRequest(BaseModel):
    slot: str


class DeliverRequest(BaseModel):
    chat_id: int
    text: str


class OnboardingScriptRequest(BaseModel):
    code: str | None = None
    password: str | None = None


def _test_settings() -> Settings:
    return Settings(
        database_connection_string=os.environ["TEST_DATABASE_CONNECTION_STRING"],
        supabase_url=os.environ["TEST_SUPABASE_URL"],
        secret_key=os.environ["TEST_SECRET_KEY"],
        telegram_api_id=int(os.environ.get("TEST_TELEGRAM_API_ID", "1")),
        telegram_api_hash=os.environ.get("TEST_TELEGRAM_API_HASH", "test-api-hash"),
        cors_allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        # Явно отключает Mem0: без этого Settings() подхватил бы боевой
        # MEM0_API_KEY из .env разработчика, и тесты били бы по настоящему
        # внешнему сервису.
        mem0_api_key=None,
    )


def build_test_app(
    settings: Settings | None = None,
    *,
    auth_verifier: AuthVerifier | None = None,
) -> FastAPI:
    app_settings = settings or _test_settings()
    scripted = ScriptedAgentFactory()
    application = create_app(
        settings=app_settings,
        telegram_factory=FakeTelegramAuthClientFactory(registry.onboarding_account()),
        telegram_client_factory=lambda config: FakeTelegramClient(
            registry.account_for(config.agent_id)
        ),
        langchain_agent_factory=scripted,
        auth_verifier=auth_verifier,
    )
    application.state.scripted_agents = scripted
    _mount_test_routes(application, app_settings)
    return application


def _mount_test_routes(application: FastAPI, settings: Settings) -> None:
    @application.post("/__test__/reset")
    async def reset(request: ResetRequest) -> dict[str, str]:
        slot = next(item for item in SLOTS if item.name == request.slot)
        await purge_slot_data(settings.database_connection_string or "", slot)
        registry.reset()
        return {"status": "ok"}

    @application.post("/__test__/telegram/{agent_id}/deliver")
    async def deliver(agent_id: UUID, request: DeliverRequest) -> dict[str, str]:
        await registry.account_for(agent_id).deliver(chat_id=request.chat_id, text=request.text)
        return {"status": "ok"}

    @application.get("/__test__/telegram/{agent_id}/sent")
    async def sent(agent_id: UUID) -> list[dict[str, str]]:
        account = registry.account_for(agent_id)
        return [{"chat_id": str(item.chat_id), "text": item.text} for item in account.sent]

    @application.post("/__test__/telegram/onboarding/script")
    async def script_onboarding(request: OnboardingScriptRequest) -> dict[str, str]:
        """Задаёт код и/или 2FA-пароль, которые примет подделка входа в
        Telegram во время онбординга. Без вызова любой 5+-значный код
        принимается как есть (FakeTelegramAuthClient.sign_in по умолчанию
        не проверяет код) — эндпоинт нужен только для сценариев с
        конкретным кодом или паролем 2FA."""
        account = registry.onboarding_account()
        if request.code is not None:
            account.script_code(request.code)
        if request.password is not None:
            account.require_password(request.password)
        return {"status": "ok"}


if os.environ.get("TEST_DATABASE_CONNECTION_STRING"):
    # Строится только когда переменные окружения реально заданы: иначе
    # простой импорт этого модуля (например, во время сбора тестов без
    # базы) падал бы независимо от маркера db.
    app = build_test_app()
