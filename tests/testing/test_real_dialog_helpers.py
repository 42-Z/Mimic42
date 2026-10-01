"""JWT в живом синхронном тесте запрашивается вне pytest event loop."""

from __future__ import annotations

import pytest

from tests.real_tg.frontend import helpers


async def test_fetch_token_with_running_pytest_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_jwt() -> str:
        return "test-token"

    monkeypatch.setattr(helpers, "jwt", fake_jwt)
    assert helpers.fetch_token() == "test-token"
