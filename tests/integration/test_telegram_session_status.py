from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import errors

from mimic42.core.agent_runtime import (
    REVOKED_SESSION_MESSAGE,
    AgentTrigger,
    MimicAgentRuntime,
    TelegramAuthorizationRequired,
)
from mimic42.core.onboarding import OnboardingSession, TelegramLoginStatus
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.integrations.database_models import AgentModel, TelegramSessionModel
from mimic42.integrations.database_onboarding import DatabaseOnboardingRepository
from mimic42.integrations.database_proxies import lock_proxy_pool
from mimic42.testing import seed_rebind
from mimic42.testing.slots import Slot
from mimic42.testing.telegram import FakeTelegramAccount

from ..core.test_agent_runtime import FakeLangChainAgent, FakeTelegramClient, make_config


async def _seed_agent_with_session(
    db_session_factory: async_sessionmaker[AsyncSession],
    *,
    agent_id: UUID,
    owner_id: UUID,
) -> None:
    """Агент и его привязанная сессия: telegram_sessions ссылается на agents."""
    async with db_session_factory() as session:
        session.add(
            AgentModel(
                id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                soul_prompt="soul",
            )
        )
        session.add(
            TelegramSessionModel(
                agent_id=agent_id,
                session_name=agent_id.hex,
                phone_number="+10000000000",
                api_id=12345,
                api_hash_ciphertext="new-hash",
                session_ciphertext="old-session",
                authorization_status="authorized",
            )
        )
        await session.commit()


