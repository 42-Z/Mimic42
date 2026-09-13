"""Очистка данных тестового слота. Выполняется ПЕРЕД прогоном,
чтобы после падения состояние можно было посмотреть глазами."""

from __future__ import annotations

import asyncpg

from mimic42.testing.slots import Slot, plain_dsn


async def purge_slot_data(dsn: str, slot: Slot) -> None:
    owner_ids = [persona.user_id for persona in slot.personas]
    connection = await asyncpg.connect(plain_dsn(dsn))
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
