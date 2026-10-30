from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

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


class FakeTelegramSettingsStore:
    def __init__(self, stored: StoredTelegramSettings | None = None) -> None:
        self.stored = stored
        self.read_error: Exception | None = None
        self.save_error: Exception | None = None
        self.read_calls = 0
        self.saved: tuple[int, str, UUID] | None = None

    async def read_telegram_settings(self) -> StoredTelegramSettings | None:
        self.read_calls += 1
        if self.read_error is not None:
            raise self.read_error
        return self.stored

    async def save_telegram_settings(
        self,
        *,
        api_id: int,
        api_hash_ciphertext: str,
        actor_user_id: UUID,
    ) -> PublicTelegramSettings:
        if self.save_error is not None:
            raise self.save_error
        self.saved = (api_id, api_hash_ciphertext, actor_user_id)
        self.stored = StoredTelegramSettings(
            api_id=api_id,
            api_hash_ciphertext=SecretStr(api_hash_ciphertext),
            updated_at=datetime.now(UTC),
            updated_by=actor_user_id,
        )
        return PublicTelegramSettings(
            api_id=api_id,
            has_api_hash=True,
            source="database",
            updated_at=self.stored.updated_at,
            updated_by=actor_user_id,
        )


def _stored(api_id: int, api_hash: str, cipher: FernetSecretCipher) -> StoredTelegramSettings:
    return StoredTelegramSettings(
        api_id=api_id,
        api_hash_ciphertext=SecretStr(cipher.encrypt(api_hash)),
        updated_at=datetime.now(UTC),
        updated_by=uuid4(),
    )


def _provider(
    repository: FakeTelegramSettingsStore | None = None,
    cipher: FernetSecretCipher | None = None,
) -> TelegramAppSettings:
    return TelegramAppSettings(repository=repository, cipher=cipher)


@pytest.mark.asyncio
async def test_saved_pair_is_resolved_from_database() -> None:
    cipher = FernetSecretCipher(Fernet.generate_key().decode())
    repository = FakeTelegramSettingsStore(_stored(42, "database-hash", cipher))
    provider = _provider(repository, cipher)

    assert await provider.resolve() == (42, "database-hash")
    assert repository.read_calls == 1


@pytest.mark.asyncio
async def test_missing_database_row_is_unconfigured() -> None:
    cipher = FernetSecretCipher(Fernet.generate_key().decode())
    provider = _provider(FakeTelegramSettingsStore(), cipher)

    with pytest.raises(TelegramAppUnavailableError) as exc_info:
        await provider.resolve()

    assert "админ-панели" in str(exc_info.value)


@pytest.mark.asyncio
async def test_provider_without_repository_is_unconfigured() -> None:
    provider = _provider()

    with pytest.raises(TelegramAppUnavailableError):
        await provider.resolve()


@pytest.mark.asyncio
async def test_database_read_failure_is_reported_without_internal_details() -> None:
    repository = FakeTelegramSettingsStore()
    repository.read_error = AdminUnavailableError("private database details")
    provider = _provider(repository, FernetSecretCipher(Fernet.generate_key().decode()))

    with pytest.raises(TelegramAppUnavailableError) as exc_info:
        await provider.resolve()

    assert "private database details" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_decryption_failure_is_reported_without_leaking_values() -> None:
    repository = FakeTelegramSettingsStore(
        StoredTelegramSettings(
            api_id=42,
            api_hash_ciphertext=SecretStr("not-a-valid-fernet-token"),
            updated_at=datetime.now(UTC),
            updated_by=None,
        )
    )
    provider = _provider(repository, FernetSecretCipher(Fernet.generate_key().decode()))

    with pytest.raises(TelegramAppUnavailableError) as exc_info:
        await provider.resolve()

    assert "not-a-valid-fernet-token" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_status_shows_saved_hash_for_the_admin_form() -> None:
    api_hash = "database-secret-hash"
    cipher = FernetSecretCipher(Fernet.generate_key().decode())
    stored = _stored(42, api_hash, cipher)
    provider = _provider(FakeTelegramSettingsStore(stored), cipher)

    status = await provider.status()

    assert status.api_id == 42
    assert status.api_hash is not None
    assert status.api_hash.get_secret_value() == api_hash
    assert status.has_api_hash is True
    assert status.source == "database"
    assert status.updated_at == stored.updated_at
    assert status.updated_by == stored.updated_by
    assert api_hash not in repr(status)
    assert api_hash not in repr(status.model_dump())


