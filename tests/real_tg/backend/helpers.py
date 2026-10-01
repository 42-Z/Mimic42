"""Помощники реальных TG-тестов бэкенда: настройки, логин, owner id и поиск агентов."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx
import jwt as pyjwt

from mimic42.config import Settings
from mimic42.core.model_catalog import DEFAULT_LLM_MODEL, resolve_model_chain
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


async def ensure_free_model(dsn: str, agent_id: str) -> None:
    """Тестовый мимик обязан работать на бесплатной модели.

    Реальные прогоны не должны жечь платные токены; проверка с понятным
    сообщением вместо тихой траты денег.
    """
    conn = await asyncpg.connect(plain_dsn(dsn))
    try:
        row = await conn.fetchrow(
            "select settings->>'model' as model from agents where id = $1::uuid",
            agent_id,
        )
    finally:
        await conn.close()
    model = (row["model"] if row else None) or DEFAULT_LLM_MODEL
    chain = resolve_model_chain(model)
    if not chain[0].endswith(":free"):
        raise AssertionError(
            f"У мимика {agent_id} выбрана модель {model!r} без бесплатного варианта: "
            "открой настройки агента и выбери Ling 3.0 Flash VL"
        )


def real_app_settings() -> Settings:
    """Настройки настоящего приложения real_tg: боевой .env поверх тестовых заглушек.

    real_tg работает с боевой конфигурацией (.env грузится поверх тестовых
    переопределений), но внешние сервисы, которые тестам не нужны, выключаются
    явно — иначе Settings() подхватил бы боевые ключи разработчика.
    """
    return Settings(
        database_connection_string=os.environ["DATABASE_CONNECTION_STRING"],
        supabase_url=os.environ["SUPABASE_URL"],
        secret_key=os.environ["SECRET_KEY"],
        telegram_api_id=int(os.environ["TELEGRAM_API_ID"]),
        telegram_api_hash=os.environ["TELEGRAM_API_HASH"],
        mem0_api_key=None,  # Mem0 в тестах не дёргаем
        braintrust_api_key=None,  # и в Braintrust тесты не пишут
        restore_running_agents=False,  # чужие RUNNING-агенты не поднимаем
    )


async def disable_auto_restore(dsn: str, owner_id: UUID) -> None:
    """Тестовые мимики — инфраструктура тестов: обычный запуск бэкенда их не
    поднимает, иначе их сессии конфликтуют с прогоном этих же тестов."""
    conn = await asyncpg.connect(plain_dsn(dsn))
    try:
        await conn.execute(
            "update agents set restore_on_start = false where owner_id = $1 and restore_on_start",
            owner_id,
        )
    finally:
        await conn.close()


class MemoryMediaStorage:
    """MediaUploader в памяти: настоящий Telegram, но без зависимости от Storage.

    Без SUPABASE_SERVICE_ROLE_KEY SupabaseMediaStorage не строится, но
    сценарий issue #98 должен оставаться доступным в живом тесте.
    """

    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}

    async def upload(
        self,
        *,
        agent_id: UUID,
        filename: str,
        data: bytes,
        mime_type: str,
        kind: str = "doc",
    ) -> Any:
        from mimic42.core.media import MediaFile, safe_filename

        if not data:
            return None
        name = safe_filename(filename)
        # uuid4 — как в SupabaseMediaStorage: две загрузки с одним именем
        # не должны затирать байты друг друга.
        path = f"{agent_id}/{uuid4()}/{name}"
        self._files[path] = bytes(data)
        return MediaFile(
            kind=kind, name=name, mime_type=mime_type, size=len(data), storage_path=path
        )

    async def open(self, path: str) -> bytes | None:
        return self._files.get(path)

    async def remove_prefix(self, agent_id: UUID) -> None:
        prefix = f"{agent_id}/"
        for key in [key for key in self._files if key.startswith(prefix)]:
            del self._files[key]


def media_storage() -> Any:
    """Настоящий Supabase Storage при наличии ключа, иначе хранилище в памяти."""
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if service_key:
        from mimic42.integrations.supabase_media import SupabaseMediaStorage

        return SupabaseMediaStorage(
            supabase_url=os.environ["SUPABASE_URL"], service_key=service_key
        )
    return MemoryMediaStorage()
