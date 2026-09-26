from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest

from mimic42.config import Settings
from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentTrigger,
    MimicAgentRuntime,
)
from mimic42.integrations import tracing
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramClient

TRACE_URL = "https://braintrust.dev/app/p/mimic42/t/turn-1"


class FakeSpan:
    """Фейк спана Braintrust: принимает события и помнит порядок вызовов.

    ``calls`` фиксирует границу спана: ``log`` после ``end`` (регрессия,
    при которой output пишется вне блока ``turn_span``) видна по порядку
    вызовов. ``permalink_value=None`` изображает спан без permalink.
    """

    def __init__(self, permalink_value: str | None = TRACE_URL) -> None:
        self.permalink_value = permalink_value
        self.events: list[dict[str, Any]] = []
        self.calls: list[str] = []
        self.ended = 0

    def log(self, **event: Any) -> None:
        self.calls.append("log")
        self.events.append(event)

    def set_current(self) -> None:
        return None

    def unset_current(self) -> None:
        return None

    def end(self) -> None:
        self.calls.append("end")
        self.ended += 1

    def permalink(self) -> str | None:
        return self.permalink_value


class FakeLangChainAgent:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def aclose(self) -> None:
        return None

    async def ainvoke(
        self,
        input_data: dict[str, object],
        context: object | None = None,
    ) -> dict[str, object]:
        if self.fail:
            raise RuntimeError("model exploded")
        return {
            "messages": [{"role": "assistant", "content": "reply"}],
            "structured_response": {
                "text": "reply",
                "send_any_message": True,
                "reply_to": None,
            },
        }


class FakeMemoryService:
    async def build_messages(
        self, *, agent_id: UUID, peer: str, user_text: str
    ) -> list[dict[str, Any]]:
        return [{"role": "user", "content": user_text}]

    async def save_messages(self, **_: Any) -> None:
        return None


class FakeActivity:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def record(self, **event: Any) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def _clean_tracing_state() -> Iterator[None]:
    tracing.reset_tracing()
    yield
    tracing.reset_tracing()


def make_config() -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_session_string="sessions/test-agent",
        telegram_api_id=12345,
        telegram_api_hash="hash",
        llm_model="openrouter/free",
        system_prompt="Base system prompt",
        soul_prompt="Quiet direct style",
    )


async def _run_turn(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail: bool = False,
    tracing_on: bool = True,
    spans: list[FakeSpan] | None = None,
    permalink_value: str | None = TRACE_URL,
    telegram_client: FakeTelegramClient | None = None,
) -> FakeActivity:
    if tracing_on:
        monkeypatch.setattr(tracing.braintrust, "init_logger", lambda **_: object())
        monkeypatch.setattr(tracing, "set_global_handler", lambda _handler: None)
        monkeypatch.setattr(tracing, "BraintrustCallbackHandler", lambda: "handler")

        def make_span(**_: Any) -> FakeSpan:
            span = FakeSpan(permalink_value)
            if spans is not None:
                spans.append(span)
            return span

        monkeypatch.setattr(tracing.braintrust, "start_span", make_span)
        tracing.setup_tracing(
            Settings(
                _env_file=None,  # ty: ignore[unknown-argument]
                braintrust_api_key="bt-key",
            )
        )
    if telegram_client is None:
        account = FakeTelegramAccount()
        account.authorized = True  # ход должен пройти: сессия уже прошла онбординг
        telegram_client = FakeTelegramClient(account)
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram_client,
        langchain_agent=FakeLangChainAgent(fail=fail),
        memory_service=FakeMemoryService(),  # type: ignore[arg-type]
    )
    activity = FakeActivity()
    # Тестовый шов вместо БД: события пишутся в список, а поле типизировано
    # как ActivityRecorder — отсюда invalid-assignment у заглушки.
    runtime._activity = activity  # ty: ignore[invalid-assignment]
    await runtime.start()
    if fail:
        with pytest.raises(RuntimeError, match="model exploded"):
            await runtime.trigger_message(AgentTrigger(peer="chat", text="hi"))
    else:
        await runtime.trigger_message(AgentTrigger(peer="chat", text="hi"))
    return activity


