from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import ToolMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mimic42.core.activity import ActivityRecorder
from mimic42.core.agent_runtime import AgentRuntimeConfig, AgentRuntimeState, MimicAgentRuntime
from mimic42.core.manager import AgentManager
from mimic42.integrations.activity_middleware import ActivityMiddleware
from mimic42.integrations.database_models import AgentEventModel, Base

from .test_agent_runtime import FakeIncomingEvent, FakeLangChainAgent, FakeTelegramClient


def make_config(agent_id: UUID | None = None) -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=agent_id or uuid4(),
        owner_id=uuid4(),
        telegram_session_name="test-session",
        telegram_api_id=12345,
        telegram_api_hash="hash",
        telegram_session_string="session",
        system_prompt="system",
        soul_prompt="soul",
    )


def make_session_factory() -> async_sessionmaker[Any]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_tables(session_factory: async_sessionmaker[Any]) -> None:
    engine = session_factory.kw["bind"]
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@pytest.mark.asyncio
async def test_activity_recorder_writes_event_row() -> None:
    session_factory = make_session_factory()
    await create_tables(session_factory)

    agent_id = uuid4()
    recorder = ActivityRecorder(session_factory)
    await recorder.record(
        agent_id=agent_id,
        event_type="tool.send_text_message",
        status="succeeded",
        payload={"turn_id": "turn-1", "peer": "123", "args": {"peer": "123"}},
        result={"success": True, "message_id": 5},
        started_at=None,
        completed_at=None,
    )

    async with session_factory() as session:
        rows = list(await session.scalars(select(AgentEventModel)))
    assert len(rows) == 1
    row = rows[0]
    assert row.agent_id == agent_id
    assert row.event_type == "tool.send_text_message"
    assert row.status == "succeeded"
    assert row.payload["turn_id"] == "turn-1"
    assert row.result == {"success": True, "message_id": 5}


@pytest.mark.asyncio
async def test_activity_recorder_swallows_write_failure() -> None:
    class BrokenFactory:
        def __call__(self) -> Any:
            raise RuntimeError("db down")

    recorder = ActivityRecorder(BrokenFactory())  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    await recorder.record(
        agent_id=uuid4(),
        event_type="tool.get_dialogs",
        status="succeeded",
    )


def test_truncate_keeps_small_keys_and_caps_large_values() -> None:
    from mimic42.core.activity import _truncate

    # Oversized dict: small correlation keys survive, the huge value is
    # collapsed to a marker.
    big = {
        "turn_id": "t-1",
        "peer": "123",
        "error_code": "FloodWaitError",
        "items": "x" * 10_000,
    }
    result = _truncate(big)
    assert result["_truncated"] is True
    assert result["turn_id"] == "t-1"
    assert result["peer"] == "123"
    assert result["error_code"] == "FloodWaitError"
    assert result["items"] == {"_truncated": True}

    # Oversized non-dict: collapses to a short preview.
    list_result = _truncate(["y" * 10_000])
    assert list_result["_truncated"] is True
    assert len(list_result["preview"]) < 1000


