from __future__ import annotations

from typing import Any

import pytest

from mimic42.api.app import create_app
from mimic42.config import Settings


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
