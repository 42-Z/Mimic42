from __future__ import annotations

from uuid import uuid4

import pytest

from mimic42.core.onboarding import (
    AgentOnboardingService,
    InMemoryOnboardingRepository,
    OnboardingOwnershipError,
    OnboardingSession,
    TelegramCredentials,
    TelegramLoginStatus,
)
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramAuthClientFactory


def _fake_telegram_factory() -> FakeTelegramAuthClientFactory:
    return FakeTelegramAuthClientFactory(FakeTelegramAccount())


@pytest.mark.asyncio
async def test_request_code_reuses_onboarding_id_and_preserves_profile() -> None:
    owner_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.NOT_STARTED,
            name="Mimic",
            soul_prompt="Short calm replies",
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
    )

    status = await service.request_telegram_code(
        TelegramCredentials(
            owner_id=owner_id,
            api_id=12345,
            api_hash="api-hash",
            phone_number="+79990000000",
        ),
        onboarding_id=onboarding_id,
    )

    assert status.onboarding_id == onboarding_id
    preserved = await repository.get(onboarding_id)
    assert preserved.name == "Mimic"
    assert preserved.soul_prompt == "Short calm replies"
    assert preserved.authorization_status is TelegramLoginStatus.CODE_REQUESTED


@pytest.mark.asyncio
async def test_request_code_rejects_cross_owner_onboarding_id() -> None:
    owner_id = uuid4()
    other_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=other_id,
            authorization_status=TelegramLoginStatus.NOT_STARTED,
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
    )

    with pytest.raises(OnboardingOwnershipError):
        await service.request_telegram_code(
            TelegramCredentials(
                owner_id=owner_id,
                api_id=12345,
                api_hash="api-hash",
                phone_number="+79990000000",
            ),
            onboarding_id=onboarding_id,
        )