async def test_unauthorized_start_marks_session_revoked(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("flow").user_id
    agent_id = uuid4()
    await _seed_agent_with_session(db_session_factory, agent_id=agent_id, owner_id=owner_id)

    runtime = MimicAgentRuntime(
        config=make_config(agent_id, owner_id).model_copy(
            update={"telegram_session_token": "old-session"}
        ),
        telegram_client=FakeTelegramClient(FakeTelegramAccount()),
        langchain_agent=FakeLangChainAgent(),
        session_factory=db_session_factory,
    )

    with pytest.raises(TelegramAuthorizationRequired):
        await runtime.start()

    async with db_session_factory() as session:
        row = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
        agent = await session.get(AgentModel, agent_id)
    assert row is not None
    assert row.authorization_status == "revoked"
    assert row.last_error == REVOKED_SESSION_MESSAGE
    assert agent is not None
    assert agent.status == "error"


async def test_authorized_start_keeps_session_status_untouched(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("flow").user_id
    agent_id = uuid4()
    await _seed_agent_with_session(db_session_factory, agent_id=agent_id, owner_id=owner_id)

    runtime = MimicAgentRuntime(
        config=make_config(agent_id, owner_id).model_copy(
            update={"telegram_session_token": "old-session"}
        ),
        telegram_client=FakeTelegramClient(),
        langchain_agent=FakeLangChainAgent(),
        session_factory=db_session_factory,
    )

    await runtime.start()
    await runtime.stop()

    async with db_session_factory() as session:
        row = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
    assert row is not None
    assert row.authorization_status == "authorized"
    assert row.last_error is None


async def test_authorized_start_backfills_username(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("flow").user_id
    agent_id = uuid4()
    await _seed_agent_with_session(db_session_factory, agent_id=agent_id, owner_id=owner_id)
    account = FakeTelegramAccount()
    account.authorized = True
    account.username = "mimic_user"

    runtime = MimicAgentRuntime(
        config=make_config(agent_id, owner_id).model_copy(
            update={"telegram_session_token": "old-session"}
        ),
        telegram_client=FakeTelegramClient(account),
        langchain_agent=FakeLangChainAgent(),
        session_factory=db_session_factory,
    )

    await runtime.start()
    await runtime.stop()

    async with db_session_factory() as session:
        row = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
    assert row is not None
    # Уже зарегистрированные агенты подтягивают @username при старте.
    assert row.username == "mimic_user"


async def test_stale_runtime_does_not_clobber_username(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner_id = clean_slot.persona("flow").user_id
    agent_id = uuid4()
    await _seed_agent_with_session(db_session_factory, agent_id=agent_id, owner_id=owner_id)
    # Строку уже заняла новая сессия (перепривязка), у неё свой @username.
    async with db_session_factory() as session:
        await session.execute(
            update(TelegramSessionModel)
            .where(TelegramSessionModel.agent_id == agent_id)
            .values(session_ciphertext="new-session", username="fresh_user")
        )
        await session.commit()
    account = FakeTelegramAccount()
    account.authorized = True
    account.username = "stale_user"

    runtime = MimicAgentRuntime(
        config=make_config(agent_id, owner_id).model_copy(
            update={"telegram_session_token": "old-session"}
        ),
        telegram_client=FakeTelegramClient(account),
        langchain_agent=FakeLangChainAgent(),
        session_factory=db_session_factory,
    )

    with caplog.at_level("WARNING", logger="mimic42.agent_runtime"):
        await runtime.start()
    await runtime.stop()

    async with db_session_factory() as session:
        row = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
    assert row is not None
    assert row.username == "fresh_user"
    assert any("changed or is missing" in record.message for record in caplog.records)


class FailingConnectClient(FakeTelegramClient):
    """Клиент, у которого падает именно подключение, а не проверка авторизации."""

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self._error = error

    async def connect(self) -> None:
        raise self._error


@pytest.mark.parametrize(
    "connect_error",
    [
        errors.AuthKeyDuplicatedError(request=None),
        errors.UnauthorizedError(request=None, message="401: Unauthorized"),
    ],
    ids=["auth_key_duplicated", "unauthorized"],
)
async def test_dead_session_error_on_connect_marks_session_revoked(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    connect_error: Exception,
) -> None:
    owner_id = clean_slot.persona("flow").user_id
    agent_id = uuid4()
    await _seed_agent_with_session(db_session_factory, agent_id=agent_id, owner_id=owner_id)

    runtime = MimicAgentRuntime(
        config=make_config(agent_id, owner_id).model_copy(
            update={"telegram_session_token": "old-session"}
        ),
        telegram_client=FailingConnectClient(connect_error),
        langchain_agent=FakeLangChainAgent(),
        session_factory=db_session_factory,
    )

    with pytest.raises(TelegramAuthorizationRequired):
        await runtime.start()

    async with db_session_factory() as session:
        row = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
        agent = await session.get(AgentModel, agent_id)
    assert row is not None
    assert row.authorization_status == "revoked"
    assert row.last_error == REVOKED_SESSION_MESSAGE
    assert agent is not None
    assert agent.status == "error"


class FailingSendClient(FakeTelegramClient):
    """Клиент, который теряет авторизацию уже во время отправки."""

    async def send_message(self, entity: str | int, message: str, **kwargs: Any) -> object:
        raise errors.UnauthorizedError(request=None, message="401: Unauthorized")


async def test_dead_session_error_on_send_marks_session_revoked(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("flow").user_id
    agent_id = uuid4()
    await _seed_agent_with_session(db_session_factory, agent_id=agent_id, owner_id=owner_id)

    runtime = MimicAgentRuntime(
        config=make_config(agent_id, owner_id).model_copy(
            update={"telegram_session_token": "old-session"}
        ),
        telegram_client=FailingSendClient(),
        langchain_agent=FakeLangChainAgent(response="reply"),
        session_factory=db_session_factory,
    )

    result = await runtime.trigger_message(AgentTrigger(peer="me", text="hi"))
    await runtime.stop()

    # Доставка сорвалась, но ход не падает наружу: сессия просто помечается мёртвой.
    assert result.response_text == "reply"

    async with db_session_factory() as session:
        row = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
    assert row is not None
    assert row.authorization_status == "revoked"
    assert row.last_error == REVOKED_SESSION_MESSAGE


async def test_old_runtime_cannot_revoke_newly_rebound_session(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("flow").user_id
    agent_id = uuid4()
    await _seed_agent_with_session(db_session_factory, agent_id=agent_id, owner_id=owner_id)

    old_runtime = MimicAgentRuntime(
        config=make_config(agent_id, owner_id).model_copy(
            update={"telegram_session_token": "old-session"}
        ),
        telegram_client=FailingSendClient(),
        langchain_agent=FakeLangChainAgent(),
        session_factory=db_session_factory,
    )
    store = DatabaseAgentStore(db_session_factory)
    await seed_rebind(
        store,
        agent_id,
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="new-hash",
            phone_number="+10000000000",
            session_secret="new-session",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
        ),
    )

    await old_runtime._mark_telegram_session_revoked(error=REVOKED_SESSION_MESSAGE)

    async with db_session_factory() as session:
        row = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
        agent = await session.get(AgentModel, agent_id)
    assert row is not None
    assert row.session_ciphertext == "new-session"
    assert row.authorization_status == "authorized"
    assert row.last_error is None
    assert agent is not None
    assert agent.status == "draft"


async def _wait_for_blocker(session: AsyncSession, pid: int, blocker: int) -> None:
    async with asyncio.timeout(5):
        while blocker not in await session.scalar(
            text("select pg_blocking_pids(:pid)"), {"pid": pid}
        ):
            pass


async def test_revoke_waits_for_rebind_before_locking_telegram_session(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("flow").user_id
    agent_id = uuid4()
    await _seed_agent_with_session(db_session_factory, agent_id=agent_id, owner_id=owner_id)
    agent_locked = asyncio.Event()
    release_rebind = asyncio.Event()
    runtime_pid = asyncio.get_running_loop().create_future()
    rebind_pid = asyncio.get_running_loop().create_future()

    class RebindSession(AsyncSession):
        async def scalar(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
            result = await super().scalar(statement, *args, **kwargs)
            if isinstance(result, AgentModel):
                rebind_pid.set_result(await super().scalar(text("select pg_backend_pid()")))
                agent_locked.set()
                await release_rebind.wait()
            return result

    class RevokeSession(AsyncSession):
        async def __aenter__(self) -> AsyncSession:
            await super().__aenter__()
            runtime_pid.set_result(await self.scalar(text("select pg_backend_pid()")))
            return self

    rebind_factory = async_sessionmaker(
        bind=db_session_factory.kw["bind"], class_=RebindSession, expire_on_commit=False
    )
    revoke_factory = async_sessionmaker(
        bind=db_session_factory.kw["bind"], class_=RevokeSession, expire_on_commit=False
    )
    runtime = MimicAgentRuntime(
        config=make_config(agent_id, owner_id).model_copy(
            update={"telegram_session_token": "old-session"}
        ),
        telegram_client=FakeTelegramClient(),
        langchain_agent=FakeLangChainAgent(),
        session_factory=revoke_factory,
    )
    rebind = asyncio.create_task(
        DatabaseOnboardingRepository(rebind_factory).begin_rebind(agent_id, owner_id=owner_id)
    )
    revoke = None
    try:
        async with asyncio.timeout(5):
            await agent_locked.wait()
        revoke = asyncio.create_task(
            runtime._mark_telegram_session_revoked(error=REVOKED_SESSION_MESSAGE)
        )
        pid = await asyncio.wait_for(runtime_pid, timeout=5)
        async with db_session_factory() as observer:
            await _wait_for_blocker(observer, pid, rebind_pid.result())
            row = await observer.scalar(
                select(TelegramSessionModel)
                .where(TelegramSessionModel.agent_id == agent_id)
                .with_for_update(nowait=True)
            )
            assert row is not None
            assert row.authorization_status == "authorized"
    finally:
        release_rebind.set()
        await asyncio.wait_for(
            asyncio.gather(rebind, *([revoke] if revoke is not None else [])), timeout=10
        )

    async with db_session_factory() as session:
        telegram = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
        agent = await session.get(AgentModel, agent_id)
    assert telegram is not None
    assert telegram.authorization_status == "revoked"
    assert telegram.session_ciphertext == "old-session"
    assert agent is not None
    assert agent.status == "error"


@pytest.mark.parametrize(
    ("table", "role"), [("agents", "authenticated"), ("profiles", "service_role")]
)
async def test_parent_delete_waits_for_pool_before_locking_agent(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    table: str,
    role: str,
) -> None:
    owner_id = clean_slot.persona("flow").user_id
    agent_id = uuid4()
    await _seed_agent_with_session(db_session_factory, agent_id=agent_id, owner_id=owner_id)
    repository = DatabaseOnboardingRepository(db_session_factory)
    await repository.begin_rebind(agent_id, owner_id=owner_id)
    async with (
        db_session_factory() as holder,
        db_session_factory() as deleting,
        db_session_factory() as observer,
    ):
        await lock_proxy_pool(holder)
        blocker = await holder.scalar(text("select pg_backend_pid()"))
        await deleting.execute(text(f"set local role {role}"))
        await deleting.execute(
            text("select set_config('request.jwt.claim.sub', :owner, true)"),
            {"owner": str(owner_id)},
        )
        pid = await deleting.scalar(text("select pg_backend_pid()"))
        deletion = asyncio.create_task(
            deleting.execute(
                text(f"delete from public.{table} where id = :id returning id"),
                {"id": agent_id if table == "agents" else owner_id},
            )
        )
        try:
            await _wait_for_blocker(observer, pid, blocker)
            assert (
                await observer.scalar(
                    select(AgentModel.id)
                    .where(AgentModel.id == agent_id)
                    .with_for_update(nowait=True)
                )
                == agent_id
            )
            await observer.rollback()
            await holder.commit()
            assert (await asyncio.wait_for(deletion, timeout=5)).scalar_one() == (
                agent_id if table == "agents" else owner_id
            )
        finally:
            await observer.rollback()
            await holder.rollback()
            await asyncio.wait_for(deletion, timeout=5)
            await deleting.rollback()


class BrokenSessionFactory:
    """Фабрика сессий, у которой падает даже вызов."""

    def __call__(self) -> object:
        raise RuntimeError("database is down")


async def test_broken_database_does_not_replace_authorization_error() -> None:
    runtime = MimicAgentRuntime(
        config=make_config(uuid4(), uuid4()).model_copy(
            update={"telegram_session_token": "old-session"}
        ),
        telegram_client=FakeTelegramClient(FakeTelegramAccount()),
        langchain_agent=FakeLangChainAgent(),
        session_factory=cast(async_sessionmaker[AsyncSession], BrokenSessionFactory()),
    )

    with pytest.raises(TelegramAuthorizationRequired):
        await runtime.start()


async def test_missing_session_row_does_not_replace_authorization_error(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner_id = clean_slot.persona("flow").user_id
    agent_id = uuid4()
    async with db_session_factory() as session:
        session.add(AgentModel(id=agent_id, owner_id=owner_id, name="Mimic", soul_prompt="soul"))
        await session.commit()

    runtime = MimicAgentRuntime(
        config=make_config(agent_id, owner_id).model_copy(
            update={"telegram_session_token": "old-session"}
        ),
        telegram_client=FakeTelegramClient(FakeTelegramAccount()),
        langchain_agent=FakeLangChainAgent(),
        session_factory=db_session_factory,
    )

    with caplog.at_level("WARNING", logger="mimic42.agent_runtime"):
        with pytest.raises(TelegramAuthorizationRequired):
            await runtime.start()

    assert any("changed or is missing" in record.message for record in caplog.records)
