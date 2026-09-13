"""Идемпотентно готовит проект Mimic42 Dev к тестам.

Создаёт схему test_support с таблицей аренды слотов и заводит
тестовые учётки через Admin API GoTrue. Запускается руками, требует
TEST_SUPABASE_SERVICE_ROLE_KEY. Повторный запуск ничего не ломает.
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg
import httpx

from mimic42.testing.slots import SLOTS

CREATE_SCHEMA_SQL = """
create schema if not exists test_support;

create table if not exists test_support.slot_leases (
    slot        text primary key,
    holder      text,
    acquired_at timestamptz,
    expires_at  timestamptz
);
"""


async def ensure_schema(dsn: str) -> None:
    connection = await asyncpg.connect(dsn)
    try:
        await connection.execute(CREATE_SCHEMA_SQL)
        for slot in SLOTS:
            await connection.execute(
                "insert into test_support.slot_leases (slot) values ($1) "
                "on conflict (slot) do nothing",
                slot.name,
            )
    finally:
        await connection.close()


async def ensure_users(supabase_url: str, service_key: str, password: str) -> None:
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=supabase_url.rstrip("/"), timeout=30.0) as client:
        for slot in SLOTS:
            for persona in slot.personas:
                response = await client.post(
                    "/auth/v1/admin/users",
                    headers=headers,
                    json={
                        "id": str(persona.user_id),
                        "email": persona.email,
                        "password": password,
                        "email_confirm": True,
                    },
                )
                if response.status_code in (200, 201):
                    print(f"создан {persona.email}")
                elif response.status_code in (409, 422):
                    print(f"уже есть {persona.email}")
                else:
                    raise RuntimeError(
                        f"не удалось создать {persona.email}: "
                        f"{response.status_code} {response.text}"
                    )


async def main() -> int:
    dsn = os.environ["TEST_DATABASE_CONNECTION_STRING"]
    supabase_url = os.environ["TEST_SUPABASE_URL"]
    service_key = os.environ["TEST_SUPABASE_SERVICE_ROLE_KEY"]
    password = os.environ["TEST_USER_PASSWORD"]
    if "ajcznltdbwvhmhgzufzv" in dsn or "ajcznltdbwvhmhgzufzv" in supabase_url:
        raise SystemExit("отказ: настройки указывают на прод")
    await ensure_schema(_plain_dsn(dsn))
    await ensure_users(supabase_url, service_key, password)
    return 0


def _plain_dsn(value: str) -> str:
    """asyncpg не понимает префикс SQLAlchemy."""
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
