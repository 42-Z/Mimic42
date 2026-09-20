"""Буфер входящих на время, пока окно отправки закрыто.

Устроен как AlbumGrouper, но копит не элементы одного альбома, а группы
сообщений по чату, и ждёт не тишины, а момента открытия окна. Каждая группа —
это одно сообщение или один альбом; при сливе они разбираются одним ходом.

Капы существуют ради главного требования: агент не должен отвечать на то, что
успело устареть, пока он молчал.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

logger = logging.getLogger("mimic42.deferred_inbox")

MAX_GROUPS = 20
MAX_AGE = 600.0


class DeferredInbox:
    """Копит группы входящих по чату и отдаёт их разом при открытии окна."""

    def __init__(
        self,
        flush: Callable[[str, list[list[Any]]], Awaitable[None]],
        *,
        max_groups: int | None = None,
        max_age: float | None = None,
        now: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        # Значения по умолчанию читаются в момент вызова (sentinel None), чтобы
        # тесты могли подменить константы модуля до создания рантайма.
        self._flush = flush
        self._max_groups = MAX_GROUPS if max_groups is None else max_groups
        self._max_age = MAX_AGE if max_age is None else max_age
        self._now = now if now is not None else self._loop_time
        self._sleep = sleep if sleep is not None else asyncio.sleep
        self._groups: dict[str, list[tuple[float, list[Any]]]] = {}
        self._deadlines: dict[str, float] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._flushing: set[asyncio.Task[None]] = set()

    @staticmethod
    def _loop_time() -> float:
        return asyncio.get_running_loop().time()

    def add(self, peer: str, group: list[Any], delay: float) -> None:
        """Положить группу в буфер; первая группа планирует слив."""
        now = self._now()
        entries = self._groups.setdefault(peer, [])
        entries.append((now, group))
        if len(entries) > self._max_groups:
            dropped = len(entries) - self._max_groups
            del entries[:dropped]
            logger.info("Вытеснено %d устаревших групп в чате %s", dropped, peer)

        if peer in self._tasks:
            # Дедлайн задаётся окном отправки, а не последним сообщением:
            # продлевать его новым входящим — значит копить отставание.
            return
        self._deadlines[peer] = now + max(delay, 0.0)
        self._tasks[peer] = asyncio.create_task(self._flush_after(peer))

    async def close(self) -> None:
        """Отменить ожидающие буферы; слив в полёте не обрывается."""
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        dropped = sum(len(entries) for entries in self._groups.values())
        self._groups.clear()
        self._deadlines.clear()
        if dropped:
            logger.warning("Отброшено %d отложенных групп при остановке", dropped)
        if self._flushing:
            logger.info("Оставлено %d сливов в полёте", len(self._flushing))

    async def _flush_after(self, peer: str) -> None:
        while True:
            delay = self._deadlines.get(peer, 0.0) - self._now()
            if delay <= 0:
                break
            await self._sleep(delay)

        entries = self._groups.pop(peer, [])
        self._deadlines.pop(peer, None)
        self._tasks.pop(peer, None)

        now = self._now()
        fresh = [group for added_at, group in entries if now - added_at <= self._max_age]
        stale = len(entries) - len(fresh)
        if stale:
            logger.info("Отброшено %d протухших групп в чате %s", stale, peer)
        if not fresh:
            return

        # Слив уже идёт: конкурентный close() не должен его отменять.
        task = asyncio.current_task()
        if task is not None:
            self._flushing.add(task)
        try:
            await self._flush(peer, fresh)
        except Exception:
            logger.exception("Слив отложенных сообщений чата %s упал", peer)
        finally:
            if task is not None:
                self._flushing.discard(task)
