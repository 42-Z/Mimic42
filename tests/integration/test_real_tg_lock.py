from __future__ import annotations

import asyncio
import random
import uuid

import asyncpg
import pytest

from mimic42.testing.real_tg.lock import APPLICATION_NAME, RealTelegramBusy, RealTelegramLock
from mimic42.testing.slots import plain_dsn


@pytest.fixture
def key() -> int:
    """Свой ключ на тест: настоящий замок в той же Dev-базе держат живые прогоны."""
    return random.randint(1, 2**31)


def test_second_run_is_refused_while_the_first_holds_the_lock(test_dsn: str, key: int) -> None:
    first = RealTelegramLock(test_dsn, holder="first", key=key)
    first.acquire()
    try:
        with pytest.raises(RealTelegramBusy, match="уже идут"):
            RealTelegramLock(test_dsn, holder="second", key=key).acquire()
    finally:
        first.release()


def test_released_lock_can_be_taken_again(test_dsn: str, key: int) -> None:
    first = RealTelegramLock(test_dsn, key=key)
    first.acquire()
    first.release()

    second = RealTelegramLock(test_dsn, key=key)
    second.acquire()
    second.release()


def test_lost_connection_frees_the_lock(test_dsn: str, key: int) -> None:
    """Убитый прогон не зовёт release: замок должен освободиться сам."""
    holder = f"crashed-{uuid.uuid4().hex[:8]}"
    crashed = RealTelegramLock(test_dsn, holder=holder, key=key)
    crashed.acquire()

    async def kill() -> None:
        connection = await asyncpg.connect(plain_dsn(test_dsn))
        try:
            # Ненулевой таймаут: функция ждёт, пока процесс действительно завершится.
            terminated = await connection.fetchval(
                "select pg_terminate_backend(pid, 5000) from pg_stat_activity "
                "where application_name = $1",
                f"{APPLICATION_NAME}:{holder}",
            )
            assert terminated is True
        finally:
            await connection.close()

    asyncio.run(kill())
    try:
        survivor = RealTelegramLock(test_dsn, key=key)
        survivor.acquire()
        survivor.release()
    finally:
        # Соединение уже разорвано: release просто подчищает поток.
        crashed.release()


def test_transaction_pooler_is_rejected() -> None:
    with pytest.raises(ValueError, match="6543"):
        RealTelegramLock("postgresql://user:pass@example.pooler.supabase.com:6543/postgres")
