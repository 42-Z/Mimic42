"""Настройки тестового контура герметичны: внешние сервисы выключены явно.

create_app в lifespan зовёт build_mem0_memory и setup_tracing: с боевыми ключами
из .env разработчика тесты ходили бы по настоящим внешним сервисам — Mem0, а для
Braintrust ещё логинились бы, ставили процесс-глобальный LangChain-хендлер и
atexit-flush прямо в pytest. Поэтому тестовый контур обязан обнулять ключи сам:
`_test_settings()` — это настройки `build_test_app()` (tests/e2e, tests/integration),
`real_app_settings()` — настоящий app слоя real_tg, а `build_test_app()` дополнительно
нормализует настройки, пришедшие мимо сборщика.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI

from mimic42.config import Settings
from mimic42.testing.server import _test_settings, build_test_app
from tests.real_tg.backend.helpers import real_app_settings


def _leaky_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Минимальное окружение сборщиков плюс утечка боевых ключей из .env."""
    monkeypatch.setenv("DATABASE_CONNECTION_STRING", "postgresql://test@localhost/test")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "test-api-hash")
    monkeypatch.setenv("MEM0_API_KEY", "leak-mem0")
    monkeypatch.setenv("BRAINTRUST_API_KEY", "leak-braintrust")


@pytest.mark.parametrize(
    ("build", "label"),
    [(_test_settings, "build_test_app"), (real_app_settings, "real_tg")],
)
def test_test_contour_settings_carry_no_external_service_keys(
    build: Callable[[], Settings], label: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _leaky_env(monkeypatch)

    settings = build()

    assert settings.mem0_api_key is None, f"{label}: Mem0 подхватил боевой ключ"
    assert settings.braintrust_api_key is None, f"{label}: Braintrust подхватил боевой ключ"


def test_build_test_app_strips_external_keys_from_any_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Настройки, пришедшие мимо сборщика, тоже герметичны: build_test_app обнуляет ключи.

    Тесты передают свои настройки (например
    ``build_test_app(settings=Settings(restore_running_agents=False))``), и они
    подхватывают боевые ключи из .env разработчика. Без обнуления на входе такой
    тест звал бы настоящий setup_tracing прямо в своём lifespan.
    """
    captured: list[Settings | None] = []
    monkeypatch.setattr("mimic42.testing.server.assert_test_project", lambda *args: None)

    def spy_create_app(*, settings: Settings | None = None, **_: Any) -> FastAPI:
        captured.append(settings)
        return FastAPI()

    monkeypatch.setattr("mimic42.testing.server.create_app", spy_create_app)
    leaky = Settings(mem0_api_key="leak-mem0", braintrust_api_key="leak-braintrust")

    build_test_app(settings=leaky)

    assert captured[0] is not None
    assert captured[0].mem0_api_key is None
    assert captured[0].braintrust_api_key is None
