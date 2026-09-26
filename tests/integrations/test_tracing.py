from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest

from mimic42.config import Settings
from mimic42.integrations import tracing


@pytest.fixture(autouse=True)
def _clean_tracing_state() -> Iterator[None]:
    tracing.reset_tracing()
    yield
    tracing.reset_tracing()


class FakeBraintrust:
    def __init__(self) -> None:
        self.init_calls: list[dict[str, Any]] = []
        self.flush_calls = 0
        self.handlers: list[Any] = []

    def init_logger(self, **kwargs: Any) -> Any:
        self.init_calls.append(kwargs)
        return object()

    def flush(self) -> None:
        self.flush_calls += 1


def _patch_braintrust(monkeypatch: pytest.MonkeyPatch) -> FakeBraintrust:
    fake = FakeBraintrust()
    monkeypatch.setattr(tracing.braintrust, "init_logger", fake.init_logger)
    monkeypatch.setattr(tracing.braintrust, "flush", fake.flush)
    monkeypatch.setattr(tracing, "set_global_handler", fake.handlers.append)
    monkeypatch.setattr(tracing, "BraintrustCallbackHandler", lambda: "handler")
    return fake


def _settings(**kwargs: Any) -> Settings:
    return Settings(_env_file=None, **kwargs)  # ty: ignore[unknown-argument]


def test_setup_tracing_without_key_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_braintrust(monkeypatch)

    tracing.setup_tracing(_settings(braintrust_api_key=None))

    assert fake.init_calls == []
    assert fake.handlers == []
    assert tracing.tracing_enabled() is False


def test_setup_tracing_initializes_braintrust(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_braintrust(monkeypatch)

    tracing.setup_tracing(_settings(braintrust_api_key="bt-key", braintrust_project="Mimic42 Dev"))

    assert fake.init_calls == [{"project": "Mimic42 Dev", "api_key": "bt-key"}]
    assert fake.handlers == ["handler"]
    assert tracing.tracing_enabled() is True


def test_setup_tracing_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_braintrust(monkeypatch)
    settings = _settings(braintrust_api_key="bt-key")

    tracing.setup_tracing(settings)
    tracing.setup_tracing(settings)

    assert len(fake.init_calls) == 1
    assert fake.handlers == ["handler"]


def test_setup_tracing_init_failure_disables_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_braintrust(monkeypatch)

    def boom(**_: Any) -> Any:
        raise RuntimeError("bad key")

    monkeypatch.setattr(tracing.braintrust, "init_logger", boom)

    tracing.setup_tracing(_settings(braintrust_api_key="bt-key"))

    assert tracing.tracing_enabled() is False


def test_setup_tracing_handler_failure_keeps_tracing_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _patch_braintrust(monkeypatch)

    def boom(_: Any) -> None:
        raise RuntimeError("no langchain")

    monkeypatch.setattr(tracing, "set_global_handler", boom)

    tracing.setup_tracing(_settings(braintrust_api_key="bt-key"))

    assert len(fake.init_calls) == 1
    assert tracing.tracing_enabled() is True


def test_flush_tracing_swallows_flush_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_braintrust(monkeypatch)

    def boom() -> None:
        raise RuntimeError("sdk down")

    monkeypatch.setattr(tracing.braintrust, "flush", boom)

    tracing.setup_tracing(_settings(braintrust_api_key="bt-key"))
    tracing.flush_tracing()

    assert tracing.tracing_enabled() is True


def test_flush_tracing_only_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_braintrust(monkeypatch)

    tracing.flush_tracing()
    assert fake.flush_calls == 0

    tracing.setup_tracing(_settings(braintrust_api_key="bt-key"))
    tracing.flush_tracing()
    assert fake.flush_calls == 1


class FakeSpan:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.ended = 0
        self.start_kwargs: dict[str, Any] = {}
        self.permalink_value = "https://braintrust.dev/app/p/mimic42/t/turn-1"

    def log(self, **event: Any) -> None:
        self.events.append(event)

    def end(self) -> None:
        self.ended += 1

    def permalink(self) -> str:
        return self.permalink_value


def _enable_tracing(monkeypatch: pytest.MonkeyPatch) -> list[FakeSpan]:
    _patch_braintrust(monkeypatch)
    spans: list[FakeSpan] = []

    def start_span(**kwargs: Any) -> FakeSpan:
        span = FakeSpan()
        span.start_kwargs = kwargs
        spans.append(span)
        return span

    monkeypatch.setattr(tracing.braintrust, "start_span", start_span)
    tracing.setup_tracing(_settings(braintrust_api_key="bt-key"))
    return spans


def test_turn_span_is_noop_without_tracing() -> None:
    with tracing.turn_span(
        agent_id=uuid4(), turn_id="t1", peer="chat", model="openrouter/free", input={"text": "hi"}
    ) as trace:
        trace.log(output={"text": "ok"})

    assert trace.permalink() is None


def test_turn_span_logs_input_metadata_and_output(monkeypatch: pytest.MonkeyPatch) -> None:
    spans = _enable_tracing(monkeypatch)
    agent_id = uuid4()

    with tracing.turn_span(
        agent_id=agent_id,
        turn_id="t1",
        peer="chat",
        model="openrouter/free",
        input={"text": "hi"},
    ) as trace:
        trace.log(output={"text": "ok"})

    assert len(spans) == 1
    span = spans[0]
    assert span.start_kwargs["name"] == "turn chat"
    assert span.start_kwargs["type"] == "task"
    assert span.events[0]["input"] == {"text": "hi"}
    metadata = span.events[0]["metadata"]
    assert metadata["agent_id"] == str(agent_id)
    assert metadata["turn_id"] == "t1"
    assert metadata["peer"] == "chat"
    assert metadata["model"] == "openrouter/free"
    assert isinstance(metadata["environment"], str) and metadata["environment"]
    assert span.events[1] == {"output": {"text": "ok"}}
    assert span.ended == 1
    assert trace.permalink() == span.permalink_value


def test_turn_span_records_error_and_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
    spans = _enable_tracing(monkeypatch)

    with pytest.raises(RuntimeError, match="boom"):
        with tracing.turn_span(
            agent_id=uuid4(), turn_id="t1", peer="chat", model="m", input=None
        ):
            raise RuntimeError("boom")

    assert spans[0].events[-1] == {"error": "boom"}
    assert spans[0].ended == 1


def test_turn_span_survives_start_span_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_tracing(monkeypatch)

    def boom(**_: Any) -> Any:
        raise RuntimeError("sdk down")

    monkeypatch.setattr(tracing.braintrust, "start_span", boom)

    with tracing.turn_span(
        agent_id=uuid4(), turn_id="t1", peer="chat", model="m", input=None
    ) as trace:
        trace.log(output={"text": "ok"})

    assert trace.permalink() is None
