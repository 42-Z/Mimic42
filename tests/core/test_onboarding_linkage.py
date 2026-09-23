from __future__ import annotations

from uuid import uuid4

import pytest

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.agent_store import InMemoryAgentStore
from mimic42.core.onboarding import (
    AgentOnboardingService,
    InMemoryOnboardingRepository,
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
async def test_request_code_rejects_completed_onboarding_id() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="old-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="old-session",
            completed_agent_id=agent_id,
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
    )

    with pytest.raises(ValueError, match="завершен"):
        await service.request_telegram_code(
            TelegramCredentials(
                owner_id=owner_id,
                api_id=777,
                api_hash="different-hash",
                phone_number="+79991111111",
            ),
            onboarding_id=agent_id,
        )

    unchanged = await repository.get(agent_id)
    assert unchanged.phone_number == "+79990000000"
    assert unchanged.api_id == 12345
    assert unchanged.session_secret == "old-session"


@pytest.mark.asyncio
async def test_start_rebind_reuses_stored_account() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    account = FakeTelegramAccount()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=111,
            api_hash_secret="old-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="old-session",
            name="Mimic",
            soul_prompt="Short calm replies",
            completed_agent_id=agent_id,
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(account),
    )

    status = await service.start_rebind(agent_id, owner_id=owner_id)

    assert status.onboarding_id == agent_id
    assert status.authorization_status is TelegramLoginStatus.CODE_REQUESTED
    assert status.phone_number == "+79990000000"
    # Код уходит на сохранённый номер, приложение тоже берётся из строки.
    assert account.phone == "+79990000000"
    session = await repository.get(agent_id)
    assert session.api_id == 111
    assert session.phone_number == "+79990000000"
    assert session.name == "Mimic"
    assert session.soul_prompt == "Short calm replies"
    # Строка остаётся скрытой от мастера онбординга.
    assert session.completed_agent_id == agent_id


@pytest.mark.asyncio
async def test_start_rebind_without_stored_session_raises() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    service = AgentOnboardingService(
        repository=InMemoryOnboardingRepository(),
        telegram_factory=_fake_telegram_factory(),
    )

    with pytest.raises(ValueError):
        await service.start_rebind(agent_id, owner_id=owner_id)


@pytest.mark.asyncio
async def test_start_rebind_row_without_telegram_data_raises() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.NOT_STARTED,
            completed_agent_id=agent_id,
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
    )

    with pytest.raises(ValueError):
        await service.start_rebind(agent_id, owner_id=owner_id)


@pytest.mark.asyncio
async def test_rebind_to_agent_updates_only_session_string() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="old-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="new-session-string",
            completed_agent_id=agent_id,
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
    # Номер и приложение агента не меняются — обновляется только сессия.
    assert config.telegram_api_id == 12345
    assert config.telegram_api_hash == "old-hash"
    assert config.name == "Mimic"
    assert config.soul_prompt == "Short calm replies"
    # Строка не удаляется: она же будет переиспользована при следующей привязке.
    saved = await repository.get(onboarding_id)
    assert saved.authorization_status is TelegramLoginStatus.AUTHORIZED
    assert saved.session_secret == "new-session-string"


@pytest.mark.asyncio
async def test_start_rebind_rejects_foreign_owner() -> None:
    owner_id = uuid4()
    other_id = uuid4()
    agent_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=other_id,
            authorization_status=TelegramLoginStatus.NOT_STARTED,
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
    )

    with pytest.raises(OnboardingOwnershipError):
        await service.start_rebind(agent_id, owner_id=owner_id)

    saved = await repository.get(agent_id)
    assert saved.owner_id == other_id
    # Владелец проверяется до «лечения»: чужой строке метку не ставим.
    assert saved.completed_agent_id is None


@pytest.mark.asyncio
async def test_rebind_to_agent_requires_authorized_session() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.CODE_REQUESTED,
            completed_agent_id=agent_id,
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
        agent_store=InMemoryAgentStore(),
    )

    with pytest.raises(TelegramAuthorizationIncompleteError):
        await service.rebind_to_agent(onboarding_id, agent_id, owner_id=owner_id)


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
            completed_agent_id=agent_id,
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
    )

    with pytest.raises(RuntimeError):
        await service.rebind_to_agent(onboarding_id, agent_id, owner_id=owner_id)


@pytest.mark.asyncio
async def test_rebind_to_agent_keeps_session_on_unknown_agent() -> None:
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
            completed_agent_id=agent_id,
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
        agent_store=InMemoryAgentStore(),
    )

    with pytest.raises(KeyError):
        await service.rebind_to_agent(onboarding_id, agent_id, owner_id=owner_id)

    saved = await repository.get(onboarding_id)
    assert saved.completed_agent_id == agent_id


@pytest.mark.asyncio
async def test_rebind_to_agent_rejects_session_bound_to_another_agent() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="session",
            completed_agent_id=uuid4(),  # привязана к другому агенту
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
            session_secret="old-session",
            name="Mimic",
            soul_prompt="Short replies",
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
    assert config.telegram_session_string == "old-session"
    assert config.telegram_api_hash == "old-hash"
