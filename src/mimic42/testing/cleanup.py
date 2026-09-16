"""Очистка данных тестового слота. Выполняется ПЕРЕД прогоном,
чтобы после падения состояние можно было посмотреть глазами."""

from __future__ import annotations

from uuid import UUID

import asyncpg

from mimic42.testing.slots import CONNECT_TIMEOUT_SECONDS, Slot, assert_test_project, plain_dsn


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