class _RecordingRecorder:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def record(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


def _make_middleware() -> tuple[ActivityMiddleware, _RecordingRecorder]:
    recorder = _RecordingRecorder()
    middleware = ActivityMiddleware(agent_id=uuid4(), recorder=recorder)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    return middleware, recorder


@pytest.mark.asyncio
async def test_middleware_classifies_failed_tool_output() -> None:
    middleware, recorder = _make_middleware()

    async def handler(request: Any) -> ToolMessage:
        return ToolMessage(
            content=json.dumps(
                {
                    "success": False,
                    "error": "No admin rights",
                    "error_code": "ChatAdminRequiredError",
                }
            ),
            tool_call_id="call-1",
        )

    request = _fake_request()
    await middleware.awrap_tool_call(request, handler)

    event = recorder.events[0]
    assert event["event_type"] == "tool.pin_message"
    assert event["status"] == "failed"
    assert event["error"] == "No admin rights"
    assert event["result"]["error_code"] == "ChatAdminRequiredError"
    assert event["payload"]["args"] == {"message_id": 1}


@pytest.mark.asyncio
async def test_middleware_classifies_successful_tool_output() -> None:
    middleware, recorder = _make_middleware()

    async def handler(request: Any) -> ToolMessage:
        return ToolMessage(
            content=json.dumps({"success": True, "message_id": 42}),
            tool_call_id="call-1",
        )

    await middleware.awrap_tool_call(_fake_request(), handler)

    event = recorder.events[0]
    assert event["status"] == "succeeded"
    assert event["error"] is None
    assert event["result"] == {"success": True, "message_id": 42}


@pytest.mark.asyncio
async def test_middleware_classifies_failed_list_tool_output() -> None:
    """List-shaped tools report failures as [{"success": false, ...}]."""
    middleware, recorder = _make_middleware()

    async def handler(request: Any) -> ToolMessage:
        return ToolMessage(
            content=json.dumps(
                [{"success": False, "error": "Peer invalid", "error_code": "PeerIdInvalidError"}]
            ),
            tool_call_id="call-1",
        )

    await middleware.awrap_tool_call(_fake_request(), handler)

    event = recorder.events[0]
    assert event["status"] == "failed"
    assert event["error"] == "Peer invalid"
    assert event["result"]["items"][0]["error_code"] == "PeerIdInvalidError"


@pytest.mark.asyncio
async def test_middleware_records_model_failure_and_success_is_silent() -> None:
    middleware, recorder = _make_middleware()

    async def failing_handler(request: Any) -> Any:
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        await middleware.awrap_model_call(object(), failing_handler)

    event = recorder.events[0]
    assert event["event_type"] == "model.failed"
    assert event["status"] == "failed"
    assert event["payload"]["error_code"] == "RuntimeError"

    async def ok_handler(request: Any) -> Any:
        return "ok"

    await middleware.awrap_model_call(object(), ok_handler)
    assert len(recorder.events) == 1


def _fake_request() -> Any:
    class FakeRuntime:
        context = None

    class FakeRequest:
        tool_call = {"name": "pin_message", "args": {"message_id": 1}, "id": "call-1"}
        runtime = FakeRuntime()

    return FakeRequest()


@pytest.mark.asyncio
async def test_runtime_start_records_lifecycle_event() -> None:
    session_factory = make_session_factory()
    await create_tables(session_factory)

    agent_id = uuid4()
    runtime = MimicAgentRuntime(
        config=make_config(agent_id),
        telegram_client=FakeTelegramClient(),
        langchain_agent=FakeLangChainAgent(),
        session_factory=session_factory,
    )
    await runtime.start()
    await runtime.stop()

    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(AgentEventModel).where(AgentEventModel.agent_id == agent_id)
            )
        )
    types = {row.event_type for row in rows}
    assert "agent.started" in types
    assert "agent.stopped" in types


@pytest.mark.asyncio
async def test_manager_start_agent_persists_error_status() -> None:
    class FailingStartClient(FakeTelegramClient):
        async def connect(self) -> None:
            raise RuntimeError("boom")

    updates: list[tuple[UUID, AgentRuntimeState]] = []

    async def save_status(agent_id: UUID, state: AgentRuntimeState) -> None:
        updates.append((agent_id, state))

    config = make_config()
    manager = AgentManager(
        runtime_factory=lambda runtime_config: MimicAgentRuntime(
            config=runtime_config,
            telegram_client=FailingStartClient(),
            langchain_agent=FakeLangChainAgent(),
        ),
        status_sink=save_status,
    )
    await manager.create_agent(config)

    with pytest.raises(RuntimeError):
        await manager.start_agent(config.agent_id)

    assert updates == [(config.agent_id, AgentRuntimeState.ERROR)]


@pytest.mark.asyncio
async def test_failed_turn_records_turn_failed_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crashing LLM call must yield exactly one turn.failed event.

    trigger_message records the event with the turn_id and re-raises;
    the handler-level catch-all must not add a duplicate row.
    """
    from unittest.mock import MagicMock

    from telethon.tl import functions

    session_factory = make_session_factory()
    await create_tables(session_factory)

    agent_id = uuid4()
    telegram = FakeTelegramClient()

    async def mock_get_input_entity(peer: Any) -> Any:
        return MagicMock()

    async def mock_call(self: Any, request: Any) -> Any:
        if isinstance(request, functions.account.GetNotifySettingsRequest):
            res = MagicMock()
            res.silent = False
            res.mute_until = None
            return res
        return True

    telegram.get_input_entity = mock_get_input_entity  # type: ignore
    monkeypatch.setattr(FakeTelegramClient, "__call__", mock_call, raising=False)

    class BrokenAgent:
        async def ainvoke(
            self,
            input_data: dict[str, object],
            context: object | None = None,
        ) -> object:
            raise RuntimeError("LLM down")

    runtime = MimicAgentRuntime(
        config=make_config(agent_id),
        telegram_client=telegram,
        langchain_agent=BrokenAgent(),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        session_factory=session_factory,
    )
    await runtime.start()

    async def mock_peer(ev: Any) -> str:
        return "6121153070"

    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_peer", mock_peer)
    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_message_id", lambda ev: 708)

    event = FakeIncomingEvent(chat_id=6121153070, message_id=708, text="ты любишь 42?")
    await telegram.emit_message(event)  # must not raise

    await runtime.stop()

    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(AgentEventModel).where(
                    AgentEventModel.agent_id == agent_id,
                    AgentEventModel.event_type == "turn.failed",
                )
            )
        )
    assert len(rows) == 1
    assert rows[0].payload.get("turn_id")
