"""Помощники реальных TG-тестов бэкенда: JWT и поиск агентов в базе."""

from __future__ import annotations

import os
from uuid import UUID

import asyncpg
import httpx

from mimic42.testing.slots import plain_dsn


async def jwt() -> str:
    """Supabase JWT для API-вызовов от имени реального сайт-аккаунта."""
    async with httpx.AsyncClient(base_url=os.environ["SUPABASE_URL"].rstrip("/")) as client:
        response = await client.post(
            "/auth/v1/token?grant_type=password",
            headers={"apikey": os.environ["SUPABASE_ANON_KEY"]},
            json={
                "email": os.environ["REAL_TG_EMAIL"],
                "password": os.environ["REAL_TG_PASSWORD"],
            },
        )
        response.raise_for_status()
        return str(response.json()["access_token"])


async def agent_id_for_phone(dsn: str, phone: str, owner_id: UUID) -> str:
    conn = await asyncpg.connect(plain_dsn(dsn))
    try:
        row = await conn.fetchrow(
            """
            select a.id::text as agent_id
            from agents a join telegram_sessions ts on ts.agent_id = a.id
            where ts.phone_number = $1 and a.owner_id = $2
            """,
            phone,
            owner_id,
        )
    finally:
        await conn.close()
    assert row, f"Нет агента с телефоном {phone}"
    return str(row["agent_id"])
