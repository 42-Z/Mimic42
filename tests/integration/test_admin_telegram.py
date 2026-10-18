from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from mimic42.core.admin import AdminUnavailableError
from mimic42.core.crypto import FernetSecretCipher
from mimic42.integrations.database_admin import DatabaseAdminRepository
from mimic42.integrations.database_models import AdminAuditLogModel, PlatformTelegramSettingsModel
from mimic42.testing.slots import Slot


async def _settings_row_count(session_factory: async_sessionmaker[Any]) -> int:
    async with session_factory() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(PlatformTelegramSettingsModel)
                .where(PlatformTelegramSettingsModel.id == 1)
            )
            or 0
        )


async def _audit_count(
    session_factory: async_sessionmaker[Any],
    actor_id: UUID,
) -> int:
    async with session_factory() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(AdminAuditLogModel)
                .where(
                    AdminAuditLogModel.actor_user_id == actor_id,
                    AdminAuditLogModel.action == "telegram.settings_updated",
                )
            )
            or 0
        )


@pytest.mark.asyncio
async def test_telegram_settings_upsert_encrypts_hash_and_audits_atomically(
    admin_db_factory: async_sessionmaker[Any],
    test_slot: Slot,
) -> None:
    repository = DatabaseAdminRepository(admin_db_factory)
    actor_id = test_slot.persona("full").user_id
    raw_hash = "integration-secret-telegram-hash"
    cipher = FernetSecretCipher(Fernet.generate_key().decode())
    ciphertext = cipher.encrypt(raw_hash)
    replacement_hash = "integration-secret-telegram-hash-replaced"
    replacement_ciphertext = cipher.encrypt(replacement_hash)
    prior_audit_count = await _audit_count(admin_db_factory, actor_id)

    insert_result = await repository.save_telegram_settings(
        api_id=4242,
        api_hash_ciphertext=ciphertext,
        actor_user_id=actor_id,
    )
    result = await repository.save_telegram_settings(
        api_id=5252,
        api_hash_ciphertext=replacement_ciphertext,
        actor_user_id=actor_id,
    )

    stored = await repository.read_telegram_settings()
    public_status = await repository.read_telegram_settings_status()
    async with admin_db_factory() as session:
        audit = await session.scalar(
            select(AdminAuditLogModel)
            .where(
                AdminAuditLogModel.actor_user_id == actor_id,
                AdminAuditLogModel.action == "telegram.settings_updated",
            )
            .order_by(AdminAuditLogModel.created_at.desc(), AdminAuditLogModel.id.desc())
        )

    assert insert_result.api_id == 4242
    assert result.api_id == 5252
    assert result.has_api_hash is True
    assert result.source == "database"
    assert stored is not None
    assert stored.api_id == 5252
    assert stored.api_hash_ciphertext.get_secret_value() == replacement_ciphertext
    assert cipher.decrypt(stored.api_hash_ciphertext.get_secret_value()) == replacement_hash
    assert public_status is not None
    assert public_status.api_id == 5252
    assert public_status.has_api_hash is True
    assert set(public_status.model_dump()) == {
        "api_id",
        "has_api_hash",
        "source",
        "updated_at",
        "updated_by",
    }
    assert await _settings_row_count(admin_db_factory) == 1
    assert await _audit_count(admin_db_factory, actor_id) == prior_audit_count + 2
    assert audit is not None
    assert audit.object_type == "telegram_settings"
    assert audit.object_id is None
    assert audit.metadata_ == {"credentials_replaced": True}
    assert raw_hash not in repr(audit.metadata_)
    assert ciphertext not in repr(audit.metadata_)
    assert replacement_hash not in repr(audit.metadata_)
    assert replacement_ciphertext not in repr(audit.metadata_)


@pytest.mark.asyncio
async def test_telegram_settings_audit_failure_rolls_back_the_upsert(
    admin_db_factory: async_sessionmaker[Any],
    test_slot: Slot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = DatabaseAdminRepository(admin_db_factory)
    actor_id = test_slot.persona("full").user_id
    before = await repository.read_telegram_settings()
    prior_audit_count = await _audit_count(admin_db_factory, actor_id)

    async def fail_audit(*_args: Any, **_kwargs: Any) -> None:
        raise AdminUnavailableError("synthetic audit failure")

    monkeypatch.setattr(DatabaseAdminRepository, "_append_audit", staticmethod(fail_audit))

    with pytest.raises(AdminUnavailableError, match="synthetic audit failure"):
        await repository.save_telegram_settings(
            api_id=9876,
            api_hash_ciphertext="ciphertext-that-must-not-be-saved",
            actor_user_id=actor_id,
        )

    after = await repository.read_telegram_settings()

    before_value = (
        (before.api_id, before.api_hash_ciphertext.get_secret_value())
        if before is not None
        else None
    )
    after_value = (
        (after.api_id, after.api_hash_ciphertext.get_secret_value()) if after is not None else None
    )
    assert after_value == before_value
    assert await _audit_count(admin_db_factory, actor_id) == prior_audit_count
