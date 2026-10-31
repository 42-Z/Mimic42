"""Точка входа сервера для тестов: настоящая база и настоящий API,
поддельные Telegram и модель.

Запуск: uv run uvicorn mimic42.testing.server:app --port 8000
"""

from __future__ import annotations

import os
from typing import Any, Literal
from uuid import UUID, uuid4

import asyncpg
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from mimic42.api.app import create_app
from mimic42.api.auth import AuthVerifier
from mimic42.config import Settings
from mimic42.core.activity import ActivityRecorder
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.crypto import FernetSecretCipher
from mimic42.core.onboarding import OnboardingSession, TelegramLoginStatus
from mimic42.testing import registry, seed_agent
from mimic42.testing.cleanup import (
    current_onboarding_draft_id,
    hide_incomplete_onboarding_drafts,
    purge_slot_data,
)
from mimic42.testing.env import load_test_env
from mimic42.testing.llm import Reply, ScriptedAgentFactory
from mimic42.testing.memory import FakeLongTermMemory
from mimic42.testing.slots import (
    CONNECT_TIMEOUT_SECONDS,
    SLOTS,
    assert_test_project,
    plain_dsn,
)
from mimic42.testing.telegram import FakeDialog, FakeTelegramAuthClientFactory, FakeTelegramClient

# Точка входа для `uvicorn mimic42.testing.server:app`: файлы грузятся здесь,
# чтобы сервер поднимался без предварительного `source .env.test`.
load_test_env()


class ResetRequest(BaseModel):
    slot: str


class OwnerRequest(BaseModel):
    owner_id: UUID


class DeliverRequest(BaseModel):
    chat_id: int
    text: str


class DialogSpec(BaseModel):
    id: int
    title: str
    kind: Literal["channel", "group", "private"]
    username: str | None = None
    archived: bool = False


class DialogsRequest(BaseModel):
    dialogs: list[DialogSpec]


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


class TestAdminRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: str = Field(min_length=1, max_length=16)
    owner_id: UUID
    enabled: bool


TEST_SLOT_HOLDER_HEADER = "X-Mimic42-Test-Slot-Holder"


def _test_settings() -> Settings:
    database_connection_string = os.environ["DATABASE_CONNECTION_STRING"]
    supabase_url = os.environ["SUPABASE_URL"]
    # CORS берём из окружения (CORS_ALLOW_ORIGINS), как боевой Settings: e2e
    # умеет переопределять порт фронта, и API обязан следовать за ним.
    cors_allow_origins = Settings().cors_allow_origins
    return Settings(
        database_connection_string=database_connection_string,
        supabase_url=supabase_url,
        secret_key=os.environ["SECRET_KEY"],
        cors_allow_origins=cors_allow_origins,
        # Явно отключает Mem0 и Braintrust: без этого Settings() подхватил бы
        # боевые ключи из .env разработчика, и тесты били бы по настоящим
        # внешним сервисам (для Braintrust — ещё логинились, ставили
        # процесс-глобальный LangChain-хендлер и atexit-flush). Память
        # подменяется FakeLongTermMemory ниже, трейсинг тестам не нужен.
        mem0_api_key=None,
        braintrust_api_key=None,
        # Чужие RUNNING-агенты из общей Dev-базы в тестах не поднимаются даже
        # фейковым клиентом: каждый такой «запуск» пишет в запись чужого агента
        # события и пустой @username от фейкового get_me (restore в app.py
        # перечитывает всех RUNNING без фильтра по владельцу). Тесты, которые
        # проверяют само восстановление, включают его явной настройкой.
        restore_running_agents=False,
    )


def _validate_test_admin_persona(
    dsn: str,
    supabase_url: str | None,
    slot_name: str,
    owner_id: UUID,
) -> None:
    if not dsn or not supabase_url:
        raise RuntimeError("тестовой базе не заданы обязательные параметры")
    assert_test_project(dsn, supabase_url)

    slot = next((candidate for candidate in SLOTS if candidate.name == slot_name), None)
    if slot is None:
        raise ValueError("Неизвестный слот тестовых аккаунтов")
    if owner_id not in {persona.user_id for persona in slot.personas}:
        raise ValueError("Пользователь не относится к указанному тестовому слоту")


async def _require_active_test_slot_lease(
    connection: asyncpg.Connection,
    slot_name: str,
    lease_holder: str,
) -> None:
    if not lease_holder.strip():
        raise ValueError("Не передан владелец аренды тестового слота")
    expires_at = await connection.fetchval(
        "select expires_at from test_support.slot_leases "
        "where slot = $1 and holder = $2 for update",
        slot_name,
        lease_holder,
    )
    lease_active = expires_at is not None and await connection.fetchval(
        "select $1::timestamptz > clock_timestamp()",
        expires_at,
    )
    if not lease_active:
        raise ValueError("Тестовый слот не арендован этим запуском")


async def get_test_admin_role(
    dsn: str,
    supabase_url: str | None,
    slot_name: str,
    owner_id: UUID,
    *,
    lease_holder: str,
) -> bool:
    """Read one slot persona's admin role while holding its active lease."""
    _validate_test_admin_persona(dsn, supabase_url, slot_name, owner_id)
    connection = await asyncpg.connect(
        plain_dsn(dsn),
        timeout=CONNECT_TIMEOUT_SECONDS,
    )
    try:
        async with connection.transaction():
            await _require_active_test_slot_lease(connection, slot_name, lease_holder)
            return bool(
                await connection.fetchval(
                    "select exists (select 1 from public.admin_users where user_id = $1)", owner_id
                )
            )
    finally:
        await connection.close()


