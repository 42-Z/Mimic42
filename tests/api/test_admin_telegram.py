from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from mimic42.api.app import create_app
from mimic42.config import Settings
from mimic42.core.admin import (
    AdminRepository,
    StoredTelegramSettings,
)
from mimic42.core.crypto import FernetSecretCipher
from mimic42.core.telegram_app_settings import TelegramAppSettings
from tests.api.admin_fakes import FakeAdminRepository
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier


def _settings(*, secret_key: str | None = None) -> Settings:
    return Settings(
        database_connection_string=None,
        mem0_api_key=None,
        braintrust_api_key=None,
        supabase_url=None,
        supabase_service_key=None,
        secret_key=secret_key,
    )


def _app(
    admin_id: UUID,
    repository: FakeAdminRepository,
    *,
    settings: Settings | None = None,
) -> FastAPI:
    app_settings = settings or _settings()
    cipher = (
        FernetSecretCipher(app_settings.secret_key) if app_settings.secret_key is not None else None
    )
    provider = TelegramAppSettings(
        repository=cast(AdminRepository, repository),
        cipher=cipher,
    )
    return create_app(
        admin_repository=cast(AdminRepository, repository),
        auth_verifier=FakeAuthVerifier(admin_id),
        settings=app_settings,
        telegram_app_settings=provider,
    )


@pytest.mark.asyncio
async def test_get_shows_saved_pair_for_the_admin_form_and_disables_caching() -> None:
    admin_id = uuid4()
    api_hash = "database-secret-hash"
    key = Fernet.generate_key().decode()
    cipher = FernetSecretCipher(key)
    repository = FakeAdminRepository(
        admin_ids={admin_id},
        telegram_settings=StoredTelegramSettings(
            api_id=42,
            api_hash_ciphertext=SecretStr(cipher.encrypt(api_hash)),
            updated_at=datetime.now(UTC),
            updated_by=admin_id,
        ),
    )
    app = _app(admin_id, repository, settings=_settings(secret_key=key))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/admin/telegram-settings", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    stored = repository.telegram_settings
    assert stored is not None
    assert result["api_id"] == 42
    assert result["api_hash"] == api_hash
    assert result["has_api_hash"] is True
    assert result["source"] == "database"
    assert set(result) == {
        "api_id",
        "api_hash",
        "has_api_hash",
        "source",
        "updated_at",
        "updated_by",
    }
    assert datetime.fromisoformat(result["updated_at"].replace("Z", "+00:00")) == (
        stored.updated_at
    )
    assert result["updated_by"] == str(admin_id)
    assert stored.api_hash_ciphertext.get_secret_value() not in response.text


@pytest.mark.asyncio
async def test_put_without_secret_key_returns_503_without_writing() -> None:
    admin_id = uuid4()
    api_hash = "submitted-api-hash"
    repository = FakeAdminRepository(admin_ids={admin_id})
    app = _app(admin_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            "/api/v1/admin/telegram-settings",
            headers=AUTH_HEADERS,
            json={"api_id": 4242, "api_hash": api_hash},
        )

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert api_hash not in response.text
    assert repository.telegram_write_count == 0
    assert not any(call[0] == "save" for call in repository.telegram_calls)


@pytest.mark.asyncio
async def test_invalid_requests_do_not_echo_hashes_or_log_request_bodies(
    caplog: pytest.LogCaptureFixture,
) -> None:
    admin_id = uuid4()
    api_hash = "highly-sensitive-invalid-hash"
    repository = FakeAdminRepository(admin_ids={admin_id})
    app = _app(admin_id, repository, settings=_settings(secret_key=Fernet.generate_key().decode()))
    invalid_json = f'{{"api_id":42,"api_hash":"{api_hash}","unexpected":]}}'

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid_id = await client.put(
            "/api/v1/admin/telegram-settings",
            headers=AUTH_HEADERS,
            json={"api_id": 0, "api_hash": api_hash},
        )
        extra_field = await client.put(
            "/api/v1/admin/telegram-settings",
            headers=AUTH_HEADERS,
            json={"api_id": 42, "api_hash": api_hash, "unexpected": "private"},
        )
        malformed = await client.put(
            "/api/v1/admin/telegram-settings",
            headers={**AUTH_HEADERS, "content-type": "application/json"},
            content=invalid_json,
        )

    for response in (invalid_id, extra_field, malformed):
        assert response.status_code == 422
        assert response.headers["cache-control"] == "no-store"
        assert api_hash not in response.text

    assert repository.telegram_write_count == 0
    assert api_hash not in caplog.text
    assert invalid_id.json() == {"detail": "Проверьте поля запроса"}


@pytest.mark.asyncio
async def test_put_encrypts_secret_and_returns_the_saved_value() -> None:
    admin_id = uuid4()
    api_hash = "replacement-private-hash"
    key = Fernet.generate_key().decode()
    cipher = FernetSecretCipher(key)
    repository = FakeAdminRepository(admin_ids={admin_id})
    app = _app(admin_id, repository, settings=_settings(secret_key=key))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            "/api/v1/admin/telegram-settings",
            headers=AUTH_HEADERS,
            json={"api_id": 4242, "api_hash": api_hash},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["api_id"] == 4242
    assert response.json()["api_hash"] == api_hash
    assert response.json()["has_api_hash"] is True
    assert response.json()["source"] == "database"
    stored = repository.telegram_settings
    assert stored is not None
    ciphertext = stored.api_hash_ciphertext.get_secret_value()
    assert ciphertext != api_hash
    assert cipher.decrypt(ciphertext) == api_hash
    assert repository.telegram_write_count == 1
    assert repository.telegram_calls[-1][1]["actor_user_id"] == admin_id


@pytest.mark.asyncio
async def test_me_response_is_never_cached() -> None:
    admin_id = uuid4()
    repository = FakeAdminRepository(admin_ids={admin_id})
    app = _app(admin_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/me", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
