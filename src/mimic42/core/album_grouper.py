"""Группировка элементов Telegram-альбома в одно событие.

Альбом на уровне API — это несколько отдельных сообщений с одинаковым
``grouped_id`` (core.telegram.org/api/files#albums-grouped-media). Официальная
рекомендация Telethon (гайд миграции на v2) — буферизовать их самостоятельно:
«тихое окно», продлеваемое каждым новым элементом, плюс жёсткий предел на весь
буфер от момента прибытия первого элемента. Опоздавший после доставки элемент
начинает новый буфер и обрабатывается отдельным ходом — ничего не теряется.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

logger = logging.getLogger("mimic42.album_grouper")

# Сколько ждём тишины после последнего элемента и сколько всего ждём от первого.
# Встроенный events.Album в Telethon ждёт 0.5 c и опоздавших теряет; документация
# отмечает, что задержки между элементами могут превышать секунду.
QUIET_WINDOW = 1.0
MAX_WINDOW = 4.0

AlbumKey = tuple[str, str]


class AlbumGrouper:
    """Буферизует элементы альбома по (chat_id, grouped_id) и отдаёт их разом."""

    def __init__(
        self,
        flush: Callable[[list[Any]], Awaitable[None]],
        *,
        quiet_window: float | None = None,
        max_window: float | None = None,
        now: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        # Значения по умолчанию читаются в момент вызова (sentinel None), чтобы
        # тесты могли monkeypatch-нуть константы модуля до создания рантайма.
        self._flush = flush
        self._quiet = QUIET_WINDOW if quiet_window is None else quiet_window
        self._cap = MAX_WINDOW if max_window is None else max_window
        self._now = now if now is not None else self._loop_time
        self._sleep = sleep if sleep is not None else asyncio.sleep
        self._events: dict[AlbumKey, list[Any]] = {}
        self._deadlines: dict[AlbumKey, float] = {}
        self._cap_deadlines: dict[AlbumKey, float] = {}
        self._tasks: dict[AlbumKey, asyncio.Task[None]] = {}

    @staticmethod
    def _loop_time() -> float:
        return asyncio.get_running_loop().time()

    def add(self, key: AlbumKey, event: Any) -> None:
        """Положить элемент альбома в буфер; первый элемент планирует flush."""
        now = self._now()
        if key in self._events:
            self._events[key].append(event)
            # Окно отсчитывается от последнего элемента, но не дальше капа,
            # зафиксированного на момент прибытия первого.
            self._deadlines[key] = min(self._cap_deadlines[key], now + self._quiet)
            return
        self._events[key] = [event]
        self._cap_deadlines[key] = now + self._cap
        self._deadlines[key] = now + self._quiet
        self._tasks[key] = asyncio.create_task(self._flush_after(key))

    async def close(self) -> None:
        """Отменить незавершённые буферы (при остановке агента)."""
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        dropped = sum(len(events) for events in self._events.values())
        self._events.clear()
        self._deadlines.clear()
        self._cap_deadlines.clear()
        if dropped:
            logger.warning("Dropped %d buffered album item(s) on close", dropped)

    async def _flush_after(self, key: AlbumKey) -> None:
        try:
            while True:
                delay = self._deadlines.get(key, 0.0) - self._now()
                if delay <= 0:
                    break
                await self._sleep(delay)
        except asyncio.CancelledError:
            raise
        except KeyError:  # буфер уже забран/закрыт
            return
        events = self._events.pop(key, [])
        self._deadlines.pop(key, None)
        self._cap_deadlines.pop(key, None)
        self._tasks.pop(key, None)
        if not events:
            return
        try:
            await self._flush(events)
        except Exception:
            logger.exception("Album flush failed for key %s", key)
