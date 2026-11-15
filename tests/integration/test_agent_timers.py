from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import types, utils

from mimic42.core.agent_runtime import AgentRuntimeState, MimicAgentRuntime
from mimic42.core.chat_access import ChatAccess
from mimic42.integrations.database_models import AgentEventModel, AgentModel, AgentTimerModel
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
    runtime._state = AgentRuntimeState.RUNNING
    await runtime._check_and_trigger_timers()

    async with db_session_factory() as session:
        db_timers = list(await session.scalars(stmt))
        assert db_timers[0].status == "succeeded"

    assert len(telegram.sent_messages) == 1
    assert telegram.sent_messages[0] == ("12345", "timer triggered reply")


async def test_timer_for_a_disabled_chat_fails_without_a_turn(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = clean_slot.persona("empty").user_id
    agent_id = uuid4()
    async with db_session_factory() as session:
        session.add(AgentModel(id=agent_id, owner_id=owner_id, name="Test Agent"))
        await session.commit()
    async with db_session_factory() as session:
        session.add(
            AgentTimerModel(
                agent_id=agent_id,
                peer="12345",
                trigger_at=datetime.now(UTC) - timedelta(seconds=1),
                description="Напомнить",
                status="pending",
            )
        )
        await session.commit()

    async def never_linked(chat_id: int) -> int | None:
        return None

    telegram = FakeTelegramClient()

    async def get_input_entity(peer: object) -> Any:
        return types.InputPeerUser(user_id=int(str(peer)), access_hash=1)

    async def get_peer_id(peer: object, add_mark: bool = True) -> int:
        return utils.get_peer_id(peer)

    telegram.get_input_entity = get_input_entity  # ty: ignore[unresolved-attribute]
    telegram.get_peer_id = get_peer_id  # ty: ignore[unresolved-attribute]
    runtime = MimicAgentRuntime(
        config=make_config(agent_id=agent_id, owner_id=owner_id),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(response="не должен ответить"),
        session_factory=db_session_factory,
        chat_access=ChatAccess(frozenset({12345}), never_linked),
    )
    events: list[dict[str, Any]] = []

    async def record_event(**kwargs: Any) -> None:
        events.append(kwargs)

    monkeypatch.setattr(runtime, "_record_event", record_event)

    await runtime._check_and_trigger_timers()

    async with db_session_factory() as session:
        timers = list(
            await session.scalars(
                select(AgentTimerModel).where(AgentTimerModel.agent_id == agent_id)
            )
        )
    assert [timer.status for timer in timers] == ["failed"]
    assert telegram.sent_messages == []
    assert [(e["event_type"], e["status"], e["payload"]["error_code"]) for e in events] == [
        ("timer.failed", "failed", "ChatDisabledError")
    ]


@pytest.mark.parametrize("during_turn", [False, True])
async def test_cancelled_timer_preserves_queue_and_restart_does_not_repeat_partial_turn(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    monkeypatch: pytest.MonkeyPatch,
    during_turn: bool,
) -> None:
    owner_id = clean_slot.persona("empty").user_id
    agent_id = uuid4()
    now = datetime.now(UTC)
    async with db_session_factory() as session:
        session.add(AgentModel(id=agent_id, owner_id=owner_id, name="Timers"))
        await session.commit()
        for index in range(3):
            session.add(
                AgentTimerModel(
                    agent_id=agent_id,
                    peer="12345",
                    description=str(index),
                    trigger_at=now - timedelta(seconds=3 - index),
                )
            )
        await session.commit()

    runtime = MimicAgentRuntime(
        config=make_config(agent_id=agent_id, owner_id=owner_id),
        telegram_client=FakeTelegramClient(),
        langchain_agent=FakeLangChainAgent(response="reply"),
        session_factory=db_session_factory,
    )
    runtime._state = AgentRuntimeState.RUNNING
    entered = asyncio.Event()

    async def block(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        await asyncio.Future()

    if during_turn:
        monkeypatch.setattr(runtime, "_take_turn", block)
    else:
        monkeypatch.setattr(runtime, "_ensure_peer_allowed", block)

    query = (
        select(AgentTimerModel)
        .where(AgentTimerModel.agent_id == agent_id)
        .order_by(AgentTimerModel.trigger_at)
    )
    task = asyncio.create_task(runtime._check_and_trigger_timers())
    try:
        await asyncio.wait_for(entered.wait(), 60)
        async with db_session_factory() as session:
            assert [timer.status for timer in await session.scalars(query)] == [
                "running",
                "pending",
                "pending",
            ]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async with db_session_factory() as session:
        assert [timer.status for timer in await session.scalars(query)] == [
            "failed" if during_turn else "pending",
            "pending",
            "pending",
        ]

    telegram = FakeTelegramClient()
    restarted = MimicAgentRuntime(
        config=runtime.config,
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(response="reply"),
        session_factory=db_session_factory,
    )
    restarted._state = AgentRuntimeState.RUNNING
    await restarted._recover_interrupted_timers()
    await restarted._check_and_trigger_timers()
    assert len(telegram.sent_messages) == (2 if during_turn else 3)
    async with db_session_factory() as session:
        assert [timer.status for timer in await session.scalars(query)] == [
            "failed" if during_turn else "succeeded",
            "succeeded",
            "succeeded",
        ]


async def test_start_recovers_orphaned_running_timer_without_replaying_it(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("empty").user_id
    agent_id = uuid4()
    timer_id = uuid4()
    async with db_session_factory() as session:
        session.add(AgentModel(id=agent_id, owner_id=owner_id, name="Timers"))
        await session.commit()
        session.add(
            AgentTimerModel(
                id=timer_id,
                agent_id=agent_id,
                peer="12345",
                description="partial turn",
                trigger_at=datetime.now(UTC),
                status="running",
            )
        )
        await session.commit()
    telegram = FakeTelegramClient()
    runtime = MimicAgentRuntime(
        config=make_config(agent_id=agent_id, owner_id=owner_id),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(response="reply"),
        session_factory=db_session_factory,
    )
    try:
        await runtime.start()
        async with db_session_factory() as session:
            timer = await session.get(AgentTimerModel, timer_id)
            assert timer is not None
            assert timer.status == "failed"
            events = list(
                await session.scalars(
                    select(AgentEventModel).where(
                        AgentEventModel.agent_id == agent_id,
                        AgentEventModel.event_type == "timer.failed",
                    )
                )
            )
        assert len(events) == 1
        assert events[0].payload["error_code"] == "TimerInterrupted"
        assert events[0].payload["timer_id"] == str(timer_id)
        assert telegram.sent_messages == []
    finally:
        await runtime.stop()
