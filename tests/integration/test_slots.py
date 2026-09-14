from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest

from mimic42.testing.slots import SLOTS, acquire_slot, plain_dsn, release_slot


@pytest.fixture
async def temp_slots(test_dsn: str) -> AsyncIterator[tuple[str, str]]:
    """Две одноразовые строки в test_support.slot_leases, не пересекающиеся
    с реальным пулом SLOTS. Механизм аренды тестируется здесь изолированно
    от слота, который сессия уже держит на время всего прогона."""
    names = ("test-x", "test-y")
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        for name in names:
            await connection.execute(
                "insert into test_support.slot_leases (slot) values ($1) "
                "on conflict (slot) do update set holder = null, "
                "acquired_at = null, expires_at = null",
                name,
            )
        yield names
    finally:
        await connection.execute(
            "delete from test_support.slot_leases where slot = any($1::text[])", list(names)
        )
        await connection.close()


async def test_two_holders_get_different_slots(test_dsn: str, temp_slots: tuple[str, str]) -> None:
    first = await acquire_slot(test_dsn, holder="first", wait_timeout=30, pool=temp_slots)
    second = await acquire_slot(test_dsn, holder="second", wait_timeout=30, pool=temp_slots)
    try:
        assert first.name != second.name
        assert {first.name, second.name} == set(temp_slots)
    finally:
        await release_slot(test_dsn, first)
        await release_slot(test_dsn, second)


async def test_third_holder_waits_and_fails_by_timeout(
    test_dsn: str, temp_slots: tuple[str, str]
) -> None:
    first = await acquire_slot(test_dsn, holder="first", wait_timeout=30, pool=temp_slots)
    second = await acquire_slot(test_dsn, holder="second", wait_timeout=30, pool=temp_slots)
    try:
        with pytest.raises(TimeoutError):
            await acquire_slot(test_dsn, holder="third", wait_timeout=2, pool=temp_slots)
    finally:
        await release_slot(test_dsn, first)
        await release_slot(test_dsn, second)


async def test_expired_lease_is_reclaimed(test_dsn: str, temp_slots: tuple[str, str]) -> None:
    stale = await acquire_slot(
        test_dsn, holder="stale", ttl_seconds=-1, wait_timeout=30, pool=temp_slots
    )
    try:
        reclaimed = await acquire_slot(test_dsn, holder="fresh", wait_timeout=30, pool=temp_slots)
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
