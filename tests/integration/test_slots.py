from __future__ import annotations

import os

import pytest

from mimic42.testing.slots import SLOTS, acquire_slot, release_slot

pytestmark = pytest.mark.db

DSN = os.environ.get("TEST_DATABASE_CONNECTION_STRING", "")


async def test_two_holders_get_different_slots() -> None:
    first = await acquire_slot(DSN, holder="first", wait_timeout=5)
    second = await acquire_slot(DSN, holder="second", wait_timeout=5)
    try:
        assert first.name != second.name
    finally:
        await release_slot(DSN, first)
        await release_slot(DSN, second)


async def test_third_holder_waits_and_fails_by_timeout() -> None:
    first = await acquire_slot(DSN, holder="first", wait_timeout=5)
    second = await acquire_slot(DSN, holder="second", wait_timeout=5)
    try:
        with pytest.raises(TimeoutError):
            await acquire_slot(DSN, holder="third", wait_timeout=2)
    finally:
        await release_slot(DSN, first)
        await release_slot(DSN, second)


async def test_expired_lease_is_reclaimed() -> None:
    stale = await acquire_slot(DSN, holder="stale", ttl_seconds=-1, wait_timeout=5)
    try:
        reclaimed = await acquire_slot(DSN, holder="fresh", wait_timeout=5)
        assert reclaimed.name == stale.name
        await release_slot(DSN, reclaimed)
    finally:
        await release_slot(DSN, stale)


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