async def test_turn_completed_event_carries_trace_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activity = await _run_turn(monkeypatch)

    completed = [e for e in activity.events if e["event_type"] == "turn.completed"]
    assert len(completed) == 1
    payload = completed[0]["payload"]
    assert payload["peer"] == "chat"
    assert payload["trace_url"] == TRACE_URL
    assert isinstance(payload["turn_id"], str) and payload["turn_id"]
    assert completed[0]["status"] == "succeeded"


async def test_turn_failed_event_carries_trace_url(monkeypatch: pytest.MonkeyPatch) -> None:
    activity = await _run_turn(monkeypatch, fail=True)

    failed = [e for e in activity.events if e["event_type"] == "turn.failed"]
    assert len(failed) == 1
    assert failed[0]["payload"]["trace_url"] == TRACE_URL
    assert failed[0]["payload"]["error_code"] == "RuntimeError"
    assert not [e for e in activity.events if e["event_type"] == "turn.completed"]


async def test_events_have_no_trace_url_without_tracing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activity = await _run_turn(monkeypatch, tracing_on=False)

    turn_events = [
        e for e in activity.events if e["event_type"] in {"turn.completed", "turn.failed"}
    ]
    assert turn_events, "ход должен записать событие уровня turn"
    for event in turn_events:
        assert "trace_url" not in event["payload"]


class FailingSendClient(FakeTelegramClient):
    """Клиент, у которого доставка сообщения падает."""

    async def send_message(self, entity: str | int, message: str, **kwargs: Any) -> object:
        raise RuntimeError("send exploded")


async def test_turn_span_output_reports_failed_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сбой доставки: спан не должен врать про отправку (issue #92, ревью)."""
    spans: list[FakeSpan] = []
    activity = await _run_turn(monkeypatch, spans=spans, telegram_client=FailingSendClient())

    assert len(spans) == 1
    # Мы на отлаживаемом пути: доставка упала и видна в ленте событий.
    assert any(e["event_type"] == "message.send_failed" for e in activity.events)
    output_events = [e for e in spans[0].events if "output" in e]
    assert output_events == [{"output": {"text": "reply", "sent": False}}]


async def test_turn_span_lifecycle_logs_output_before_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Граница спана: input+metadata первыми, output до end(), end ровно раз."""
    spans: list[FakeSpan] = []
    activity = await _run_turn(monkeypatch, spans=spans)

    assert len(spans) == 1
    span = spans[0]
    assert set(span.events[0]) == {"input", "metadata"}
    metadata = span.events[0]["metadata"]
    assert metadata["peer"] == "chat"
    assert metadata["model"] == "openrouter/free"
    completed = [e for e in activity.events if e["event_type"] == "turn.completed"]
    assert metadata["turn_id"] == completed[0]["payload"]["turn_id"]
    assert span.events[1] == {"output": {"text": "reply", "sent": True}}
    # Регрессия «output вне with» дала бы ["log", "end", "log"].
    assert span.calls == ["log", "log", "end"]
    assert span.ended == 1


async def test_turn_completed_omits_trace_url_without_permalink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spans: list[FakeSpan] = []
    activity = await _run_turn(monkeypatch, spans=spans, permalink_value=None)

    assert len(spans) == 1
    completed = [e for e in activity.events if e["event_type"] == "turn.completed"]
    assert len(completed) == 1
    assert "trace_url" not in completed[0]["payload"]


async def test_turn_failed_omits_trace_url_without_permalink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spans: list[FakeSpan] = []
    activity = await _run_turn(monkeypatch, spans=spans, fail=True, permalink_value=None)

    assert len(spans) == 1
    failed = [e for e in activity.events if e["event_type"] == "turn.failed"]
    assert len(failed) == 1
    assert "trace_url" not in failed[0]["payload"]
