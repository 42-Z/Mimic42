from __future__ import annotations

from uuid import uuid4

import pytest

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.agent_store import InMemoryAgentStore
from mimic42.core.onboarding import (
    AgentOnboardingService,
    InMemoryOnboardingRepository,
    OnboardingNotFoundError,
    OnboardingOwnershipError,
    OnboardingSession,
    TelegramAuthorizationIncompleteError,
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


@pytest.mark.asyncio
async def test_rebind_to_agent_updates_store_and_deletes_session() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="new-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="new-session-string",
        )
    )
    store = InMemoryAgentStore()
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="old-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="old-session-string",
            name="Mimic",
            soul_prompt="Short calm replies",
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
        agent_store=store,
    )

    result = await service.rebind_to_agent(onboarding_id, agent_id, owner_id=owner_id)

    assert result.agent_id == agent_id
    assert result.state is AgentRuntimeState.STOPPED
    config = await store.get_runtime_config(agent_id)
    assert config.telegram_session_string == "new-session-string"
    assert config.telegram_api_hash == "new-hash"
    assert config.name == "Mimic"
    assert config.soul_prompt == "Short calm replies"
    with pytest.raises(OnboardingNotFoundError):
        await repository.get(onboarding_id)


@pytest.mark.asyncio
async def test_rebind_to_agent_requires_authorized_session() -> None:
    owner_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.CODE_REQUESTED,
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
        agent_store=InMemoryAgentStore(),
    )

    with pytest.raises(TelegramAuthorizationIncompleteError):
        await service.rebind_to_agent(onboarding_id, uuid4(), owner_id=owner_id)


@pytest.mark.asyncio
async def test_rebind_to_agent_rejects_foreign_owner() -> None:
    owner_id = uuid4()
    other_id = uuid4()
    agent_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=other_id,
            api_id=12345,
            api_hash_secret="new-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="new-session-string",
        )
    )
    store = InMemoryAgentStore()
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=other_id,
            api_id=12345,
            api_hash_secret="old-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="old-session-string",
            name="Mimic",
            soul_prompt="Short calm replies",
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
        agent_store=store,
    )

    with pytest.raises(OnboardingOwnershipError):
        await service.rebind_to_agent(onboarding_id, agent_id, owner_id=owner_id)

    config = await store.get_runtime_config(agent_id)
    assert config.telegram_session_string == "old-session-string"
    assert config.telegram_api_hash == "old-hash"
    saved = await repository.get(onboarding_id)
    assert saved.completed_agent_id is None


@pytest.mark.asyncio
async def test_rebind_to_agent_requires_agent_store() -> None:
    owner_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="new-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="new-session-string",
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
    )

    with pytest.raises(RuntimeError):
        await service.rebind_to_agent(onboarding_id, uuid4(), owner_id=owner_id)


@pytest.mark.asyncio
async def test_rebind_to_agent_keeps_session_on_unknown_agent() -> None:
    owner_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="new-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="new-session-string",
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
        agent_store=InMemoryAgentStore(),
    )

    with pytest.raises(KeyError):
        await service.rebind_to_agent(onboarding_id, uuid4(), owner_id=owner_id)

    saved = await repository.get(onboarding_id)
    assert saved.completed_agent_id is None
