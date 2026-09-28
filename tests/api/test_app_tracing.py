from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest

from mimic42.api.app import create_app
from mimic42.config import Settings
from mimic42.integrations import tracing
from tests.api.fakes import FakeAgentManager


def test_api_tests_neutralize_braintrust_key_from_developer_env(tmp_path: Path) -> None:
    """API-тесты герметичны: ключ Braintrust из .env разработчика не доходит до Settings.

    Без этого create_app через lifespan звал бы настоящий setup_tracing: логин
    в Braintrust, процесс-глобальный LangChain-хендлер и atexit-flush прямо в
    pytest. Утечка моделируется настоящим dotenv-файлом, а не пустым окружением:
    пустая строка в env (действие фикстуры no_real_tracing) перебивает слой .env
    в pydantic-settings, а валидатор трактует её как «не задано».
    """
    env_file = tmp_path / ".env"
    env_file.write_text("BRAINTRUST_API_KEY=leak\n")

    # Фикстура no_real_tracing выставляет пустой ключ поверх .env: без неё
    # dotenv-утечка ниже проходила бы в Settings.
    assert os.environ.get("BRAINTRUST_API_KEY") == ""

    settings = Settings(_env_file=env_file)  # ty: ignore[unknown-argument]
    assert settings.braintrust_api_key is None


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

    async def fake_flush() -> None:
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

    async def fake_flush() -> None:
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


async def test_lifespan_shutdown_survives_flush_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Отмена на await flush не отменяет shutdown агентов и cleanup.

    flush — первая точка отмены в finally: при остановке приложения снаружи
    (CancelledError приходит именно на этот await) агенты обязаны остановиться
    иначе рантаймы останутся висеть в памяти процесса.
    """
    calls: dict[str, list[Any]] = {"flush": [], "shutdown": []}

    async def cancelled_flush() -> None:
        calls["flush"].append(True)
        raise asyncio.CancelledError

    monkeypatch.setattr("mimic42.api.app.setup_tracing", lambda _settings: None)
    monkeypatch.setattr("mimic42.api.app.flush_tracing", cancelled_flush)

    class ShutdownRecordingManager(FakeAgentManager):
        async def shutdown(self) -> None:
            calls["shutdown"].append(True)

    app = create_app(
        manager=ShutdownRecordingManager(),
        settings=Settings(database_connection_string=None),
    )
    with pytest.raises(asyncio.CancelledError):
        async with app.router.lifespan_context(app):
            pass

    assert calls["flush"] == [True]
    assert calls["shutdown"] == [True], "cancelled flush must not skip agent shutdown"
