"""Синхронная обёртка проверяющего: жизненный цикл её собственного event loop."""

from __future__ import annotations

from mimic42.testing.real_tg.checker import SyncChecker


def test_sync_checker_stop_closes_its_event_loop() -> None:
    """Луп и его self-pipe-сокеты не должны переживать stop(): незакрытые
    ресурсы всплывают ResourceWarning, а с -W error это ошибка прогона."""
    checker = SyncChecker(api_id=1, api_hash="hash", session_string="session")
    loop = checker._loop

    checker.stop()

    assert loop.is_closed()
