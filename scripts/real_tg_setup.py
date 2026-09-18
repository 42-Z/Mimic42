"""Регистрирует выделенный аккаунт сайта для реальных TG-тестов.

    uv run python scripts/real_tg_setup.py

TEST_ACCOUNT_EMAIL/PASSWORD читаются из .env/.env.test, сервисный ключ — из
SUPABASE_SERVICE_ROLE_KEY в .env (или явного TEST_SUPABASE_SERVICE_ROLE_KEY).
Идемпотентен: существующий пользователь не трогается. Id аккаунта нигде не
фиксируется — тесты берут owner_id из claim `sub` своего JWT после логина.
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx

from mimic42.testing.env import load_test_env
from mimic42.testing.slots import assert_test_project


async def main() -> int:
    load_test_env()
    supabase_url = os.environ["SUPABASE_URL"]
    dsn = os.environ["DATABASE_CONNECTION_STRING"]
    email = os.environ["TEST_ACCOUNT_EMAIL"]
    password = os.environ["TEST_ACCOUNT_PASSWORD"]
    # Приложенческий service-ключ уже лежит в .env (он же нужен медиа-стораджу);
    # TEST_SUPABASE_SERVICE_ROLE_KEY остаётся явным оверрайдом для CI и разовых
    # запусков, где .env недоступен.
    service_key = os.environ.get("TEST_SUPABASE_SERVICE_ROLE_KEY") or os.environ.get(
        "SUPABASE_SERVICE_ROLE_KEY", ""
    )
    if not service_key:
        raise SystemExit(
            "Сервисный ключ не найден: заполни SUPABASE_SERVICE_ROLE_KEY в .env "
            "или передай TEST_SUPABASE_SERVICE_ROLE_KEY явно."
        )
    try:
        # service_key сразу пойдёт в Admin API: проверяем и его, — иначе чужим
        # ключом можно завести аккаунт не в тот проект.
        assert_test_project(dsn, supabase_url, service_key)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=supabase_url.rstrip("/"), timeout=30.0) as client:
        response = await client.post(
            "/auth/v1/admin/users",
            headers=headers,
            json={
                "email": email,
                "password": password,
                "email_confirm": True,
            },
        )
        if response.status_code in (200, 201):
            print(f"создан {email}")
        elif response.status_code in (409, 422):
            print(f"уже есть {email}")
        else:
            print(f"не удалось создать: {response.status_code} {response.text}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
