"""Точка входа сервера для тестов: настоящая база и настоящий API,
поддельные Telegram и модель.

Запуск: uv run uvicorn mimic42.testing.server:app --port 8000
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from mimic42.api.app import create_app
from mimic42.api.auth import AuthVerifier
from mimic42.config import Settings
from mimic42.core.activity import ActivityRecorder
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.crypto import FernetSecretCipher
from mimic42.core.onboarding import OnboardingSession, TelegramLoginStatus
from mimic42.testing import registry
from mimic42.testing.cleanup import (
    current_onboarding_draft_id,
    hide_incomplete_onboarding_drafts,
    purge_slot_data,
)
from mimic42.testing.llm import Reply, ScriptedAgentFactory
from mimic42.testing.memory import FakeLongTermMemory
from mimic42.testing.slots import SLOTS, assert_test_project
from mimic42.testing.telegram import FakeTelegramAuthClientFactory, FakeTelegramClient


class ResetRequest(BaseModel):
    slot: str


class OwnerRequest(BaseModel):
    owner_id: UUID


class DeliverRequest(BaseModel):
    chat_id: int
    text: str


class OnboardingScriptRequest(BaseModel):
    code: str | None = None
    password: str | None = None


class AgentScriptRequest(BaseModel):
    text: str


class AgentEventRequest(BaseModel):
    event_type: str
    status: str
    payload: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class CreateTestAgentRequest(BaseModel):
    owner_id: UUID
    name: str
    soul_prompt: str = "спокойный помощник, отвечает коротко"
    state: str = "stopped"
    phone_number: str | None = None
    with_telegram_session: bool = True


def _test_settings() -> Settings:
    database_connection_string = os.environ["TEST_DATABASE_CONNECTION_STRING"]
    supabase_url = os.environ["TEST_SUPABASE_URL"]
    return Settings(
        database_connection_string=database_connection_string,
        supabase_url=supabase_url,
        secret_key=os.environ["TEST_SECRET_KEY"],
        telegram_api_id=int(os.environ.get("TEST_TELEGRAM_API_ID", "1")),
        telegram_api_hash=os.environ.get("TEST_TELEGRAM_API_HASH", "test-api-hash"),
        cors_allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        # Явно отключает Mem0: без этого Settings() подхватил бы боевой
        # MEM0_API_KEY из .env разработчика, и тесты били бы по настоящему
        # внешнему сервису. Память подменяется FakeLongTermMemory ниже.
        mem0_api_key=None,
    )


def build_test_app(
    settings: Settings | None = None,
    *,
    auth_verifier: AuthVerifier | None = None,
) -> FastAPI:
    app_settings = settings or _test_settings()
    # Заслон стоит здесь, а не только в _test_settings: сюда можно передать
    # произвольные настройки мимо env, и они тоже обязаны указывать на Dev.
    assert_test_project(app_settings.database_connection_string, app_settings.supabase_url)
    scripted = ScriptedAgentFactory()
    application = create_app(
        settings=app_settings,
        telegram_factory=FakeTelegramAuthClientFactory(registry.onboarding_account()),
        telegram_client_factory=lambda config: FakeTelegramClient(
            registry.account_for(config.agent_id)
        ),
        langchain_agent_factory=scripted,
        long_term_memory=FakeLongTermMemory(),
        auth_verifier=auth_verifier,
    )
    application.state.scripted_agents = scripted
    _mount_test_routes(application, app_settings)
    return application


def _mount_test_routes(application: FastAPI, settings: Settings) -> None:
    dsn = settings.database_connection_string or ""

    @application.post("/__test__/reset")
    async def reset(request: ResetRequest) -> dict[str, str]:
        slot = next(item for item in SLOTS if item.name == request.slot)
        await purge_slot_data(dsn, slot)
        registry.reset()
        # Сценарии привязаны к id уже удалённых агентов: чистим, чтобы
        # следующий прогон не унаследовал чужие заготовки.
        application.state.scripted_agents.scripts.clear()
        application.state.scripted_agents.built.clear()
        return {"status": "ok"}

    @application.post("/__test__/onboarding/drafts/hide")
    async def hide_onboarding_drafts(request: OwnerRequest) -> dict[str, int]:
        """Прячет незавершённые черновики владельца перед попыткой визарда."""
        removed = await hide_incomplete_onboarding_drafts(dsn, request.owner_id)
        return {"removed": removed}

    @application.get("/__test__/onboarding/drafts/current")
    async def current_draft(owner_id: UUID) -> dict[str, str]:
        draft_id = await current_onboarding_draft_id(dsn, owner_id)
        if draft_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Нет незавершённого черновика онбординга для {owner_id}",
            )
        return {"id": str(draft_id)}

    @application.post("/__test__/agents/{agent_id}/script")
    async def script_agent(agent_id: UUID, request: AgentScriptRequest) -> dict[str, str]:
        """Задаёт ответ поддельной модели для следующих ходов агента."""
        application.state.scripted_agents.set_script(agent_id, [Reply(request.text)])
        return {"status": "ok"}

    @application.post("/__test__/agents/{agent_id}/events")
    async def record_agent_event(agent_id: UUID, request: AgentEventRequest) -> dict[str, str]:
        """Пишет настоящее событие агента тем же recorder'ом, что и прод."""
        store = application.state.agent_store
        recorder = ActivityRecorder(store._session_factory)  # noqa: SLF001
        await recorder.record(
            agent_id=agent_id,
            event_type=request.event_type,
            status=request.status,
            payload=request.payload,
            result=request.result,
            error=request.error,
        )
        return {"status": "ok"}

    @application.post("/__test__/telegram/onboarding/reset")
    async def reset_onboarding_login() -> dict[str, str]:
        """Снимает сценарий входа (код/2FA), чтобы следующий тест визарда
        начинал с чистого фейкового аккаунта."""
        registry.reset_onboarding_account()
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
        Telegram во время онбординга. Без вызова код не проверяется
        (любой непустой принимается как есть) — эндпоинт нужен только для
        сценариев с конкретным кодом или паролем 2FA."""
        account = registry.onboarding_account()
        if request.code is not None:
            account.script_code(request.code)
        if request.password is not None:
            account.require_password(request.password)
        return {"status": "ok"}

    @application.post("/__test__/agents")
    async def create_test_agent(request: CreateTestAgentRequest) -> dict[str, str]:
        """Заводит настоящего агента в базе в обход онбординга — для тестов,
        которым нужен готовый агент, а не сама процедура его создания."""
        agent_id = uuid4()
        cipher = FernetSecretCipher(settings.secret_key) if settings.secret_key else None
        store = application.state.agent_store
        await store.create_from_onboarding(
            OnboardingSession(
                onboarding_id=agent_id,
                owner_id=request.owner_id,
                authorization_status=TelegramLoginStatus.AUTHORIZED,
                api_id=1,
                api_hash_secret=(cipher.encrypt("test-api-hash") if cipher else "test-api-hash"),
                phone_number=request.phone_number,
                name=request.name,
                soul_prompt=request.soul_prompt,
            )
        )
        if not request.with_telegram_session:
            # create_from_onboarding always writes a telegram_sessions row —
            # some UI states (e.g. "session not found") only occur when that
            # row is genuinely absent, so drop it back out here.
            from sqlalchemy import delete

            from mimic42.integrations.database_models import TelegramSessionModel

            async with store._session_factory() as db_session:  # noqa: SLF001
                await db_session.execute(
                    delete(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
                )
                await db_session.commit()
        if request.state == "running":
            await store.update_status(agent_id, AgentRuntimeState.RUNNING)
            config = await store.get_runtime_config(agent_id)
            await application.state.agent_manager.create_agent(config, start=True)
        return {"agent_id": str(agent_id)}


if os.environ.get("TEST_DATABASE_CONNECTION_STRING"):
    # Строится только когда переменные окружения реально заданы: иначе
    # простой импорт этого модуля (например, во время сбора тестов без
    # базы) падал бы независимо от маркера db.
    app = build_test_app()
