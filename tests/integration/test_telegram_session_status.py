from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
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
    await store.rebind_telegram_session(
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
