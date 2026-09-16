"""Аренда набора тестовых учёток: база одна на всех, слотов несколько."""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

logger = logging.getLogger("mimic42.testing.slots")

DEV_PROJECT_REF = "ipqylrdmmjitemjrygej"
PROD_PROJECT_REF = "ajcznltdbwvhmhgzufzv"

# Аренду продлевает heartbeat, поэтому TTL короткий: упавший воркер держит
# слот минуты, а не полчаса. Ожидание при этом заметно длиннее TTL, чтобы
# очередь пережидала смерть держателя, а не сдавалась раньше него.
DEFAULT_LEASE_TTL_SECONDS = 300
DEFAULT_WAIT_TIMEOUT_SECONDS = 900
CONNECT_TIMEOUT_SECONDS = 20.0

PERSONA_KEYS = ("empty", "full", "flow", "twofa", "code")


def _jwt_payload(value: str) -> dict[str, Any] | None:
    """Payload Supabase-ключа, если значение похоже на JWT.

    У service_role/anon ключей ref проекта лежит в claim ``ref`` и в сыром
    виде подстрокой не встречается — его надо декодировать."""
    parts = value.split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, binascii.Error):
        return None
    return payload if isinstance(payload, dict) else None


def _project_ref(value: str) -> str | None:
    payload = _jwt_payload(value)
    if payload is not None:
        ref = payload.get("ref")
        return ref if isinstance(ref, str) else None
    if DEV_PROJECT_REF in value:
        return DEV_PROJECT_REF
    if PROD_PROJECT_REF in value:
        return PROD_PROJECT_REF
    return None


def assert_test_project(*values: str | None) -> None:
    """Отказ, если хоть одно значение не опознаётся как проект Mimic42 Dev.

    Allowlist, а не denylist: DSN, адрес и ключи обязаны явно указывать на
    Dev — рефом в строке подключения, в домене или в claim ``ref`` JWT.
    Значение без рефа (IP-литерал, кастомный домен, чужой ключ) отвергается
    целиком, а не проскакивает, как при поиске рефа прода подстрокой.

    Единая точка проверки для всего, что имеет доступ на запись/удаление
    в тестовую базу: pytest-фикстуры, разовые скрипты и тестовый сервер."""
    for value in values:
        if not value:
            continue
        ref = _project_ref(value)
        if ref == DEV_PROJECT_REF:
            continue
        if ref == PROD_PROJECT_REF:
            raise RuntimeError(
                f"отказ: тестовые настройки указывают на прод (project ref {PROD_PROJECT_REF})"
            )
        raise RuntimeError(
            "отказ: значение не опознано как проект Mimic42 Dev "
            f"(нужен ref {DEV_PROJECT_REF} в строке, домене или JWT-ключе)"
        )


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
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    wait_timeout: int = DEFAULT_WAIT_TIMEOUT_SECONDS,
    pool: tuple[str, ...] | None = None,
    heartbeat: bool = True,
) -> Slot:
    """pool сужает выбор до перечисленных имён строк — нужно только тестам
    самого механизма аренды, чтобы не зависеть от того, какой реальный слот
    сейчас держит текущая pytest-сессия. Реальные вызовы pool не передают.

    heartbeat продлевает аренду, пока процесс жив: упавший воркер теряет
    слот через ttl_seconds, а не держит его до конца прогона."""
    assert_test_project(dsn)
    deadline = datetime.now(UTC) + timedelta(seconds=wait_timeout)
    while True:
        taken = await _try_acquire(dsn, holder=holder, ttl_seconds=ttl_seconds, pool=pool)
        if taken is not None:
            if heartbeat:
                _start_heartbeat(dsn, taken.name, holder=holder, ttl_seconds=ttl_seconds)
            return taken
        if datetime.now(UTC) >= deadline:
            raise TimeoutError(
                "Все слоты тестовых аккаунтов заняты: дождитесь окончания другого прогона"
            )
        await asyncio.sleep(2)


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


_HEARTBEATS: dict[str, asyncio.Task[None]] = {}


def _start_heartbeat(dsn: str, slot: str, *, holder: str, ttl_seconds: int) -> None:
    _cancel_heartbeat(slot)
    task = asyncio.create_task(
        _heartbeat_loop(dsn, slot, holder=holder, ttl_seconds=ttl_seconds),
        name=f"slot-heartbeat:{slot}",
    )
    _HEARTBEATS[slot] = task


def _cancel_heartbeat(slot: str) -> None:
    task = _HEARTBEATS.pop(slot, None)
    if task is not None:
        task.cancel()


async def _stop_heartbeat(slot: str) -> None:
    task = _HEARTBEATS.pop(slot, None)
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _heartbeat_loop(dsn: str, slot: str, *, holder: str, ttl_seconds: int) -> None:
    interval = max(1.0, ttl_seconds / 3)
    while True:
        await asyncio.sleep(interval)
        try:
            connection = await asyncpg.connect(plain_dsn(dsn), timeout=CONNECT_TIMEOUT_SECONDS)
            try:
                status = await connection.execute(
                    "update test_support.slot_leases "
                    "set expires_at = now() + make_interval(secs => $3) "
                    "where slot = $1 and holder = $2",
                    slot,
                    holder,
                    float(ttl_seconds),
                )
            finally:
                await connection.close()
        except Exception:
            logger.warning("Не удалось продлить аренду слота %s", slot, exc_info=True)
            continue
        if status == "UPDATE 0":
            logger.warning(
                "Аренда слота %s больше не принадлежит %s: heartbeat остановлен",
                slot,
                holder,
            )
            return


async def release_slot(dsn: str, slot: Slot, *, holder: str) -> None:
    """Снять аренду, только если слот всё ещё держит этот holder.

    Без проверки протухший воркер своим teardown снимал бы чужой живой лиз
    и открывал слот третьему прогону поверх ещё работающего."""
    assert_test_project(dsn)
    await _stop_heartbeat(slot.name)
    connection = await asyncpg.connect(plain_dsn(dsn), timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        status = await connection.execute(
            "update test_support.slot_leases "
            "set holder = null, acquired_at = null, expires_at = null "
            "where slot = $1 and holder = $2",
            slot.name,
            holder,
        )
        if status == "UPDATE 0":
            logger.warning("Слот %s не принадлежит %s: аренда уже не наша", slot.name, holder)
    finally:
        await connection.close()
