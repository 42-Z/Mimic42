from __future__ import annotations

import os
from uuid import uuid4

import asyncpg
import pytest

from mimic42.testing.cleanup import purge_slot_data
from mimic42.testing.slots import SLOTS, plain_dsn

pytestmark = pytest.mark.db

DSN = os.environ.get("TEST_DATABASE_CONNECTION_STRING", "")


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


async def test_purge_removes_own_slot_and_keeps_the_other() -> None:
    own, other = SLOTS[0], SLOTS[1]
    connection = await asyncpg.connect(plain_dsn(DSN))
    try:
        own_agent = await _insert_agent(connection, own.persona("full").user_id, "свой")
        other_agent = await _insert_agent(connection, other.persona("full").user_id, "чужой")

        await purge_slot_data(DSN, own)

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


async def test_purge_keeps_the_user_accounts_themselves() -> None:
    slot = SLOTS[0]
    await purge_slot_data(DSN, slot)
    connection = await asyncpg.connect(plain_dsn(DSN))
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
