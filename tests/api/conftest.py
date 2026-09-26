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