async def set_test_admin_role(
    dsn: str,
    supabase_url: str | None,
    slot_name: str,
    owner_id: UUID,
    *,
    lease_holder: str,
    enabled: bool,
) -> bool:
    """Set one slot persona's admin role while holding its active lease."""
    _validate_test_admin_persona(dsn, supabase_url, slot_name, owner_id)
    connection = await asyncpg.connect(
        plain_dsn(dsn),
        timeout=CONNECT_TIMEOUT_SECONDS,
    )
    try:
        async with connection.transaction():
            await _require_active_test_slot_lease(connection, slot_name, lease_holder)
            was_enabled = bool(
                await connection.fetchval(
                    "select exists (select 1 from public.admin_users where user_id = $1)", owner_id
                )
            )
            if enabled:
                await connection.execute(
                    "insert into public.admin_users (user_id) values ($1) "
                    "on conflict (user_id) do nothing",
                    owner_id,
                )
            else:
                await connection.execute(
                    "delete from public.admin_users where user_id = $1",
                    owner_id,
                )
    finally:
        await connection.close()
    return was_enabled


async def delete_test_official_preset(
    dsn: str,
    supabase_url: str | None,
    preset_id: UUID,
    *,
    slot_name: str,
    lease_holder: str,
) -> bool:
    """Delete only a captured, synthetic official preset used by E2E cleanup."""
    if not dsn or not supabase_url:
        raise RuntimeError("тестовой базе не заданы обязательные параметры")
    assert_test_project(dsn, supabase_url)
    if not any(candidate.name == slot_name for candidate in SLOTS):
        raise ValueError("Неизвестный слот тестовых аккаунтов")

    connection = await asyncpg.connect(
        plain_dsn(dsn),
        timeout=CONNECT_TIMEOUT_SECONDS,
    )
    try:
        async with connection.transaction():
            await _require_active_test_slot_lease(connection, slot_name, lease_holder)
            result = await connection.execute(
                "delete from public.prompt_presets "
                "where id = $1 and owner_id is null and title like 'E2E admin fixture:%'",
                preset_id,
            )
    finally:
        await connection.close()
    return result.endswith(" 1")


def build_test_app(
    settings: Settings | None = None,
    *,
    auth_verifier: AuthVerifier | None = None,
) -> FastAPI:
    app_settings = settings or _test_settings()
    # Тестовый контур никогда не ходит во внешние сервисы: ключи обнуляются
    # всегда — и у сборщика _test_settings, и у настроек, пришедших сюда мимо
    # него (например Settings(restore_running_agents=False) в tests/integration).
    # Без этого тесты с кастомными настройками звали бы настоящие Mem0 и
    # Braintrust из .env разработчика.
    app_settings = app_settings.model_copy(
        update={"mem0_api_key": None, "braintrust_api_key": None}
    )
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

    @application.get("/__test__/admin-role")
    async def get_admin_role(request: Request, slot: str, owner_id: UUID) -> dict[str, bool]:
        try:
            enabled = await get_test_admin_role(
                dsn,
                settings.supabase_url,
                slot,
                owner_id,
                lease_holder=request.headers.get(TEST_SLOT_HOLDER_HEADER, ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return {"enabled": enabled}

    @application.put("/__test__/admin-role")
    async def set_admin_role(request: Request, values: TestAdminRoleRequest) -> dict[str, bool]:
        try:
            previously_enabled = await set_test_admin_role(
                dsn,
                settings.supabase_url,
                values.slot,
                values.owner_id,
                lease_holder=request.headers.get(TEST_SLOT_HOLDER_HEADER, ""),
                enabled=values.enabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return {"previously_enabled": previously_enabled, "enabled": values.enabled}

    @application.delete("/__test__/admin-presets/{preset_id}")
    async def remove_test_official_preset(
        request: Request,
        preset_id: UUID,
        slot: str,
    ) -> dict[str, bool]:
        try:
            deleted = await delete_test_official_preset(
                dsn,
                settings.supabase_url,
                preset_id,
                slot_name=slot,
                lease_holder=request.headers.get(TEST_SLOT_HOLDER_HEADER, ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Тестовый официальный пресет не найден",
            )
        return {"deleted": True}

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

    @application.post("/__test__/telegram/{agent_id}/dialogs")
    async def seed_dialogs(agent_id: UUID, request: DialogsRequest) -> dict[str, str]:
        """Задаёт диалоги аккаунта агента: их увидит настройка «Чаты и каналы»."""
        registry.account_for(agent_id).dialogs = [
            FakeDialog(**dialog.model_dump()) for dialog in request.dialogs
        ]
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
        await seed_agent(
            store,
            OnboardingSession(
                onboarding_id=agent_id,
                owner_id=request.owner_id,
                authorization_status=TelegramLoginStatus.AUTHORIZED,
                api_id=1,
                api_hash_secret=(cipher.encrypt("test-api-hash") if cipher else "test-api-hash"),
                session_secret=(cipher.encrypt("test-session") if cipher else "test-session"),
                phone_number=request.phone_number,
                name=request.name,
                soul_prompt=request.soul_prompt,
            ),
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


if os.environ.get("DATABASE_CONNECTION_STRING"):
    # Строится только когда переменные окружения реально заданы: иначе
    # простой импорт этого модуля (например, во время сбора тестов без
    # базы) падал бы независимо от маркера db.
    app = build_test_app()
