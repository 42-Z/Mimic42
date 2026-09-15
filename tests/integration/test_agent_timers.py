from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import MimicAgentRuntime
from mimic42.integrations.database_models import AgentModel, AgentTimerModel
from mimic42.integrations.telegram_tools import TelegramToolbox
from mimic42.testing.slots import Slot
from tests.core.test_agent_runtime import FakeLangChainAgent, FakeTelegramClient, make_config


async def test_set_wakeup_timer_tool_and_scheduler(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("empty").user_id
    agent_id = uuid4()

    async with db_session_factory() as session:
        session.add(
            AgentModel(
                id=agent_id,
                owner_id=owner_id,
                name="Test Agent",
            )
        )
        await session.commit()

    telegram = FakeTelegramClient()
    runtime = MimicAgentRuntime(
        config=make_config(agent_id=agent_id, owner_id=owner_id),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(response="timer triggered reply"),
        session_factory=db_session_factory,
    )

    toolbox = TelegramToolbox(telegram, agent_id=agent_id, session_factory=db_session_factory)

    res = await toolbox.set_wakeup_timer(
        peer="12345", delay_seconds=0, description="Process analytics"
    )
    assert res["success"] is True

    stmt = select(AgentTimerModel).where(AgentTimerModel.agent_id == agent_id)
    async with db_session_factory() as session:
        db_timers = list(await session.scalars(stmt))
        assert len(db_timers) == 1
        assert db_timers[0].peer == "12345"
        assert db_timers[0].status == "pending"
        assert db_timers[0].description == "Process analytics"

    # Call scheduler trigger manually (without start() loop to avoid dual trigger race condition)
    await runtime._check_and_trigger_timers()

    async with db_session_factory() as session:
        db_timers = list(await session.scalars(stmt))
        assert db_timers[0].status == "succeeded"

    assert len(telegram.sent_messages) == 1
    assert telegram.sent_messages[0] == ("12345", "timer triggered reply")
