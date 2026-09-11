from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.model_catalog import DEFAULT_LLM_MODEL
from mimic42.core.onboarding import OnboardingSession, TelegramLoginStatus
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.integrations.database_models import (
    AgentEventModel,
    AgentMessageModel,
    AgentModel,
    AgentOnboardingSessionModel,
    Base,
    ProfileModel,
    TelegramSessionModel,
)


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    # SQLite needs an explicit pragma to honour ON DELETE CASCADE like Postgres does
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(
        dbapi_connection: Any,
        connection_record: Any,
    ) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_agent_store_creates_agent_session_and_runtime_config(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = uuid4()
    onboarding_id = uuid4()
    async with session_factory() as session:
        session.add(ProfileModel(id=owner_id))
        await session.commit()

    store = DatabaseAgentStore(session_factory)
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="encrypted-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="encrypted-session",
            name="Mimic",
            soul_prompt="Soul",
        )
    )

    agents = await store.list_agents(owner_id=owner_id)
    runtime_config = await store.get_runtime_config(onboarding_id)
    await store.update_status(onboarding_id, AgentRuntimeState.RUNNING)
    updated_agents = await store.list_agents(owner_id=owner_id)

    assert agents[0].name == "Mimic"
    assert runtime_config.telegram_api_hash == "encrypted-hash"
    assert runtime_config.telegram_session_string == "encrypted-session"
    assert runtime_config.llm_model == DEFAULT_LLM_MODEL
    assert updated_agents[0].state is AgentRuntimeState.RUNNING


def _make_session(owner_id: UUID, onboarding_id: UUID, name: str) -> OnboardingSession:
    return OnboardingSession(
        onboarding_id=onboarding_id,
        owner_id=owner_id,
        api_id=12345,
        api_hash_secret="encrypted-hash",
        phone_number="+79990000000",
        authorization_status=TelegramLoginStatus.AUTHORIZED,
        session_secret="encrypted-session",
        name=name,
        soul_prompt="Soul",
    )


@pytest.mark.asyncio
async def test_create_from_onboarding_twice_creates_two_agents(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = uuid4()
    async with session_factory() as session:
        session.add(ProfileModel(id=owner_id))
        await session.commit()

    store = DatabaseAgentStore(session_factory)
    first_id = uuid4()
    second_id = uuid4()
    await store.create_from_onboarding(_make_session(owner_id, first_id, "First"))
    await store.create_from_onboarding(_make_session(owner_id, second_id, "Second"))

    agents = await store.list_agents(owner_id=owner_id)

    assert {agent.agent_id for agent in agents} == {first_id, second_id}


@pytest.mark.asyncio
async def test_delete_agent_removes_agent_and_onboarding_row_only_for_it(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = uuid4()
    async with session_factory() as session:
        session.add(ProfileModel(id=owner_id))
        await session.commit()

    store = DatabaseAgentStore(session_factory)
    first_id = uuid4()
    second_id = uuid4()
    await store.create_from_onboarding(_make_session(owner_id, first_id, "First"))
    await store.create_from_onboarding(_make_session(owner_id, second_id, "Second"))

    async with session_factory() as session:
        # The originating onboarding row: id == agent id, finalize marker lost
        session.add(
            AgentOnboardingSessionModel(
                id=first_id,
                owner_id=owner_id,
                authorization_status=TelegramLoginStatus.AUTHORIZED.value,
            )
        )
        session.add(
            AgentOnboardingSessionModel(
                id=uuid4(),
                owner_id=owner_id,
                completed_agent_id=first_id,
                authorization_status=TelegramLoginStatus.AUTHORIZED.value,
            )
        )
        session.add(
            AgentOnboardingSessionModel(
                id=uuid4(),
                owner_id=owner_id,
                completed_agent_id=second_id,
                authorization_status=TelegramLoginStatus.AUTHORIZED.value,
            )
        )
        await session.commit()

    await store.delete_agent(first_id)

    agents = await store.list_agents(owner_id=owner_id)
    assert [agent.agent_id for agent in agents] == [second_id]

    async with session_factory() as session:
        from sqlalchemy import select

        onboarding_rows = (await session.scalars(select(AgentOnboardingSessionModel))).all()
        assert len(onboarding_rows) == 1
        assert onboarding_rows[0].completed_agent_id == second_id

        telegram_sessions = (await session.scalars(select(TelegramSessionModel))).all()
        assert [session_row.agent_id for session_row in telegram_sessions] == [second_id]


@pytest.mark.asyncio
async def test_delete_agent_for_missing_agent_is_noop(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = DatabaseAgentStore(session_factory)

    await store.delete_agent(uuid4())


@pytest.mark.asyncio
async def test_database_conversation_groups_messages_and_tool_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    base = datetime(2026, 5, 19, 23, 30, tzinfo=UTC)
    # NOTE: profile, agent, and messages are committed in separate sessions.
    # Same-flush parent+child inserts misorder under the FK pragma
    # (pre-existing SQLAlchemy UoW quirk, unrelated to conversation logic).
    async with session_factory() as session:
        session.add(ProfileModel(id=owner_id))
        await session.commit()
    async with session_factory() as session:
        session.add(
            AgentModel(
                id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                status=AgentRuntimeState.STOPPED.value,
                soul_prompt="Soul",
            )
        )
        await session.commit()
    async with session_factory() as session:
        session.add(
            AgentMessageModel(
                agent_id=agent_id,
                direction="incoming",
                role="user",
                content="hi",
                payload={"peer": "chat", "peer_name": "Ivan"},
                created_at=base,
            )
        )
        session.add(
            AgentEventModel(
                agent_id=agent_id,
                event_type="get_profile",
                status="succeeded",
                payload={"args": {"peer": "chat"}, "parent_peer": "chat"},
                created_at=base + timedelta(seconds=1),
                started_at=base,
                completed_at=base + timedelta(seconds=1),
            )
        )
        session.add(
            AgentMessageModel(
                agent_id=agent_id,
                direction="agent_response",
                role="assistant",
                content="hello",
                payload={"peer": "chat", "agent_name": "Mimic"},
                created_at=base + timedelta(seconds=2),
            )
        )
        # Orphan outgoing (proactive message, direction "outgoing")
        session.add(
            AgentMessageModel(
                agent_id=agent_id,
                direction="outgoing",
                role="assistant",
                content="proactive",
                payload={"peer": "chat", "agent_name": "Mimic"},
                created_at=base + timedelta(seconds=3),
            )
        )
        await session.commit()

    store = DatabaseAgentStore(session_factory)
    turns = await store.get_conversation(agent_id=agent_id)

    # Newest first: proactive outgoing, then the grouped both-turn.
    assert len(turns) == 2
    assert turns[0].direction == "outgoing"
    assert turns[0].outgoing == "proactive"
    grouped = turns[1]
    assert grouped.direction == "both"
    assert grouped.incoming == "hi"
    assert grouped.outgoing == "hello"
    assert len(grouped.tools) == 1
    assert grouped.tools[0].name == "get_profile"
    assert grouped.tools[0].duration_ms == 1000.0

    limited = await store.get_conversation(agent_id=agent_id, limit=1)
    assert len(limited) == 1
    assert limited[0].outgoing == "proactive"
