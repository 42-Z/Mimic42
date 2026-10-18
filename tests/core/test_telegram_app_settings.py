from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from mimic42.config import Settings
from mimic42.core.admin import (
    AdminUnavailableError,
    PublicTelegramSettings,
    StoredTelegramSettings,
)
from mimic42.core.crypto import FernetSecretCipher
from mimic42.core.telegram_app_settings import (
    TelegramAppSettings,
    TelegramAppUnavailableError,
)

if TYPE_CHECKING:
    from mimic42.core.admin import AdminRepository


class FakeTelegramSettingsRepository:
    def __init__(self, stored: StoredTelegramSettings | None = None) -> None:
        self.stored = stored
        self.status_value: PublicTelegramSettings | None = None
        self.read_error: Exception | None = None
        self.status_error: Exception | None = None
        self.read_calls = 0
        self.status_calls = 0
        self.saved: tuple[int, str, Any] | None = None

    async def read_telegram_settings(self) -> StoredTelegramSettings | None:
        self.read_calls += 1
        if self.read_error is not None:
            raise self.read_error
        return self.stored

    async def read_telegram_settings_status(self) -> PublicTelegramSettings | None:
        self.status_calls += 1
        if self.status_error is not None:
            raise self.status_error
        if self.status_value is not None:
            return self.status_value
        if self.stored is None:
            return None
        return PublicTelegramSettings(
            api_id=self.stored.api_id,
            has_api_hash=True,
            source="database",
            updated_at=self.stored.updated_at,
            updated_by=self.stored.updated_by,
        )

    async def save_telegram_settings(
        self,
        *,
        api_id: int,
        api_hash_ciphertext: str,
        actor_user_id: UUID,
    ) -> PublicTelegramSettings:
        self.saved = (api_id, api_hash_ciphertext, actor_user_id)
        self.stored = StoredTelegramSettings(
            api_id=api_id,
            api_hash_ciphertext=SecretStr(api_hash_ciphertext),
            updated_at=datetime.now(UTC),
            updated_by=actor_user_id,
        )
        self.status_value = None
        status = await self.read_telegram_settings_status()
        assert status is not None
        return status


def _settings(
    *,
    api_id: int | None = None,
    api_hash: str | None = None,
    secret_key: str | None = None,
) -> Settings:
    return Settings(
        database_connection_string=None,
        mem0_api_key=None,
        braintrust_api_key=None,
        telegram_api_id=api_id,
        telegram_api_hash=api_hash,
        secret_key=secret_key,
    )


def _provider(
    settings: Settings,
    repository: FakeTelegramSettingsRepository | None = None,
    cipher: FernetSecretCipher | None = None,
) -> TelegramAppSettings:
    return TelegramAppSettings(
        settings=settings,
        repository=cast("AdminRepository | None", repository),
        cipher=cipher,
    )


@pytest.mark.asyncio
async def test_missing_database_row_falls_back_to_environment() -> None:
    repository = FakeTelegramSettingsRepository()
    provider = _provider(
        _settings(api_id=777, api_hash="environment-hash"),
        repository,
    )

    assert await provider.resolve(None, None) == (777, "environment-hash")
    assert repository.read_calls == 1


@pytest.mark.asyncio
async def test_without_database_repository_provider_uses_environment_only() -> None:
    provider = _provider(_settings(api_id=777, api_hash="environment-hash"))

    assert await provider.resolve(None, None) == (777, "environment-hash")


@pytest.mark.asyncio
async def test_saved_pair_precedes_environment_and_partial_inputs_override_one_field() -> None:
    key = Fernet.generate_key().decode()
    cipher = FernetSecretCipher(key)
    repository = FakeTelegramSettingsRepository(
        StoredTelegramSettings(
            api_id=42,
            api_hash_ciphertext=SecretStr(cipher.encrypt("database-hash")),
            updated_at=datetime.now(UTC),
            updated_by=uuid4(),
        )
    )
    provider = _provider(
        _settings(api_id=777, api_hash="environment-hash"),
        repository,
        cipher,
    )

    assert await provider.resolve(None, None) == (42, "database-hash")
    assert await provider.resolve(99, None) == (99, "database-hash")
    assert await provider.resolve(None, "explicit-hash") == (42, "explicit-hash")


