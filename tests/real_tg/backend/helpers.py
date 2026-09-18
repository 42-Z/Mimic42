"""Помощники реальных TG-тестов бэкенда: логин, owner id и поиск агентов."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import asyncpg
import httpx
import jwt as pyjwt

from mimic42.testing.slots import plain_dsn

ROOT = Path(__file__).resolve().parents[3]


def anon_key() -> str:
    """Публичный anon-ключ: из окружения (CI) или frontend/.env.local (локально)."""
    value = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    if value:
        return value
    env_local = ROOT / "frontend" / ".env.local"
    if env_local.exists():
        for line in env_local.read_text().splitlines():
            if line.startswith("NEXT_PUBLIC_SUPABASE_ANON_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("SUPABASE_ANON_KEY / NEXT_PUBLIC_SUPABASE_ANON_KEY не найден")


async def jwt() -> str:
    """Supabase JWT для API-вызовов от имени реального сайт-аккаунта."""
    async with httpx.AsyncClient(base_url=os.environ["SUPABASE_URL"].rstrip("/")) as client:
        response = await client.post(
            "/auth/v1/token?grant_type=password",
            headers={"apikey": anon_key()},
            json={
                "email": os.environ["TEST_ACCOUNT_EMAIL"],
                "password": os.environ["TEST_ACCOUNT_PASSWORD"],
            },
        )
        response.raise_for_status()
        return str(response.json()["access_token"])


def user_id_from_token(token: str) -> UUID:
    """owner_id — тот же claim `sub`, что читает прод (`api/auth.py`).

    Подпись не проверяется: токен только что получен от Supabase по TLS,
    из него берётся собственная личность, а не принимается чужое решение.
    """
    payload = pyjwt.decode(token, options={"verify_signature": False})
    return UUID(str(payload["sub"]))


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
