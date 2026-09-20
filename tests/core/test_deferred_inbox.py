from __future__ import annotations

import asyncio
from typing import Any

from mimic42.core.deferred_inbox import DeferredInbox


class Recorder:
    def __init__(self) -> None:
        self.flushed: list[tuple[str, list[list[Any]]]] = []

    async def flush(self, peer: str, groups: list[list[Any]]) -> None:
        self.flushed.append((peer, groups))


class FakeClock:
    """Детерминированное время и сон — как в tests/core/test_album_grouper.py."""

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


def inbox_with(clock: FakeClock, recorder: Recorder, **kwargs: Any) -> DeferredInbox:
    return DeferredInbox(recorder.flush, now=clock.now, sleep=clock.sleep, **kwargs)


async def test_groups_are_delivered_together_when_the_window_opens() -> None:
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder)
    inbox.add("-100777", ["a"], delay=30.0)
    await clock.advance(10)
    inbox.add("-100777", ["b"], delay=20.0)
    assert recorder.flushed == []

    await clock.advance(20)
    assert recorder.flushed == [("-100777", [["a"], ["b"]])]


async def test_albums_stay_one_group() -> None:
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder)
    inbox.add("-100777", ["photo1", "photo2"], delay=5.0)
    await clock.advance(5)
    assert recorder.flushed == [("-100777", [["photo1", "photo2"]])]


async def test_different_peers_do_not_mix() -> None:
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder)
    inbox.add("-100777", ["a"], delay=5.0)
    inbox.add("-100888", ["b"], delay=5.0)
    await clock.advance(5)
    assert sorted(recorder.flushed) == [("-100777", [["a"]]), ("-100888", [["b"]])]


async def test_oldest_groups_are_evicted_past_the_cap() -> None:
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder, max_groups=2)
    for name in ("a", "b", "c"):
        inbox.add("-100777", [name], delay=10.0)
    await clock.advance(10)
    assert recorder.flushed == [("-100777", [["b"], ["c"]])]


async def test_stale_groups_are_dropped_on_flush() -> None:
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder, max_age=60.0)
    inbox.add("-100777", ["old"], delay=200.0)
    await clock.advance(150)
    inbox.add("-100777", ["fresh"], delay=50.0)
    await clock.advance(50)
    assert recorder.flushed == [("-100777", [["fresh"]])]


async def test_everything_stale_flushes_nothing() -> None:
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder, max_age=10.0)
    inbox.add("-100777", ["old"], delay=100.0)
    await clock.advance(100)
    assert recorder.flushed == []


async def test_close_cancels_pending_buffers() -> None:
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder)
    inbox.add("-100777", ["a"], delay=30.0)
    await inbox.close()
    await clock.advance(30)
    assert recorder.flushed == []


async def test_a_later_group_does_not_postpone_the_deadline() -> None:
    """Дедлайн — момент открытия окна, а не тишина: новый элемент его не двигает."""
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder)
    inbox.add("-100777", ["a"], delay=10.0)
    await clock.advance(5)
    inbox.add("-100777", ["b"], delay=100.0)
    await clock.advance(5)
    assert recorder.flushed == [("-100777", [["a"], ["b"]])]
