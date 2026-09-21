"""Замок живых Telegram-тестов: один прогон на все машины и CI сразу.

Сессии проверяющего и мимиков общие. Если два прогона подключат одну сессию
Telethon с разных машин, Telegram может отозвать её — так потерялся первый
проверяющий. Замок — advisory lock Postgres в той же базе, куда ходят живые
тесты: таблиц и миграций не нужно, и Postgres снимает его сам, как только
соединение закрылось (упавший или убитый прогон не оставляет висящий флаг).

Advisory lock живёт на соединении, поэтому пулер Supabase нужен в session
mode (порт 5432); transaction mode (6543) его не поддерживает.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Coroutine
from typing import Any
from urllib.parse import urlsplit

import asyncpg

from mimic42.testing.slots import CONNECT_TIMEOUT_SECONDS, plain_dsn

# Произвольный, но постоянный ключ: по нему все прогоны узнают один и тот же замок.
LOCK_KEY = 4_242_072_001
APPLICATION_NAME = "mimic42-real-tg"
TRANSACTION_POOLER_PORT = 6543


class RealTelegramBusy(RuntimeError):
    """Живые тесты уже идут в другом процессе."""


class RealTelegramLock:
    """Держит замок на отдельном соединении до release().

    Синхронный снаружи: фронт-слой гоняет pytest-playwright, которому нельзя
    подсовывать свой луп, поэтому соединение живёт в собственном потоке."""

    def __init__(self, dsn: str, *, holder: str | None = None, key: int = LOCK_KEY) -> None:
        """key меняют только тесты самого замка, чтобы не мешать живым прогонам."""
        dsn = plain_dsn(dsn)
        if urlsplit(dsn).port == TRANSACTION_POOLER_PORT:
            raise ValueError(
                "Замок живых тестов не работает через transaction pooler (порт 6543): "
                "нужен session mode (5432) или прямое подключение"
            )
        self._dsn = dsn
        self._holder = holder or socket.gethostname()
        self._key = key
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._connection: asyncpg.Connection | None = None

    def acquire(self) -> None:
        """Взять замок или сразу упасть с RealTelegramBusy, не дожидаясь."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="real-tg-lock", daemon=True
        )
        self._thread.start()
        try:
            self._run(self._acquire())
        except BaseException:
            self._stop_loop()
            raise

    def release(self) -> None:
        if self._loop is None:
            return
        try:
            self._run(self._release())
        finally:
            self._stop_loop()

    def _run(self, coroutine: Coroutine[Any, Any, None]) -> None:
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        future.result(timeout=CONNECT_TIMEOUT_SECONDS * 2)

    def _stop_loop(self) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._loop.close()
        self._loop = None
        self._thread = None

    async def _acquire(self) -> None:
        connection = await asyncpg.connect(self._dsn, timeout=CONNECT_TIMEOUT_SECONDS)
        try:
            # Пулер подменяет application_name из параметров подключения своим,
            # поэтому имя держателя ставится уже внутри сессии.
            await connection.execute(
                "select set_config('application_name', $1, false)",
                f"{APPLICATION_NAME}:{self._holder}",
            )
            taken = await connection.fetchval("select pg_try_advisory_lock($1)", self._key)
            if not taken:
                raise RealTelegramBusy(await _busy_message(connection, self._key))
        except BaseException:
            await connection.close()
            raise
        self._connection = connection

    async def _release(self) -> None:
        connection, self._connection = self._connection, None
        # Разорванное соединение уже унесло замок с собой: снимать нечего.
        if connection is None or connection.is_closed():
            return
        try:
            await connection.execute("select pg_advisory_unlock($1)", self._key)
        finally:
            await connection.close()


async def _busy_message(connection: asyncpg.Connection, key: int) -> str:
    """Кто держит замок: имя, которое держатель поставил себе в сессии."""
    holder = await connection.fetchval(
        """
        select a.application_name
          from pg_locks l
          join pg_stat_activity a on a.pid = l.pid
         where l.locktype = 'advisory' and l.granted
           and (l.classid::bigint << 32 | l.objid::bigint) = $1
         limit 1
        """,
        key,
    )
    where = f" ({holder})" if holder else ""
    return (
        f"Живые Telegram-тесты уже идут в другом прогоне{where}. Сессии проверяющего и "
        "мимика общие: одновременный запуск может заставить Telegram их отозвать. "
        "Дождитесь окончания того прогона."
    )
