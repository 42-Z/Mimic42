from __future__ import annotations

from collections.abc import Iterator
from typing import Any

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


def test_flush_tracing_only_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_braintrust(monkeypatch)

    tracing.flush_tracing()
    assert fake.flush_calls == 0

    tracing.setup_tracing(_settings(braintrust_api_key="bt-key"))
    tracing.flush_tracing()
    assert fake.flush_calls == 1
