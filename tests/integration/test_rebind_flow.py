from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.onboarding import (
    AgentOnboardingService,
    AgentProfileInput,
    OnboardingSession,
    TelegramCodeVerification,
    TelegramCredentials,
    TelegramLoginStatus,
)
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.integrations.database_onboarding import DatabaseOnboardingRepository
from mimic42.testing.slots import Slot
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramAuthClientFactory


async def test_rebind_reuses_wizard_row_and_does_not_conflict_with_unique_marker(
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

    # Перепривязка переиспользует строку мастера — UNIQUE-конфликта нет
    status = await service.start_rebind(
        agent_id,
        TelegramCredentials(
            owner_id=owner_id,
            api_id=777,
            api_hash="new-hash",
            phone_number="+79990000001",
        ),
    )
    assert status.onboarding_id == agent_id
    assert status.authorization_status is TelegramLoginStatus.CODE_REQUESTED

    verified = await service.verify_telegram_code(agent_id, TelegramCodeVerification(code="12345"))
    assert verified.authorization_status is TelegramLoginStatus.AUTHORIZED

    result = await service.rebind_to_agent(agent_id, agent_id, owner_id=owner_id)
    assert result.state is AgentRuntimeState.STOPPED

    config = await store.get_runtime_config(agent_id)
    assert config.telegram_api_id == 777
    assert config.telegram_session_string == "fake-session:+79990000001"
    assert config.name == "Mimic"
    assert config.soul_prompt == "Soul"

    # Строка мастера осталась на месте и по-прежнему скрыта от мастера
    wizard_row = await repository.get(agent_id)
    assert wizard_row.completed_agent_id == agent_id
    assert wizard_row.authorization_status is TelegramLoginStatus.AUTHORIZED


async def test_start_rebind_hides_new_row_for_agent_without_onboarding_session(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("code").user_id
    agent_id = uuid4()
    repository = DatabaseOnboardingRepository(db_session_factory)
    store = DatabaseAgentStore(db_session_factory)
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
        agent_store=store,
    )

    # Агент создан через API: онбординг-строки у него нет
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="api-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="api-session",
            name="Mimic",
            soul_prompt="Soul",
        )
    )
    credentials = TelegramCredentials(
        owner_id=owner_id,
        api_id=777,
        api_hash="new-hash",
        phone_number="+79990000001",
    )

    first = await service.start_rebind(agent_id, credentials)

    assert first.onboarding_id != agent_id
    row = await repository.get(first.onboarding_id)
    assert row.completed_agent_id == agent_id

    # Повторный старт переиспользует скрытую строку, а не заводит вторую
    second = await service.start_rebind(agent_id, credentials)

    assert second.onboarding_id == first.onboarding_id
