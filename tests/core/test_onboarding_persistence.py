from __future__ import annotations

from uuid import uuid4

import pytest

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.agent_store import InMemoryAgentStore
from mimic42.core.onboarding import (
    AgentOnboardingService,
    AgentProfileInput,
    InMemoryOnboardingRepository,
    OnboardingOwnershipError,
    OnboardingSession,
    TelegramAuthClient,
    TelegramCredentials,
    TelegramLoginStatus,
)


class FakeTelegramAuthClient:
    def __init__(self) -> None:
        self.connect_calls = 0
        self.disconnect_calls = 0

    async def connect(self) -> None:
        self.connect_calls += 1

    async def disconnect(self) -> None:
        self.disconnect_calls += 1

    async def send_code_request(self, phone: str) -> object:
        return {"phone_code_hash": f"hash-for-{phone}"}

    async def sign_in(
        self,
        *,
        phone: str | None = None,
        code: str | None = None,
        phone_code_hash: str | None = None,
        password: str | None = None,
    ) -> object:
        return {}

    def save_session(self) -> str:
        return "session-string"


class FakeTelegramAuthFactory:
    def build(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
    ) -> TelegramAuthClient:
        return FakeTelegramAuthClient()  # type: ignore[return-value]


class UnusedTelegramFactory:
    def build(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
    ) -> TelegramAuthClient:
        raise AssertionError("Telegram factory should not be used while finalizing an agent")


@pytest.mark.asyncio
async def test_finalize_agent_persists_agent_and_telegram_session() -> None:
    owner_id = uuid4()
    onboarding_id = uuid4()
    onboarding_repository = InMemoryOnboardingRepository()
    agent_store = InMemoryAgentStore()
    await onboarding_repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="encrypted-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="encrypted-session",
        )
    )
    service = AgentOnboardingService(
        repository=onboarding_repository,
        telegram_factory=UnusedTelegramFactory(),
        agent_store=agent_store,
    )

    status = await service.finalize_agent(
        onboarding_id,
        AgentProfileInput(name="Mimic", soul_prompt="Short replies"),
    )

    assert status.agent_id == onboarding_id
    assert status.state is AgentRuntimeState.STOPPED
    persisted = await agent_store.get_runtime_config(onboarding_id)
    assert persisted.owner_id == owner_id
    assert persisted.telegram_api_hash == "encrypted-hash"
    assert persisted.telegram_session_string == "encrypted-session"
    from mimic42.core.onboarding import load_default_system_prompt

    assert persisted.system_prompt == load_default_system_prompt()
    assert persisted.soul_prompt == "Short replies"


@pytest.mark.asyncio
async def test_two_onboarding_runs_create_two_distinct_sessions() -> None:
    owner_id = uuid4()
    repository = InMemoryOnboardingRepository()
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthFactory(),
    )
    credentials = TelegramCredentials(
        owner_id=owner_id,
        api_id=12345,
        api_hash="hash",
        phone_number="+79990000000",
    )

    first = await service.request_telegram_code(credentials)
    second = await service.request_telegram_code(credentials)

    assert first.onboarding_id != second.onboarding_id
    assert len(repository._sessions) == 2


@pytest.mark.asyncio
async def test_request_code_with_existing_onboarding_id_reuses_draft() -> None:
    owner_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.NOT_STARTED,
            name="Mimic",
            soul_prompt="Short replies",
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthFactory(),
    )
    credentials = TelegramCredentials(
        owner_id=owner_id,
        api_id=12345,
        api_hash="hash",
        phone_number="+79990000001",
    )

    status = await service.request_telegram_code(credentials, onboarding_id=onboarding_id)

    assert status.onboarding_id == onboarding_id
    reused = await repository.get(onboarding_id)
    assert reused.name == "Mimic"
    assert reused.soul_prompt == "Short replies"
    assert reused.phone_number == "+79990000001"


@pytest.mark.asyncio
async def test_request_code_for_foreign_onboarding_is_rejected() -> None:
    owner_id = uuid4()
    stranger_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=stranger_id,
            authorization_status=TelegramLoginStatus.NOT_STARTED,
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthFactory(),
    )
    credentials = TelegramCredentials(
        owner_id=owner_id,
        api_id=12345,
        api_hash="hash",
        phone_number="+79990000002",
    )

    with pytest.raises(OnboardingOwnershipError):
        await service.request_telegram_code(credentials, onboarding_id=onboarding_id)