@pytest.mark.asyncio
async def test_status_serializes_hash_only_in_json_response() -> None:
    api_hash = "database-secret-hash"
    cipher = FernetSecretCipher(Fernet.generate_key().decode())
    provider = _provider(FakeTelegramSettingsStore(_stored(42, api_hash, cipher)), cipher)

    status = await provider.status()

    assert status.model_dump(mode="json")["api_hash"] == api_hash


@pytest.mark.asyncio
async def test_status_without_cipher_keeps_hash_marker_but_hides_value() -> None:
    stored = StoredTelegramSettings(
        api_id=42,
        api_hash_ciphertext=SecretStr("ciphertext-without-key"),
        updated_at=datetime.now(UTC),
        updated_by=None,
    )
    provider = _provider(FakeTelegramSettingsStore(stored))

    status = await provider.status()

    assert status.api_id == 42
    assert status.api_hash is None
    assert status.has_api_hash is True
    assert status.source == "database"


@pytest.mark.asyncio
async def test_unconfigured_status_has_no_values() -> None:
    status = await _provider(FakeTelegramSettingsStore()).status()

    assert status.model_dump(mode="json") == {
        "api_id": None,
        "api_hash": None,
        "has_api_hash": False,
        "source": "unconfigured",
        "updated_at": None,
        "updated_by": None,
    }


@pytest.mark.asyncio
async def test_save_requires_a_cipher_and_a_repository_before_writing() -> None:
    actor_id = uuid4()
    repository = FakeTelegramSettingsStore()

    with pytest.raises(TelegramAppUnavailableError):
        await _provider(repository).save(
            api_id=42,
            api_hash=SecretStr("secret-hash"),
            actor_user_id=actor_id,
        )

    assert repository.saved is None


@pytest.mark.asyncio
async def test_save_encrypts_hash_and_returns_the_saved_value() -> None:
    actor_id = uuid4()
    raw_hash = "telegram-api-hash-value"
    cipher = FernetSecretCipher(Fernet.generate_key().decode())
    repository = FakeTelegramSettingsStore()
    provider = _provider(repository, cipher)

    status = await provider.save(
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
    assert status.api_id == 42
    assert status.has_api_hash is True
    assert status.source == "database"
    assert status.api_hash is not None
    assert status.api_hash.get_secret_value() == raw_hash
    assert raw_hash not in repr(status)
    assert await provider.resolve() == (42, raw_hash)


@pytest.mark.asyncio
async def test_save_failure_is_reported_without_internal_details() -> None:
    repository = FakeTelegramSettingsStore()
    repository.save_error = RuntimeError("private storage details")
    provider = _provider(repository, FernetSecretCipher(Fernet.generate_key().decode()))

    with pytest.raises(TelegramAppUnavailableError) as exc_info:
        await provider.save(
            api_id=42,
            api_hash=SecretStr("secret-hash"),
            actor_user_id=uuid4(),
        )

    assert "private storage details" not in str(exc_info.value)


def test_public_settings_repr_and_python_dump_mask_the_hash() -> None:
    settings = PublicTelegramSettings(
        api_id=42,
        api_hash=SecretStr("secret-hash"),
        has_api_hash=True,
        source="database",
        updated_at=None,
        updated_by=None,
    )

    assert "secret-hash" not in repr(settings)
    dumped: dict[str, Any] = settings.model_dump()
    assert isinstance(dumped["api_hash"], SecretStr)
    assert "secret-hash" not in repr(dumped)
