from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from mimic42.core.agent_runtime import AgentRuntimeState, AgentTrigger, MimicAgentRuntime
from mimic42.core.memory import RuntimeMemoryService, TurnInput
from mimic42.testing.telegram import FakeTelegramClient
from tests.core.test_agent_runtime import make_config
from tests.core.test_agent_runtime_tracing import FakeActivity
from tests.core.test_memory import FakeLongTermMemory


class TranscriptStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.context_started = asyncio.Event()
        self.release_context = asyncio.Event()
        self.release_context.set()
        self.context_error: RuntimeError | None = None

    async def save_input(self, incoming: TurnInput) -> None:
        if any(row["turn_id"] == incoming.turn_id for row in self.rows):
            return
        self.rows.append(
            {
                "agent_id": incoming.agent_id,
                "peer": incoming.peer,
                "role": "user",
                "content": incoming.raw_text if incoming.raw_text.strip() else incoming.text,
                "turn_id": incoming.turn_id,
                "created_at": datetime.now(UTC),
                "media": incoming.media,
                "reply": incoming.reply,
                "thread_id": incoming.thread_id,
            }
        )

    async def load_recent_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        since: datetime,
        exclude_turn_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.context_started.set()
        await self.release_context.wait()
        if self.context_error is not None:
            raise self.context_error
        return [
            {
                "type": "human" if row["role"] == "user" else "ai",
                "role": row["role"],
                "content": row["content"],
            }
            for row in self.rows
            if row["agent_id"] == agent_id
            and row["peer"] == peer
            and row["created_at"] >= since
            and (exclude_turn_id is None or row["turn_id"] != exclude_turn_id)
        ]

    async def save_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        messages: list[dict[str, Any]],
        structured_response: dict[str, Any] | None = None,
        peer_name: str = "",
        agent_name: str = "",
        turn_id: str | None = None,
        thread_id: UUID | None = None,
    ) -> None:
        for message in messages:
            role = message.get("role", message.get("type"))
            if role in {"human", "user"}:
                continue
            elif role == "ai":
                role = "assistant"
            self.rows.append(
                {
                    "agent_id": agent_id,
                    "peer": peer,
                    "role": role,
                    "content": message["content"],
                    "turn_id": turn_id,
                    "created_at": datetime.now(UTC),
                    "media": None,
                    "reply": None,
                    "thread_id": thread_id,
                }
            )


class ControlledAgent:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.error: RuntimeError | None = None
        self.inputs: list[list[dict[str, Any]]] = []

    async def ainvoke(
        self, input_data: dict[str, object], context: object | None = None
    ) -> dict[str, object]:
        messages = cast(list[dict[str, Any]], input_data["messages"])
        self.inputs.append(messages)
        self.started.set()
        await self.release.wait()
        if self.error is not None:
            raise self.error
        return {
            "messages": [*messages, {"role": "assistant", "content": "reply"}],
            "structured_response": {"text": "reply", "send_any_message": False},
        }


@pytest.fixture
async def incoming_turn() -> AsyncIterator[
    tuple[MimicAgentRuntime, TranscriptStore, ControlledAgent, FakeActivity]
]:
    store = TranscriptStore()
    agent = ControlledAgent()
    activity = FakeActivity()
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=FakeTelegramClient(),
        langchain_agent=agent,
        memory_service=RuntimeMemoryService(short_term=store),
    )
    runtime._activity = cast(Any, activity)
    try:
        yield runtime, store, agent, activity
    finally:
        await runtime.stop()


