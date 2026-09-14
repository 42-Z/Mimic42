"""Аренда набора тестовых учёток: база одна на всех, слотов несколько."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg

PERSONA_KEYS = ("empty", "full", "flow", "twofa", "code")


@dataclass(frozen=True)
class Persona:
    key: str
    user_id: UUID
    email: str


@dataclass(frozen=True)
class Slot:
    name: str
    personas: tuple[Persona, ...]

    def persona(self, key: str) -> Persona:
        for persona in self.personas:
            if persona.key == key:
                return persona
        raise KeyError(f"В слоте {self.name} нет персоны {key}")


def _build_slot(name: str, digit: str, suffix: str) -> Slot:
    personas = tuple(
        Persona(
            key=key,
            user_id=UUID(f"{digit * 8}-{digit * 4}-{digit * 4}-{digit * 4}-{index:012d}"),
            email=f"e2e-{key}{suffix}@mimic42.test",
        )
        for index, key in enumerate(PERSONA_KEYS, start=1)
    )
    return Slot(name=name, personas=personas)


SLOTS: tuple[Slot, ...] = (
    _build_slot("a", "1", ""),
    _build_slot("b", "2", "-b"),
)


def plain_dsn(value: str) -> str:
    """asyncpg не понимает префикс драйвера из строки SQLAlchemy."""
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


async def acquire_slot(
    dsn: str,
    *,
    holder: str,
    ttl_seconds: int = 1800,
    wait_timeout: int = 600,
    pool: tuple[str, ...] | None = None,
) -> Slot:
    """pool сужает выбор до перечисленных имён строк — нужно только тестам
    самого механизма аренды, чтобы не зависеть от того, какой реальный слот
    сейчас держит текущая pytest-сессия. Реальные вызовы pool не передают."""
    deadline = datetime.now(UTC) + timedelta(seconds=wait_timeout)
    while True:
        taken = await _try_acquire(dsn, holder=holder, ttl_seconds=ttl_seconds, pool=pool)
        if taken is not None:
            return taken
        if datetime.now(UTC) >= deadline:
            raise TimeoutError(
                "Все слоты тестовых аккаунтов заняты: дождитесь окончания другого прогона"
            )
        await asyncio.sleep(2)


CONNECT_TIMEOUT_SECONDS = 20.0


async def _try_acquire(
    dsn: str, *, holder: str, ttl_seconds: int, pool: tuple[str, ...] | None = None
) -> Slot | None:
    connection = await asyncpg.connect(plain_dsn(dsn), timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        row = await connection.fetchrow(
            """
            update test_support.slot_leases
               set holder = $1,
                   acquired_at = now(),
                   expires_at = now() + make_interval(secs => $2)
             where slot = (
                 select slot
                   from test_support.slot_leases
                  where (holder is null or expires_at < now())
                    and ($3::text[] is null or slot = any($3::text[]))
                  order by slot
                    for update skip locked
                  limit 1
             )
            returning slot
            """,
            holder,
            float(ttl_seconds),
            list(pool) if pool is not None else None,
        )
    finally:
        await connection.close()
    if row is None:
        return None
    return _find_slot(row["slot"])


def _find_slot(name: str) -> Slot:
    """Именованные слоты пула резолвятся в SLOTS; любые другие строки
    таблицы (например, временные ряды, которые заводят тесты самого
    механизма аренды) возвращают заглушку без персон."""
    return next((slot for slot in SLOTS if slot.name == name), Slot(name=name, personas=()))


async def release_slot(dsn: str, slot: Slot) -> None:
    connection = await asyncpg.connect(plain_dsn(dsn), timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        await connection.execute(
            "update test_support.slot_leases "
            "set holder = null, acquired_at = null, expires_at = null where slot = $1",
            slot.name,
        )
    finally:
        await connection.close()
