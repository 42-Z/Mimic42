from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.onboarding import (
    AgentOnboardingService,
    AgentProfileInput,
    OnboardingNotFoundError,
    OnboardingSession,
    TelegramLoginStatus,
)
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.integrations.database_onboarding import DatabaseOnboardingRepository
from mimic42.testing.slots import Slot
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramAuthClientFactory


async def test_rebind_after_wizard_finalize_does_not_conflict_with_unique_marker(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("flow").user_id
    agent_id = uuid4()
    repository = DatabaseOnboardingRepository(db_session_factory)
    store = DatabaseAgentStore(db_session_factory)
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
        agent_store=store,
    )

    # Мастер: черновик с id == agent_id, финализация ставит completed_agent_id = agent_id
    await repository.save(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="wizard-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="wizard-session",
            name="Mimic",
            soul_prompt="Soul",
        )
    )
    await service.finalize_agent(agent_id, AgentProfileInput(name="Mimic", soul_prompt="Soul"))

    # Перепривязка: новая сессия
    rebind_id = uuid4()
    await repository.save(
        OnboardingSession(
            onboarding_id=rebind_id,
            owner_id=owner_id,
            api_id=777,
            api_hash_secret="new-hash",
            phone_number="+79990000001",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="new-session",
        )
    )
    await service.rebind_to_agent(rebind_id, agent_id, owner_id=owner_id)

    config = await store.get_runtime_config(agent_id)
    assert config.telegram_api_id == 777
    assert config.telegram_session_string == "new-session"
    assert config.name == "Mimic"
    assert config.soul_prompt == "Soul"

    with pytest.raises(OnboardingNotFoundError):
        await repository.get(rebind_id)

    wizard_row = await repository.get(agent_id)
    assert wizard_row.completed_agent_id == agent_id
