from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import braintrust
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
        self.calls: list[str] = []
        self.start_kwargs: dict[str, Any] = {}
        self.log_error: BaseException | None = None
        self.permalink_value = "https://braintrust.dev/app/p/mimic42/t/turn-1"

    def log(self, **event: Any) -> None:
        if self.log_error is not None:
            raise self.log_error
        self.events.append(event)

    def set_current(self) -> None:
        self.calls.append("set_current")

    def unset_current(self) -> None:
        self.calls.append("unset_current")

    def end(self) -> None:
        self.calls.append("end")
        self.ended += 1

    def permalink(self) -> str:
        return self.permalink_value


def _enable_tracing(monkeypatch: pytest.MonkeyPatch, **settings_kwargs: Any) -> list[FakeSpan]:
    _patch_braintrust(monkeypatch)
    spans: list[FakeSpan] = []

    def start_span(**kwargs: Any) -> FakeSpan:
        span = FakeSpan()
        span.start_kwargs = kwargs
        spans.append(span)
        return span

    monkeypatch.setattr(tracing.braintrust, "start_span", start_span)
    tracing.setup_tracing(_settings(braintrust_api_key="bt-key", **settings_kwargs))
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
    assert span.calls == ["set_current", "unset_current", "end"]
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
    assert spans[0].calls == ["set_current", "unset_current", "end"]


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


def test_turn_span_initial_log_failure_keeps_span_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    spans = _enable_tracing(monkeypatch)

    def start_span_with_broken_log(**kwargs: Any) -> FakeSpan:
        span = FakeSpan()
        span.start_kwargs = kwargs
        span.log_error = RuntimeError("log down")
        spans.append(span)
        return span

    monkeypatch.setattr(tracing.braintrust, "start_span", start_span_with_broken_log)

    with tracing.turn_span(
        agent_id=uuid4(), turn_id="t1", peer="chat", model="m", input=None
    ) as trace:
        trace.log(output={"text": "ok"})

    assert len(spans) == 1
    span = spans[0]
    # начальный log упал, но спан живой: хэндл рабочий, спан закрыт и снят с current
    assert trace.permalink() == span.permalink_value
    assert span.ended == 1
    assert span.calls == ["set_current", "unset_current", "end"]


def test_turn_span_records_base_exception_error(monkeypatch: pytest.MonkeyPatch) -> None:
    spans = _enable_tracing(monkeypatch)

    with pytest.raises(asyncio.CancelledError):
        with tracing.turn_span(
            agent_id=uuid4(), turn_id="t1", peer="chat", model="m", input=None
        ):
            raise asyncio.CancelledError()

    assert spans[0].events[-1] == {"error": "CancelledError"}
    assert spans[0].ended == 1
    assert spans[0].calls == ["set_current", "unset_current", "end"]


def test_turn_span_uses_environment_from_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    spans = _enable_tracing(monkeypatch, environment="production-test")

    with tracing.turn_span(
        agent_id=uuid4(), turn_id="t1", peer="chat", model="m", input=None
    ):
        pass

    assert spans[0].events[0]["metadata"]["environment"] == "production-test"


def test_turn_span_does_not_construct_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    spans = _enable_tracing(monkeypatch)

    class BoomSettings:
        def __init__(self, *_: Any, **__: Any) -> None:
            raise AssertionError("Settings must not be constructed during a turn")

    monkeypatch.setattr(tracing, "Settings", BoomSettings)

    with tracing.turn_span(
        agent_id=uuid4(), turn_id="t1", peer="chat", model="m", input=None
    ) as trace:
        trace.log(output={"text": "ok"})

    assert trace.permalink() == spans[0].permalink_value
    assert spans[0].ended == 1


def test_turn_span_is_current_span_for_real_braintrust_machinery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Интеграционная проверка на настоящей span-context машинерии SDK (без сети).

    SDK логинится офлайн по TEST_API_KEY, логи уходят на 127.0.0.1:1 (мгновенный
    отказ), atexit-flush выключен — ни логина, ни отправки логов в Braintrust.
    """
    monkeypatch.setenv("BRAINTRUST_API_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("BRAINTRUST_PROXY_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("BRAINTRUST_DISABLE_ATEXIT_FLUSH", "1")
    # Глушим только установку глобального LangChain-хендлера:
    # init_logger и start_span — настоящие.
    monkeypatch.setattr(tracing, "set_global_handler", lambda *_: None)
    monkeypatch.setattr(tracing, "BraintrustCallbackHandler", lambda: "handler")
    tracing.setup_tracing(_settings(braintrust_api_key=braintrust.TEST_API_KEY))
    assert tracing.tracing_enabled() is True

    with tracing.turn_span(
        agent_id=uuid4(), turn_id="t1", peer="chat", model="m", input={"text": "hi"}
    ) as trace:
        current: Any = braintrust.current_span()
        assert current is trace._span
        child: Any = braintrust.start_span(name="child")
        assert child.root_span_id == current.root_span_id
        assert child.span_id != current.span_id
        child.end()

    # после выхода из блока спан хода снят с current (остался NOOP-спан)
    assert braintrust.current_span() is not trace._span
    assert braintrust.current_span().export() == ""
