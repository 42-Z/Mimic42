from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.token_usage import TokenUsageRecorder
from mimic42.integrations.database_models import AgentModel, AgentTokenUsageModel
from mimic42.testing.slots import Slot


async def _seed_agent(
    db_session_factory: async_sessionmaker[AsyncSession],
    *,
    agent_id: UUID,
    owner_id: UUID,
) -> None:
    async with db_session_factory() as session:
        session.add(
            AgentModel(
                id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                soul_prompt="soul",
            )
        )
        await session.commit()


async def test_token_usage_recorder_accumulates_per_agent(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()
    await _seed_agent(db_session_factory, agent_id=agent_id, owner_id=owner_id)

    recorder = TokenUsageRecorder(db_session_factory)
    await recorder.add(agent_id=agent_id, input_tokens=100, output_tokens=20)
    await recorder.add(agent_id=agent_id, input_tokens=50, output_tokens=10)

    async with db_session_factory() as session:
        row = await session.get(AgentTokenUsageModel, agent_id)

    assert row is not None
    assert row.input_tokens == 150
    assert row.output_tokens == 30