@pytest.mark.asyncio
async def test_complete_explicit_pair_does_not_read_database() -> None:
    repository = FakeTelegramSettingsRepository()
    repository.read_error = RuntimeError("database unavailable")
    provider = _provider(_settings(), repository)

    assert await provider.resolve(123, "explicit-hash") == (123, "explicit-hash")
    assert repository.read_calls == 0


@pytest.mark.asyncio
async def test_database_read_failure_never_falls_back_to_environment() -> None:
    repository = FakeTelegramSettingsRepository()
    repository.read_error = AdminUnavailableError("private database details")
    provider = _provider(_settings(api_id=777, api_hash="environment-hash"), repository)

    with pytest.raises(TelegramAppUnavailableError) as exc_info:
        await provider.resolve(None, None)

    assert "environment-hash" not in str(exc_info.value)
    assert "private database details" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_decryption_failure_never_falls_back_to_environment() -> None:
    repository = FakeTelegramSettingsRepository(
        StoredTelegramSettings(
            api_id=42,
            api_hash_ciphertext=SecretStr("not-a-valid-fernet-token"),
            updated_at=datetime.now(UTC),
            updated_by=None,
        )
    )
    provider = _provider(
        _settings(api_id=777, api_hash="environment-hash"),
        repository,
        FernetSecretCipher(Fernet.generate_key().decode()),
    )

    with pytest.raises(TelegramAppUnavailableError) as exc_info:
        await provider.resolve(None, None)

    assert "environment-hash" not in str(exc_info.value)
    assert "not-a-valid-fernet-token" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_status_is_public_and_does_not_decrypt_database_value() -> None:
    repository = FakeTelegramSettingsRepository(
        StoredTelegramSettings(
            api_id=42,
            api_hash_ciphertext=SecretStr("not-a-valid-fernet-token"),
            updated_at=datetime.now(UTC),
            updated_by=uuid4(),
        )
    )
    provider = _provider(_settings(), repository, cipher=None)

    status = await provider.status()

    assert status.api_id == 42
    assert status.has_api_hash is True
    assert status.source == "database"
    assert "api_hash" not in status.model_dump()
    assert "ciphertext" not in status.model_dump()
    assert "not-a-valid-fernet-token" not in repr(status)
    assert repository.stored is not None
    assert "not-a-valid-fernet-token" not in repr(repository.stored)
    assert repository.read_calls == 0
    assert repository.status_calls == 1


@pytest.mark.asyncio
async def test_environment_status_and_unconfigured_status_are_distinct() -> None:
    environment = await _provider(_settings(api_id=777, api_hash="environment-hash")).status()
    unconfigured = await _provider(_settings()).status()

    assert environment.model_dump() == {
        "api_id": 777,
        "has_api_hash": True,
        "source": "environment",
        "updated_at": None,
        "updated_by": None,
    }
    assert unconfigured.source == "unconfigured"
    assert unconfigured.has_api_hash is False


@pytest.mark.asyncio
async def test_save_requires_a_cipher_and_a_repository_before_writing() -> None:
    actor_id = uuid4()
    repository = FakeTelegramSettingsRepository()
    provider = _provider(_settings(), repository, cipher=None)

    with pytest.raises(TelegramAppUnavailableError):
        await provider.save(api_id=42, api_hash=SecretStr("secret-hash"), actor_user_id=actor_id)

    assert repository.saved is None


@pytest.mark.asyncio
async def test_save_encrypts_hash_and_returns_only_public_status() -> None:
    actor_id = uuid4()
    raw_hash = "telegram-api-hash-value"
    key = Fernet.generate_key().decode()
    cipher = FernetSecretCipher(key)
    repository = FakeTelegramSettingsRepository()
    provider = _provider(_settings(secret_key=key), repository, cipher)

    public_status = await provider.save(
        api_id=42,
        api_hash=SecretStr(raw_hash),
        actor_user_id=actor_id,
    )

    assert repository.saved is not None
    saved_api_id, ciphertext, saved_actor_id = repository.saved
    assert saved_api_id == 42
    assert saved_actor_id == actor_id
    assert ciphertext != raw_hash
    assert cipher.decrypt(ciphertext) == raw_hash
    assert public_status.api_id == 42
    assert public_status.has_api_hash is True
    assert "api_hash" not in public_status.model_dump()
    assert raw_hash not in public_status.model_dump_json()
    assert await provider.resolve(None, None) == (42, raw_hash)
