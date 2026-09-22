from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.integrations.database_memory import DatabaseShortTermMemory
from mimic42.integrations.database_models import AgentEventModel, AgentMessageModel, AgentModel
from mimic42.testing.slots import Slot

PEER = "12345"


async def _create_agent(
    db_session_factory: async_sessionmaker[AsyncSession], owner_id: UUID
) -> UUID:
    agent_id = uuid4()
    async with db_session_factory() as session:
        session.add(
            AgentModel(
                id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                status=AgentRuntimeState.RUNNING.value,
                soul_prompt="Soul",
            )
        )
        await session.commit()
    return agent_id


async def _save_turn(memory: DatabaseShortTermMemory, agent_id: UUID, text: str) -> None:
    await memory.save_messages(
        agent_id=agent_id,
        peer=PEER,
        messages=[{"role": "assistant", "content": f"Ответ на {text}"}],
        raw_user_text=text,
    )


async def _load_context(memory: DatabaseShortTermMemory, agent_id: UUID) -> set[str]:
    # The incoming row and the reply of one turn share created_at, so their
    # order is not part of the contract here.
    messages = await memory.load_recent_messages(
        agent_id=agent_id,
        peer=PEER,
        since=datetime.now(UTC) - timedelta(hours=1),
    )
    return {message["content"] for message in messages}


async def test_reset_hides_earlier_messages_from_context_but_keeps_history(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    agent_id = await _create_agent(db_session_factory, owner_id)
    memory = DatabaseShortTermMemory(db_session_factory)
    store = DatabaseAgentStore(db_session_factory)

    await _save_turn(memory, agent_id, "до сброса")
    assert await _load_context(memory, agent_id) == {"до сброса", "Ответ на до сброса"}

    reset_at = await store.reset_context(agent_id, actor_user_id=owner_id)
    assert await _load_context(memory, agent_id) == set()

    await _save_turn(memory, agent_id, "после сброса")
    assert await _load_context(memory, agent_id) == {"после сброса", "Ответ на после сброса"}

    async with db_session_factory() as session:
        agent = await session.get(AgentModel, agent_id)
        assert agent is not None
        assert agent.context_reset_at == reset_at
        stored = await session.scalar(
            select(func.count())
            .select_from(AgentMessageModel)
            .where(AgentMessageModel.agent_id == agent_id)
        )
        assert stored == 4
        event = await session.scalar(
            select(AgentEventModel).where(
                AgentEventModel.agent_id == agent_id,
                AgentEventModel.event_type == "agent.context_reset",
            )
        )
        assert event is not None
        assert event.status == "succeeded"
        assert event.actor_user_id == owner_id


async def test_reset_of_one_agent_leaves_other_agents_context(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    reset_agent = await _create_agent(db_session_factory, owner_id)
    other_agent = await _create_agent(db_session_factory, owner_id)
    memory = DatabaseShortTermMemory(db_session_factory)

    await _save_turn(memory, reset_agent, "первый")
    await _save_turn(memory, other_agent, "второй")
    await DatabaseAgentStore(db_session_factory).reset_context(reset_agent, actor_user_id=owner_id)

    assert await _load_context(memory, reset_agent) == set()
    assert await _load_context(memory, other_agent) == {"второй", "Ответ на второй"}


async def test_reset_of_missing_agent_raises_key_error(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    store = DatabaseAgentStore(db_session_factory)
    with pytest.raises(KeyError):
        await store.reset_context(uuid4(), actor_user_id=clean_slot.persona("twofa").user_id)
