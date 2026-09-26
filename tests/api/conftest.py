"""Общая обвязка API-тестов."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def no_real_media_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """API-тесты не ходят в настоящее хранилище Supabase.

    create_app без явных настроек читает `.env` разработчика с service-ключом
    Dev и собирает настоящее хранилище: удаление агента тогда чистило бы его
    папку в Dev и оставляло открытый сокет. Переменная окружения важнее `.env`,
    так что пустой ключ выключает хранилище; нужное тесту передаётся через
    media_uploader.
    """
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")


@pytest.fixture(autouse=True)
def no_real_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    """API-тесты не инициализируют настоящий Braintrust.

    create_app без явных настроек читает `.env` разработчика, где может лежать
    BRAINTRUST_API_KEY, а lifespan зовёт настоящий setup_tracing: с ключом он
    логинится в Braintrust, ставит процесс-глобальный LangChain-хендлер и
    регистрирует atexit-flush. Переменная окружения важнее `.env`, так что
    пустой ключ (валидатор Settings трактует его как «не задано») выключает
    трейсинг; тестам он не нужен — они мокают setup_tracing.
    """
    monkeypatch.setenv("BRAINTRUST_API_KEY", "")
