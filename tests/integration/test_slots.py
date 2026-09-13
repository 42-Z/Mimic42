from __future__ import annotations

import pytest

from mimic42.testing.slots import SLOTS, acquire_slot, release_slot


async def test_two_holders_get_different_slots(test_dsn: str) -> None:
    first = await acquire_slot(test_dsn, holder="first", wait_timeout=30)
    second = await acquire_slot(test_dsn, holder="second", wait_timeout=30)
    try:
        assert first.name != second.name
    finally:
        await release_slot(test_dsn, first)
        await release_slot(test_dsn, second)


async def test_third_holder_waits_and_fails_by_timeout(test_dsn: str) -> None:
    first = await acquire_slot(test_dsn, holder="first", wait_timeout=30)
    second = await acquire_slot(test_dsn, holder="second", wait_timeout=30)
    try:
        with pytest.raises(TimeoutError):
            await acquire_slot(test_dsn, holder="third", wait_timeout=2)
    finally:
        await release_slot(test_dsn, first)
        await release_slot(test_dsn, second)


async def test_expired_lease_is_reclaimed(test_dsn: str) -> None:
    stale = await acquire_slot(test_dsn, holder="stale", ttl_seconds=-1, wait_timeout=30)
    try:
        reclaimed = await acquire_slot(test_dsn, holder="fresh", wait_timeout=30)
        assert reclaimed.name == stale.name
        await release_slot(test_dsn, reclaimed)
    finally:
        await release_slot(test_dsn, stale)


async def test_every_slot_has_five_personas() -> None:
    assert len(SLOTS) == 2
    for slot in SLOTS:
        assert {persona.key for persona in slot.personas} == {
            "empty",
            "full",
            "flow",
            "twofa",
            "code",
        }
