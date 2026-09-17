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


@pytest.mark.asyncio
async def test_album_items_flush_together_after_quiet_window() -> None:
    recorder = Recorder()
    grouper = AlbumGrouper(recorder.flush, quiet_window=0.05, max_window=0.5)

    for i in range(3):
        grouper.add(("chat", "1"), f"event-{i}")
        await asyncio.sleep(0.02)

    await asyncio.sleep(0.4)

    assert recorder.flushed == [["event-0", "event-1", "event-2"]]


@pytest.mark.asyncio
async def test_interleaved_albums_flush_separately() -> None:
    recorder = Recorder()
    grouper = AlbumGrouper(recorder.flush, quiet_window=0.05, max_window=0.5)

    grouper.add(("chat", "1"), "a-1")
    grouper.add(("chat", "2"), "b-1")
    grouper.add(("chat", "1"), "a-2")
    grouper.add(("other", "2"), "c-1")

    await asyncio.sleep(0.4)

    batches = {tuple(sorted(batch)) for batch in recorder.flushed}
    assert batches == {("a-1", "a-2"), ("b-1",), ("c-1",)}


@pytest.mark.asyncio
async def test_item_after_flush_starts_a_new_buffer() -> None:
    recorder = Recorder()
    grouper = AlbumGrouper(recorder.flush, quiet_window=0.05, max_window=0.5)

    grouper.add(("chat", "1"), "first")
    await asyncio.sleep(0.4)
    assert recorder.flushed == [["first"]]

    # Опоздавший элемент после доставки не теряется — начинает новый буфер.
    grouper.add(("chat", "1"), "late")
    await asyncio.sleep(0.4)
    assert recorder.flushed == [["first"], ["late"]]


@pytest.mark.asyncio
async def test_close_cancels_pending_buffers_without_flushing() -> None:
    recorder = Recorder()
    grouper = AlbumGrouper(recorder.flush, quiet_window=0.05, max_window=30.0)

    grouper.add(("chat", "1"), "pending")
    await grouper.close()
    await asyncio.sleep(0.1)

    assert recorder.flushed == []


@pytest.mark.asyncio
async def test_max_window_caps_extensions() -> None:
    recorder = Recorder()
    grouper = AlbumGrouper(recorder.flush, quiet_window=0.15, max_window=0.3)

    grouper.add(("chat", "1"), "first")
    # Элементы приходят дольше капа: flush обязан случиться не позже капа.
    for i in range(6):
        await asyncio.sleep(0.1)
        grouper.add(("chat", "1"), f"late-{i}")

    await asyncio.sleep(0.5)

    assert recorder.flushed, "flush должен был случиться"
    first = recorder.flushed[0]
    assert first[0] == "first"
    # До капа успели доехать не все: часть осталась на отдельный буфер/потеряна
    # в этой доставке, но flush случился и не завис навсегда.
    assert len(first) < 7
