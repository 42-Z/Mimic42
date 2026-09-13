from __future__ import annotations

from uuid import uuid4

import asyncpg

from mimic42.testing.cleanup import purge_slot_data
from mimic42.testing.slots import SLOTS, plain_dsn


async def _insert_agent(connection: asyncpg.Connection, owner_id: object, name: str) -> object:
    agent_id = uuid4()
    await connection.execute(
        "insert into public.agents (id, owner_id, name, soul_prompt, status) "
        "values ($1, $2, $3, 'тест', 'stopped')",
        agent_id,
        owner_id,
        name,
    )
    return agent_id


async def test_purge_removes_own_slot_and_keeps_the_other(test_dsn: str) -> None:
    own, other = SLOTS[0], SLOTS[1]
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        own_agent = await _insert_agent(connection, own.persona("full").user_id, "свой")
        other_agent = await _insert_agent(connection, other.persona("full").user_id, "чужой")

        await purge_slot_data(test_dsn, own)

        assert await connection.fetchval(
            "select count(*) from public.agents where id = $1", own_agent
        ) == 0
        assert await connection.fetchval(
            "select count(*) from public.agents where id = $1", other_agent
        ) == 1
    finally:
        await connection.execute(
            "delete from public.agents where owner_id = $1", other.persona("full").user_id
        )
        await connection.close()


async def test_purge_keeps_the_user_accounts_themselves(test_dsn: str) -> None:
    slot = SLOTS[0]
    await purge_slot_data(test_dsn, slot)
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        for persona in slot.personas:
            assert await connection.fetchval(
                "select count(*) from auth.users where id = $1", persona.user_id
            ) == 1
            assert await connection.fetchval(
                "select count(*) from public.profiles where id = $1", persona.user_id
            ) == 1
    finally:
        await connection.close()