@pytest.mark.parametrize("stage", ["context", "model"])
@pytest.mark.parametrize("raw_text", ["", "hello there"], ids=["dashboard", "telegram"])
async def test_incoming_is_visible_before_context_or_model_finishes(
    incoming_turn: tuple[MimicAgentRuntime, TranscriptStore, ControlledAgent, FakeActivity],
    stage: str,
    raw_text: str,
) -> None:
    runtime, store, agent, _ = incoming_turn
    if stage == "context":
        store.release_context.clear()
        started = store.context_started
    else:
        agent.release.clear()
        started = agent.started
    trigger = AgentTrigger(peer="chat", text="hello there", raw_text=raw_text)
    task = asyncio.create_task(runtime.trigger_message(trigger))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        assert not task.done()
        incoming = [row for row in store.rows if row["role"] == "user"]
        assert [row["content"] for row in incoming] == ["hello there"]
        assert incoming[0]["turn_id"]
        if stage == "context":
            assert agent.inputs == []
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_cancelling_turn_records_cancelled_and_keeps_incoming(
    incoming_turn: tuple[MimicAgentRuntime, TranscriptStore, ControlledAgent, FakeActivity],
) -> None:
    runtime, store, agent, activity = incoming_turn
    agent.release.clear()
    task = asyncio.create_task(
        runtime.trigger_message(AgentTrigger(peer="chat", text="keep this", raw_text="keep this"))
    )
    try:
        await asyncio.wait_for(agent.started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    outcomes = [
        event
        for event in activity.events
        if event["event_type"] in {"turn.completed", "turn.failed", "turn.cancelled"}
    ]
    assert [event["event_type"] for event in outcomes] == ["turn.cancelled"]
    assert outcomes[0]["status"] == "cancelled"
    payload = outcomes[0]["payload"]
    assert payload["peer"] == "chat"
    assert payload["turn_id"]
    assert [(row["role"], row["content"]) for row in store.rows] == [("user", "keep this")]
    assert store.rows[0]["turn_id"] == payload["turn_id"]


@pytest.mark.parametrize("stage", ["context", "model"])
@pytest.mark.parametrize("raw_text", ["", "keep this"], ids=["dashboard", "telegram"])
async def test_failed_context_or_model_keeps_incoming_once(
    incoming_turn: tuple[MimicAgentRuntime, TranscriptStore, ControlledAgent, FakeActivity],
    stage: str,
    raw_text: str,
) -> None:
    runtime, store, agent, activity = incoming_turn
    error = RuntimeError("dependency unavailable")
    if stage == "context":
        store.context_error = error
    else:
        agent.error = error

    with pytest.raises(RuntimeError) as caught:
        await runtime.trigger_message(
            AgentTrigger(peer="chat", text="keep this", raw_text=raw_text)
        )

    assert caught.value is error
    assert [(row["role"], row["content"]) for row in store.rows] == [("user", "keep this")]
    failed = [event for event in activity.events if event["event_type"] == "turn.failed"]
    assert len(failed) == 1
    assert failed[0]["status"] == "failed"
    assert store.rows[0]["turn_id"] == failed[0]["payload"]["turn_id"]
    assert store.rows[0]["turn_id"]
    if stage == "context":
        assert agent.inputs == []


@pytest.mark.parametrize("raw_text", ["", "hello there"], ids=["dashboard", "telegram"])
async def test_successful_turn_has_no_duplicate_incoming_or_current_model_input(
    incoming_turn: tuple[MimicAgentRuntime, TranscriptStore, ControlledAgent, FakeActivity],
    raw_text: str,
) -> None:
    runtime, store, agent, activity = incoming_turn
    await runtime.trigger_message(AgentTrigger(peer="chat", text="hello there", raw_text=raw_text))

    assert [(row["role"], row["content"]) for row in store.rows] == [
        ("user", "hello there"),
        ("assistant", "reply"),
    ]
    assert len(agent.inputs) == 1
    assert [message["content"] for message in agent.inputs[0] if message["role"] == "user"] == [
        "hello there"
    ]
    completed = [event for event in activity.events if event["event_type"] == "turn.completed"]
    assert len(completed) == 1
    assert {row["turn_id"] for row in store.rows} == {completed[0]["payload"]["turn_id"]}


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
async def test_long_term_memory_receives_only_final_successful_turn(
    incoming_turn: tuple[MimicAgentRuntime, TranscriptStore, ControlledAgent, FakeActivity],
    outcome: str,
) -> None:
    runtime, store, agent, _ = incoming_turn
    long_term = FakeLongTermMemory()
    runtime._memory_service = RuntimeMemoryService(short_term=store, long_term=long_term)
    if outcome == "failed":
        agent.error = RuntimeError("model unavailable")
    elif outcome == "cancelled":
        agent.release.clear()
    task = asyncio.create_task(runtime.trigger_message(AgentTrigger(peer="chat", text="current")))
    try:
        await asyncio.wait_for(agent.started.wait(), timeout=2)
        assert store.rows[0]["content"] == "current"
        if outcome == "cancelled":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif outcome == "failed":
            with pytest.raises(RuntimeError, match="model unavailable"):
                await task
        else:
            await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    if outcome == "completed":
        assert long_term.saved == [(str(runtime.config.agent_id), "current", "reply")]
    else:
        assert long_term.saved == []


async def test_cancellation_during_input_commit_waits_before_recording_outcome(
    incoming_turn: tuple[MimicAgentRuntime, TranscriptStore, ControlledAgent, FakeActivity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, store, agent, activity = incoming_turn
    started = asyncio.Event()
    release = asyncio.Event()
    save_input = store.save_input

    async def delayed_input(incoming: TurnInput) -> None:
        started.set()
        await release.wait()
        await save_input(incoming)

    monkeypatch.setattr(store, "save_input", delayed_input)
    task = asyncio.create_task(runtime.trigger_message(AgentTrigger(peer="chat", text="keep")))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert not any(event["event_type"] == "turn.cancelled" for event in activity.events)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert [row["content"] for row in store.rows] == ["keep"]
    assert agent.inputs == []
    assert not store.context_started.is_set()
    assert len([event for event in activity.events if event["event_type"] == "turn.cancelled"]) == 1


@pytest.mark.parametrize("outcome", ["turn.cancelled", "turn.completed"])
@pytest.mark.parametrize("storage_fails", [False, True])
async def test_cancellation_settles_terminal_write_without_duplicate_outcome(
    incoming_turn: tuple[MimicAgentRuntime, TranscriptStore, ControlledAgent, FakeActivity],
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    storage_fails: bool,
) -> None:
    runtime, store, agent, activity = incoming_turn
    started = asyncio.Event()
    release = asyncio.Event()
    record = activity.record

    async def delayed_record(**event: Any) -> None:
        if event["event_type"] == outcome:
            started.set()
            await release.wait()
            if storage_fails:
                raise RuntimeError("storage unavailable")
        await record(**event)

    monkeypatch.setattr(activity, "record", delayed_record)
    if outcome == "turn.cancelled":
        agent.release.clear()
    task = asyncio.create_task(runtime.trigger_message(AgentTrigger(peer="chat", text="keep")))
    try:
        if outcome == "turn.cancelled":
            await asyncio.wait_for(agent.started.wait(), timeout=2)
            task.cancel()
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    terminal = [event for event in activity.events if event["event_type"].startswith("turn.")]
    assert [event["event_type"] for event in terminal] == ([] if storage_fails else [outcome])
    assert store.rows[0]["content"] == "keep"
    if terminal:
        assert terminal[0]["started_at"] <= terminal[0]["completed_at"]


async def test_timer_is_recorded_before_blocked_model_in_verified_peer(
    incoming_turn: tuple[MimicAgentRuntime, TranscriptStore, ControlledAgent, FakeActivity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, store, agent, activity = incoming_turn
    await runtime.start()
    timer = SimpleNamespace(
        id=uuid4(),
        peer="@original",
        description="reminder",
        trigger_at=datetime.now(UTC),
        status="pending",
    )
    session = AsyncMock()
    session.scalars.return_value = [timer]
    session.__aenter__.return_value = session
    runtime._session_factory = cast(Any, MagicMock(return_value=session))
    monkeypatch.setattr(runtime, "_ensure_peer_allowed", AsyncMock(return_value=12345))
    agent.release.clear()
    task = asyncio.create_task(runtime._check_and_trigger_timers())
    try:
        await asyncio.wait_for(agent.started.wait(), timeout=2)
        fired = [event for event in activity.events if event["event_type"] == "timer.fired"]
        assert len(fired) == 1
        assert fired[0]["payload"]["peer"] == "12345"
        assert store.rows[0]["peer"] == "12345"
        assert timer.status == "running"
        assert not any(event["event_type"] == "turn.completed" for event in activity.events)
        agent.release.set()
        await task
    finally:
        agent.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    outcomes = [
        event["event_type"]
        for event in activity.events
        if event["event_type"] in {"timer.fired", "turn.completed"}
    ]
    assert outcomes == ["timer.fired", "turn.completed"]
    assert timer.status == "succeeded"


async def test_timer_waiting_for_admission_does_not_fire_or_restart_after_stop(
    incoming_turn: tuple[MimicAgentRuntime, TranscriptStore, ControlledAgent, FakeActivity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, store, agent, activity = incoming_turn
    await runtime.start()
    timer = SimpleNamespace(
        id=uuid4(),
        peer="chat",
        description="reminder",
        trigger_at=datetime.now(UTC),
        status="pending",
    )
    session = AsyncMock()
    session.scalars.return_value = [timer]
    session.__aenter__.return_value = session
    runtime._session_factory = cast(Any, MagicMock(return_value=session))
    checked = asyncio.Event()

    async def check_peer(peer: str) -> None:
        checked.set()

    monkeypatch.setattr(runtime, "_ensure_peer_allowed", check_peer)
    await runtime._trigger_lock.acquire()
    task = asyncio.create_task(runtime._check_and_trigger_timers())
    try:
        await asyncio.wait_for(checked.wait(), timeout=2)
        await runtime.stop()
    finally:
        runtime._trigger_lock.release()
    await task
    assert runtime.state is AgentRuntimeState.STOPPED
    assert agent.inputs == []
    assert store.rows == []
    assert not any(event["event_type"] == "timer.fired" for event in activity.events)
