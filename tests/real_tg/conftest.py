"""Общее для обоих слоёв real_tg: один прогон живых тестов на все машины и CI."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from mimic42.testing.real_tg.lock import RealTelegramBusy, RealTelegramLock


@pytest.fixture(scope="session", autouse=True)
def real_telegram_lock() -> Iterator[None]:
    """Autouse-фикстура сессии поднимается раньше проверяющего и мимиков:
    занятый замок останавливает прогон до того, как тронута хоть одна сессия.
    Строку подключения к этому моменту уже загрузили conftest слоёв из .env."""
    lock = RealTelegramLock(os.environ["DATABASE_CONNECTION_STRING"])
    try:
        lock.acquire()
    except RealTelegramBusy as busy:
        pytest.exit(str(busy), returncode=pytest.ExitCode.INTERRUPTED)
    try:
        yield
    finally:
        lock.release()
