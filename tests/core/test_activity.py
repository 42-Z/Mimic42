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

from .test_agent_runtime import FakeLangChainAgent, FakeTelegramClient


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


def test_truncate_caps_large_values() -> None:
    big = {"items": "x" * 10_000}
    truncated = ActivityMiddleware.__mro__  # keep import meaningful
    assert truncated is not None

    from mimic42.core.activity import _truncate

    result = _truncate(big)
    assert result["_truncated"] is True
    assert len(result["preview"]) < 1000


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
