from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime

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


async def _holder_of(test_dsn: str, name: str) -> str | None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        return await connection.fetchval(
            "select holder from test_support.slot_leases where slot = $1", name
        )
    finally:
        await connection.close()


async def _expires_at(test_dsn: str, name: str) -> datetime | None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        value = await connection.fetchval(
            "select expires_at from test_support.slot_leases where slot = $1", name
        )
        return value if isinstance(value, datetime) else None
    finally:
        await connection.close()


async def test_two_holders_get_different_slots(test_dsn: str, temp_slots: tuple[str, str]) -> None:
    first = await acquire_slot(test_dsn, holder="first", wait_timeout=30, pool=temp_slots)
    second = await acquire_slot(test_dsn, holder="second", wait_timeout=30, pool=temp_slots)
    try:
        assert first.name != second.name
        assert {first.name, second.name} == set(temp_slots)
    finally:
        await release_slot(test_dsn, first, holder="first")
        await release_slot(test_dsn, second, holder="second")


async def test_third_holder_waits_and_fails_by_timeout(
    test_dsn: str, temp_slots: tuple[str, str]
) -> None:
    first = await acquire_slot(test_dsn, holder="first", wait_timeout=30, pool=temp_slots)
    second = await acquire_slot(test_dsn, holder="second", wait_timeout=30, pool=temp_slots)
    try:
        with pytest.raises(TimeoutError):
            await acquire_slot(test_dsn, holder="third", wait_timeout=2, pool=temp_slots)
    finally:
        await release_slot(test_dsn, first, holder="first")
        await release_slot(test_dsn, second, holder="second")


async def test_expired_lease_is_reclaimed(test_dsn: str, temp_slots: tuple[str, str]) -> None:
    stale = await acquire_slot(
        test_dsn,
        holder="stale",
        ttl_seconds=-1,
        wait_timeout=30,
        pool=temp_slots,
        heartbeat=False,
    )
    try:
        reclaimed = await acquire_slot(test_dsn, holder="fresh", wait_timeout=30, pool=temp_slots)
        assert reclaimed.name == stale.name
        await release_slot(test_dsn, reclaimed, holder="fresh")
    finally:
        # Протухший holder снимает только свой (уже чужой) лиз — no-op.
        await release_slot(test_dsn, stale, holder="stale")


async def test_release_by_another_holder_keeps_the_lease(
    test_dsn: str, temp_slots: tuple[str, str]
) -> None:
    slot = await acquire_slot(test_dsn, holder="owner", wait_timeout=30, pool=temp_slots)
    other = next(name for name in temp_slots if name != slot.name)

    await release_slot(test_dsn, slot, holder="intruder")

    assert await _holder_of(test_dsn, slot.name) == "owner"
    assert await _holder_of(test_dsn, other) is None
    await release_slot(test_dsn, slot, holder="owner")
    assert await _holder_of(test_dsn, slot.name) is None


async def test_heartbeat_renews_the_lease(test_dsn: str, temp_slots: tuple[str, str]) -> None:
    # Гонки с истечением TTL нет намеренно: соединение до облачного pooler
    # бывает медленнее, чем успел бы обновиться лиз, и такая гонка плевала
    # бы в результат. Проверяем сам факт продления.
    slot = await acquire_slot(
        test_dsn, holder="alive", ttl_seconds=3, wait_timeout=30, pool=(temp_slots[0],)
    )
    try:
        first = await _expires_at(test_dsn, slot.name)
        await asyncio.sleep(3.5)
        second = await _expires_at(test_dsn, slot.name)
        assert first is not None
        assert second is not None
        assert second > first
    finally:
        await release_slot(test_dsn, slot, holder="alive")


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
