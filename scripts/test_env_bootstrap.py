"""Идемпотентно готовит проект Mimic42 Dev к тестам.

Создаёт схему test_support с таблицей аренды слотов, заводит тестовые
учётки персон и, если заданы TEST_ACCOUNT_EMAIL/PASSWORD, аккаунт сайта для
реальных TG-тестов — всё через Admin API GoTrue. Запускается руками; берёт
SUPABASE_SERVICE_ROLE_KEY из .env (или явного TEST_SUPABASE_SERVICE_ROLE_KEY).
Повторный запуск ничего не ломает.
"""

from __future__ import annotations

import asyncio
import os
import sys
from uuid import UUID

import asyncpg
import httpx

from mimic42.testing.env import load_test_env
from mimic42.testing.slots import SLOTS, assert_test_project

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


async def _create_user(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    email: str,
    password: str,
    user_id: UUID | None = None,
) -> None:
    payload: dict[str, object] = {
        "email": email,
        "password": password,
        "email_confirm": True,
    }
    if user_id is not None:
        payload["id"] = str(user_id)
    response = await client.post("/auth/v1/admin/users", headers=headers, json=payload)
    if response.status_code in (200, 201):
        print(f"создан {email}")
    elif response.status_code in (409, 422):
        print(f"уже есть {email}")
    else:
        raise RuntimeError(f"не удалось создать {email}: {response.status_code} {response.text}")


async def ensure_users(supabase_url: str, service_key: str, password: str) -> None:
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=supabase_url.rstrip("/"), timeout=30.0) as client:
        for slot in SLOTS:
            for persona in slot.personas:
                await _create_user(
                    client,
                    headers,
                    email=persona.email,
                    password=password,
                    user_id=persona.user_id,
                )


async def ensure_real_tg_account(supabase_url: str, service_key: str) -> None:
    """Выделенный аккаунт сайта для реальных TG-тестов — если заданы креды.

    Id не фиксируется: тесты берут owner_id из claim `sub` своего JWT.
    """
    email = os.environ.get("TEST_ACCOUNT_EMAIL")
    password = os.environ.get("TEST_ACCOUNT_PASSWORD")
    if not email or not password:
        print("TEST_ACCOUNT_* не заданы — аккаунт реальных TG-тестов пропущен")
        return
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=supabase_url.rstrip("/"), timeout=30.0) as client:
        await _create_user(client, headers, email=email, password=password)


async def main() -> int:
    load_test_env()
    dsn = os.environ["DATABASE_CONNECTION_STRING"]
    supabase_url = os.environ["SUPABASE_URL"]
    password = os.environ["TEST_USER_PASSWORD"]
    # Приложенческий service-ключ уже лежит в .env (нужен медиа-стораджу);
    # TEST_SUPABASE_SERVICE_ROLE_KEY остаётся явным оверрайдом для запусков,
    # где .env недоступен.
    service_key = os.environ.get("TEST_SUPABASE_SERVICE_ROLE_KEY") or os.environ.get(
        "SUPABASE_SERVICE_ROLE_KEY", ""
    )
    if not service_key:
        raise SystemExit(
            "Сервисный ключ не найден: заполни SUPABASE_SERVICE_ROLE_KEY в .env "
            "или передай TEST_SUPABASE_SERVICE_ROLE_KEY явно."
        )
    try:
        # service_key сразу пойдёт в Admin API: проверяем и его, а не только
        # DSN с адресом, — иначе чужим ключом можно завести юзеров не туда.
        assert_test_project(dsn, supabase_url, service_key)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    await ensure_schema(_plain_dsn(dsn))
    await ensure_users(supabase_url, service_key, password)
    await ensure_real_tg_account(supabase_url, service_key)
    return 0


def _plain_dsn(value: str) -> str:
    """asyncpg не понимает префикс SQLAlchemy."""
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
