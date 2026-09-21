from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import (
    UNAUTHORIZED_SESSION_MESSAGE,
    MimicAgentRuntime,
    TelegramAuthorizationRequired,
)
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
        config=make_config(agent_id, owner_id),
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
    assert row is not None
    assert row.authorization_status == "revoked"
    assert row.last_error == UNAUTHORIZED_SESSION_MESSAGE


async def test_authorized_start_keeps_session_status_untouched(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("flow").user_id
    agent_id = uuid4()
    await _seed_agent_with_session(db_session_factory, agent_id=agent_id, owner_id=owner_id)

    runtime = MimicAgentRuntime(
        config=make_config(agent_id, owner_id),
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


class BrokenSessionFactory:
    """Фабрика сессий, у которой падает даже вызов."""

    def __call__(self) -> object:
        raise RuntimeError("database is down")


async def test_broken_database_does_not_replace_authorization_error() -> None:
    runtime = MimicAgentRuntime(
        config=make_config(uuid4(), uuid4()),
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
        config=make_config(agent_id, owner_id),
        telegram_client=FakeTelegramClient(FakeTelegramAccount()),
        langchain_agent=FakeLangChainAgent(),
        session_factory=db_session_factory,
    )

    with caplog.at_level("WARNING", logger="mimic42.agent_runtime"):
        with pytest.raises(TelegramAuthorizationRequired):
            await runtime.start()

    assert any("No telegram_sessions row" in record.message for record in caplog.records)
