from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest

from mimic42.core.agent_runtime import AgentTrigger, MimicAgentRuntime
from mimic42.core.memory import RuntimeMemoryService
from mimic42.testing.telegram import FakeTelegramClient
from tests.core.test_agent_runtime import make_config
from tests.core.test_agent_runtime_tracing import FakeActivity


class TranscriptStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.context_started = asyncio.Event()
        self.release_context = asyncio.Event()
        self.release_context.set()
        self.context_error: RuntimeError | None = None

    async def load_recent_messages(
        self, *, agent_id: UUID, peer: str, since: datetime
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
            if row["agent_id"] == agent_id and row["peer"] == peer and row["created_at"] >= since
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
        raw_user_text: str = "",
        turn_id: str | None = None,
        thread_id: UUID | None = None,
        media: list[dict[str, Any]] | None = None,
        reply: dict[str, Any] | None = None,
    ) -> None:
        user_written = False
        batch = messages
        if raw_user_text:
            batch = [{"role": "user", "content": raw_user_text}, *messages]
        for message in batch:
            role = message.get("role", message.get("type"))
            if role in {"human", "user"}:
                if user_written:
                    continue
                role = "user"
                user_written = True
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
                    "media": media,
                    "reply": reply,
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
