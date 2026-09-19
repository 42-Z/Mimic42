from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mimic42.core.album_grouper import AlbumGrouper


class Recorder:
    def __init__(self) -> None:
        self.flushed: list[list[Any]] = []

    async def flush(self, events: list[Any]) -> None:
        self.flushed.append(events)


class FakeClock:
    """Инъекция времени в AlbumGrouper: детерминированное ``now`` и ``sleep``
    вместо реальных задержек, чтобы тесты не зависели от планировщика asyncio."""

    def __init__(self) -> None:
        self._time = 0.0
        self._waiters: list[tuple[float, asyncio.Event]] = []

    def now(self) -> float:
        return self._time

    async def sleep(self, delay: float) -> None:
        waiter = (self._time + max(delay, 0.0), asyncio.Event())
        self._waiters.append(waiter)
        try:
            await waiter[1].wait()
        finally:
            if waiter in self._waiters:
                self._waiters.remove(waiter)

    async def advance(self, delta: float) -> None:
        self._time += delta
        # Даём уже созданным задачам дойти до первого sleep и зарегистрироваться.
        await asyncio.sleep(0)
        for _ in range(100):
            due = [waiter for waiter in self._waiters if waiter[0] <= self._time]
            if not due:
                return
            for _, event in due:
                event.set()
            await asyncio.sleep(0)
            self._waiters = [waiter for waiter in self._waiters if not waiter[1].is_set()]
        raise AssertionError("fake clock did not settle")


def grouper_with(clock: FakeClock, recorder: Recorder, **kwargs: Any) -> AlbumGrouper:
    return AlbumGrouper(
        recorder.flush,
        now=clock.now,
        sleep=clock.sleep,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_album_items_flush_together_after_quiet_window() -> None:
    clock = FakeClock()
    recorder = Recorder()
    grouper = grouper_with(clock, recorder, quiet_window=0.05, max_window=0.5)

    for i in range(3):
        grouper.add(("chat", "1"), f"event-{i}")
        await clock.advance(0.02)

    await clock.advance(0.05)

    assert recorder.flushed == [["event-0", "event-1", "event-2"]]


@pytest.mark.asyncio
async def test_interleaved_albums_flush_separately() -> None:
    clock = FakeClock()
    recorder = Recorder()
    grouper = grouper_with(clock, recorder, quiet_window=0.05, max_window=0.5)

    grouper.add(("chat", "1"), "a-1")
    grouper.add(("chat", "2"), "b-1")
    grouper.add(("chat", "1"), "a-2")
    grouper.add(("other", "2"), "c-1")

    await clock.advance(0.05)

    batches = {tuple(sorted(batch)) for batch in recorder.flushed}
    assert batches == {("a-1", "a-2"), ("b-1",), ("c-1",)}


@pytest.mark.asyncio
async def test_item_after_flush_starts_a_new_buffer() -> None:
    clock = FakeClock()
    recorder = Recorder()
    grouper = grouper_with(clock, recorder, quiet_window=0.05, max_window=0.5)

    grouper.add(("chat", "1"), "first")
    await clock.advance(0.05)
    assert recorder.flushed == [["first"]]

    # Опоздавший элемент после доставки не теряется — начинает новый буфер.
    grouper.add(("chat", "1"), "late")
    await clock.advance(0.05)
    assert recorder.flushed == [["first"], ["late"]]


@pytest.mark.asyncio
async def test_close_cancels_pending_buffers_without_flushing() -> None:
    clock = FakeClock()
    recorder = Recorder()
    grouper = grouper_with(clock, recorder, quiet_window=0.05, max_window=30.0)

    grouper.add(("chat", "1"), "pending")
    await grouper.close()
    await clock.advance(0.05)

    assert recorder.flushed == []


@pytest.mark.asyncio
async def test_close_does_not_cancel_an_in_flight_flush() -> None:
    """Остановка агента не должна обрывать уже начавшийся ход: ответ мог уйти
    в Telegram, и отмена посреди flush теряет запись хода."""
    clock = FakeClock()
    started = asyncio.Event()
    finished: list[int] = []

    async def slow_flush(events: list[Any]) -> None:
        started.set()
        await asyncio.sleep(0.1)
        finished.append(len(events))

    grouper = AlbumGrouper(
        slow_flush,
        quiet_window=0.01,
        max_window=0.1,
        now=clock.now,
        sleep=clock.sleep,
    )
    grouper.add(("chat", "1"), "x")
    await clock.advance(0.01)
    await started.wait()

    await grouper.close()  # не ждёт LLM-ход и не отменяет его

    assert finished == []
    await asyncio.sleep(0.2)
    assert finished == [1]


@pytest.mark.asyncio
async def test_max_window_caps_extensions() -> None:
    clock = FakeClock()
    recorder = Recorder()
    # Элементы приходят чаще, чем тихое окно, поэтому без капа flush бы не наступил.
    grouper = grouper_with(clock, recorder, quiet_window=0.1, max_window=0.25)

    grouper.add(("chat", "1"), "first")
    for i in range(4):
        await clock.advance(0.05)
        grouper.add(("chat", "1"), f"item-{i}")

    # Кап (0.25 c) ещё не достигнут: тишины не было, буфер держится.
    assert recorder.flushed == []

    # На капе flush случается ровно с тем, что успело доехать.
    await clock.advance(0.05)
    assert recorder.flushed == [["first", "item-0", "item-1", "item-2", "item-3"]]

    # Опоздавший после капа элемент обрабатывается отдельным буфером.
    await clock.advance(0.05)
    grouper.add(("chat", "1"), "after-cap")
    await clock.advance(0.1)
    assert recorder.flushed == [
        ["first", "item-0", "item-1", "item-2", "item-3"],
        ["after-cap"],
    ]
