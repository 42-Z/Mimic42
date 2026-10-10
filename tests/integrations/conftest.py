from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def no_join_settle_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    """Осмотр группы после вступления ждёт бота-верификатора: в тестах пауза не нужна."""
    monkeypatch.setattr("mimic42.integrations.telegram_tools.JOIN_SETTLE_SECONDS", 0.0)
