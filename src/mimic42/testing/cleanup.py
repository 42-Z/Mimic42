"""Подготовка и очистка данных тестового контура. Очистка выполняется ПЕРЕД
прогоном, чтобы после падения состояние можно было посмотреть глазами."""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple
from uuid import UUID

import asyncpg

from mimic42.core.crypto import FernetSecretCipher
from mimic42.testing.slots import CONNECT_TIMEOUT_SECONDS, Slot, assert_test_project, plain_dsn


class PlatformTelegramSnapshot(NamedTuple):
    api_id: int
    api_hash_ciphertext: str
    updated_by: UUID | None
    updated_at: datetime


async def seed_platform_telegram_settings(
    dsn: str,
    *,
    secret_key: str,
    api_id: int,
    api_hash: str,
) -> PlatformTelegramSnapshot | None:
    """Кладёт пару Telegram-приложения в platform_telegram_settings.

    Панель администра — единственный источник пары, поэтому тестовые контуры
    (e2e, real_tg) перед стартом приложения записывают пару из окружения в базу.
    Повторный запуск перезаписывает строку. Возвращает прежнюю строку, чтобы
    вызывающий код мог вернуть состояние окружения после прогона.
    """
    assert_test_project(dsn)
    ciphertext = FernetSecretCipher(secret_key).encrypt(api_hash)
    connection = await asyncpg.connect(plain_dsn(dsn), timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        previous = await connection.fetchrow(
            "select api_id, api_hash_ciphertext, updated_by, updated_at "
            "from public.platform_telegram_settings where id = 1"
        )
        await connection.execute(
            """
            insert into public.platform_telegram_settings
                (id, api_id, api_hash_ciphertext, updated_by)
            values (1, $1, $2, null)
            on conflict (id) do update set
                api_id = excluded.api_id,
                api_hash_ciphertext = excluded.api_hash_ciphertext,
                updated_by = null,
                updated_at = now()
            """,
            api_id,
            ciphertext,
        )
    finally:
        await connection.close()
    if previous is None:
        return None
    return PlatformTelegramSnapshot(
        api_id=previous["api_id"],
        api_hash_ciphertext=previous["api_hash_ciphertext"],
        updated_by=previous["updated_by"],
        updated_at=previous["updated_at"],
    )


async def restore_platform_telegram_settings(
    dsn: str,
    snapshot: PlatformTelegramSnapshot | None,
) -> None:
    """Возвращает строку platform_telegram_settings к состоянию до прогона."""
    assert_test_project(dsn)
    connection = await asyncpg.connect(plain_dsn(dsn), timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        if snapshot is None:
            await connection.execute("delete from public.platform_telegram_settings where id = 1")
            return
        await connection.execute(
            """
            insert into public.platform_telegram_settings
                (id, api_id, api_hash_ciphertext, updated_by, updated_at)
            values (1, $1, $2, $3, $4)
            on conflict (id) do update set
                api_id = excluded.api_id,
                api_hash_ciphertext = excluded.api_hash_ciphertext,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            snapshot.api_id,
            snapshot.api_hash_ciphertext,
            snapshot.updated_by,
            snapshot.updated_at,
        )
    finally:
        await connection.close()


async def purge_slot_data(dsn: str, slot: Slot) -> None:
    assert_test_project(dsn)
    owner_ids = [persona.user_id for persona in slot.personas]
    connection = await asyncpg.connect(plain_dsn(dsn), timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        async with connection.transaction():
            await connection.execute(
                "delete from public.agent_onboarding_sessions where owner_id = any($1::uuid[])",
                owner_ids,
            )
            await connection.execute(
                "delete from public.agents where owner_id = any($1::uuid[])",
                owner_ids,
            )
    finally:
        await connection.close()


async def hide_incomplete_onboarding_drafts(dsn: str, owner_id: UUID) -> int:
    """Удаляет незавершённые черновики онбординга владельца.

    Нужно e2e-визарду, который должен начинаться с чистого листа, а не
    продолжать незавершённый черновик предыдущей попытки."""
    assert_test_project(dsn)
    connection = await asyncpg.connect(plain_dsn(dsn), timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        status = await connection.execute(
            "delete from public.agent_onboarding_sessions "
            "where owner_id = $1 and completed_agent_id is null",
            owner_id,
        )
    finally:
        await connection.close()
    return int(status.rsplit(" ", 1)[-1])


async def current_onboarding_draft_id(dsn: str, owner_id: UUID) -> UUID | None:
    """Id самого свежего незавершённого черновика владельца — тот самый,
    который видит и продолжает визард."""
    assert_test_project(dsn)
    connection = await asyncpg.connect(plain_dsn(dsn), timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        value = await connection.fetchval(
            "select id from public.agent_onboarding_sessions "
            "where owner_id = $1 and completed_agent_id is null "
            "order by created_at desc limit 1",
            owner_id,
        )
    finally:
        await connection.close()
    return value if isinstance(value, UUID) else None
