from __future__ import annotations

import os
from typing import Any

import pytest

from mimic42.api.app import create_app
from mimic42.config import Settings
from mimic42.integrations import tracing
from tests.api.fakes import FakeAgentManager


def test_api_tests_neutralize_braintrust_key_from_developer_env() -> None:
    """API-тесты герметичны: ключ Braintrust разработчика не доходит до Settings.

    Без этого create_app через lifespan звал бы настоящий setup_tracing: логин
    в Braintrust, процесс-глобальный LangChain-хендлер и atexit-flush прямо в
    pytest. Пустая строка (а не отсутствие переменной) важна: она перебивает
    слой .env в pydantic-settings, а валидатор трактует её как «не задано».
    """
    assert os.environ.get("BRAINTRUST_API_KEY") == ""
    assert Settings().braintrust_api_key is None


async def test_api_tests_do_not_enable_real_tracing() -> None:
    """Настоящий setup_tracing в API-тестах — no-op: без ключа Braintrust не трогается."""
    app = create_app(settings=Settings(database_connection_string=None))
    async with app.router.lifespan_context(app):
        pass

    assert tracing.tracing_enabled() is False


async def test_lifespan_sets_up_and_flushes_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, list[Any]] = {"setup": [], "flush": []}

    def fake_setup(settings: Settings) -> None:
        calls["setup"].append(settings)

    def fake_flush() -> None:
        calls["flush"].append(True)

    monkeypatch.setattr("mimic42.api.app.setup_tracing", fake_setup)
    monkeypatch.setattr("mimic42.api.app.flush_tracing", fake_flush)

    app = create_app(settings=Settings(database_connection_string=None))
    async with app.router.lifespan_context(app):
        assert len(calls["setup"]) == 1
        assert calls["flush"] == []

    assert calls["flush"] == [True]


async def test_lifespan_flushes_tracing_before_manager_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """flush идёт до shutdown: спаны добираются, пока агенты ещё останавливаются.

    Порядок фиксирован спекой: один flush_tracing() первой строкой finally, до
    manager.shutdown(). Спаны, завершающиеся уже в shutdown, добирает
    atexit-flush SDK при выходе процесса.
    """
    calls: dict[str, list[Any]] = {"setup": [], "flush": [], "shutdown": [], "order": []}

    def fake_setup(settings: Settings) -> None:
        calls["setup"].append(settings)
        calls["order"].append("setup")

    def fake_flush() -> None:
        calls["flush"].append(True)
        calls["order"].append("flush")

    monkeypatch.setattr("mimic42.api.app.setup_tracing", fake_setup)
    monkeypatch.setattr("mimic42.api.app.flush_tracing", fake_flush)

    class ShutdownRecordingManager(FakeAgentManager):
        async def shutdown(self) -> None:
            calls["shutdown"].append(True)
            calls["order"].append("shutdown")

    settings = Settings(database_connection_string=None)
    app = create_app(manager=ShutdownRecordingManager(), settings=settings)
    async with app.router.lifespan_context(app):
        assert calls["order"] == ["setup"]
        assert calls["flush"] == []
        assert calls["shutdown"] == []

    assert calls["order"] == ["setup", "flush", "shutdown"]
    assert calls["flush"] == [True]
    assert calls["shutdown"] == [True]
    assert calls["setup"][0] is settings
