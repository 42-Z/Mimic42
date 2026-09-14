from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.onboarding import OnboardingNotFoundError, OnboardingSession, TelegramLoginStatus
from mimic42.integrations.database_onboarding import DatabaseOnboardingRepository
from mimic42.testing.slots import Slot


async def test_database_onboarding_repository_maps_session_rows(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    repository = DatabaseOnboardingRepository(db_session_factory)
    session = OnboardingSession(
        onboarding_id=uuid4(),
        owner_id=clean_slot.persona("code").user_id,
        api_id=12345,
        api_hash_secret="encrypted-hash",
        phone_number="+79990000000",
        authorization_status=TelegramLoginStatus.CODE_REQUESTED,
        phone_code_hash_secret="encrypted-code-hash",
        session_secret="encrypted-session",
    )

    await repository.save(session)
    loaded = await repository.get(session.onboarding_id)

    assert loaded == session


async def test_database_onboarding_repository_raises_when_missing(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = DatabaseOnboardingRepository(db_session_factory)

    with pytest.raises(OnboardingNotFoundError):
        await repository.get(uuid4())
