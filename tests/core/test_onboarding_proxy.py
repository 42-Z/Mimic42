from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from mimic42.core.agent_runtime import TelegramProxyConfig
from mimic42.core.onboarding import (
    AgentOnboardingService,
    InMemoryOnboardingRepository,
    OnboardingSession,
    TelegramCodeVerification,
    TelegramCredentials,
    TelegramLoginStatus,
)
from mimic42.core.telegram_proxy import (
    TelegramProxyAssignment,
    TelegramProxyUnavailableError,
)
from mimic42.testing.telegram import (
    FakeTelegramAccount,
    FakeTelegramAuthClientFactory,
)


def _proxy_config(host: str = "proxy.example.test") -> TelegramProxyConfig:
    return TelegramProxyConfig(protocol="socks5", host=host, port=1080)


class FakeTelegramProxyStore:
    def __init__(
        self,
        *,
        allocation: TelegramProxyAssignment | None = None,
        configs: dict[UUID, TelegramProxyConfig] | None = None,
        agent_assignments: dict[UUID, TelegramProxyAssignment] | None = None,
    ) -> None:
        self.allocation = allocation
        self.configs = dict(configs or {})
        self.agent_assignments = dict(agent_assignments or {})
        self.allocate_calls = 0
        self.load_calls: list[UUID] = []
        self.agent_calls: list[UUID] = []

    async def allocate(self) -> TelegramProxyAssignment | None:
        self.allocate_calls += 1
        return self.allocation

    async def load(self, proxy_id: UUID) -> TelegramProxyConfig:
        self.load_calls.append(proxy_id)
        config = self.configs.get(proxy_id)
        if config is None:
            raise TelegramProxyUnavailableError("Прокси не найден")
        return config

    async def assignment_for_agent(self, agent_id: UUID) -> TelegramProxyAssignment | None:
        self.agent_calls.append(agent_id)
        assignment = self.agent_assignments.get(agent_id)
        if assignment is None:
            return None
        if assignment.proxy_id not in self.configs:
            raise TelegramProxyUnavailableError("Прокси не найден")
        return assignment


def _credentials(owner_id: UUID, phone: str = "+79990000000") -> TelegramCredentials:
    return TelegramCredentials(
        owner_id=owner_id,
        api_id=12345,
        api_hash="hash",
        phone_number=phone,
    )


@pytest.mark.asyncio
async def test_new_onboarding_allocates_proxy_and_reuses_it_for_verification() -> None:
    owner_id = uuid4()
    proxy_id = uuid4()
    config = _proxy_config()
    account = FakeTelegramAccount()
    account.script_code("12345")
    factory = FakeTelegramAuthClientFactory(account)
    store = FakeTelegramProxyStore(
        allocation=TelegramProxyAssignment(proxy_id=proxy_id, config=config),
        configs={proxy_id: config},
    )
    repository = InMemoryOnboardingRepository()
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=factory,
        proxy_store=store,
    )

    started = await service.request_telegram_code(_credentials(owner_id))

    saved = await repository.get(started.onboarding_id)
    assert saved.proxy_id == proxy_id
    assert factory.proxies == [config]
    assert store.allocate_calls == 1

    verified = await service.verify_telegram_code(
        started.onboarding_id,
        TelegramCodeVerification(code="12345"),
    )

    assert verified.authorization_status is TelegramLoginStatus.AUTHORIZED
    assert factory.proxies == [config, config]
    assert store.load_calls == [proxy_id]


@pytest.mark.asyncio
async def test_existing_draft_keeps_its_proxy_without_new_allocation() -> None:
    owner_id = uuid4()
    onboarding_id = uuid4()
    proxy_id = uuid4()
    config = _proxy_config()
    store = FakeTelegramProxyStore(configs={proxy_id: config})
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.NOT_STARTED,
            proxy_id=proxy_id,
        )
    )
    factory = FakeTelegramAuthClientFactory(FakeTelegramAccount())
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=factory,
        proxy_store=store,
    )

    await service.request_telegram_code(
        _credentials(owner_id),
        onboarding_id=onboarding_id,
    )

    assert factory.proxies == [config]
    assert store.load_calls == [proxy_id]
    assert store.allocate_calls == 0


@pytest.mark.asyncio
async def test_broken_existing_proxy_clears_assignment_and_goes_direct() -> None:
    owner_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.NOT_STARTED,
            proxy_id=uuid4(),
        )
    )
    factory = FakeTelegramAuthClientFactory(FakeTelegramAccount())
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=factory,
        proxy_store=FakeTelegramProxyStore(),
    )

    await service.request_telegram_code(
        _credentials(owner_id),
        onboarding_id=onboarding_id,
    )

    saved = await repository.get(onboarding_id)
    assert saved.proxy_id is None
    assert factory.proxies == [None]


@pytest.mark.asyncio
async def test_rebind_uses_the_agent_proxy_from_telegram_sessions() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    proxy_id = uuid4()
    config = _proxy_config()
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
            completed_agent_id=agent_id,
        )
    )
    account = FakeTelegramAccount()
    factory = FakeTelegramAuthClientFactory(account)
    store = FakeTelegramProxyStore(
        configs={proxy_id: config},
        agent_assignments={agent_id: TelegramProxyAssignment(proxy_id=proxy_id, config=config)},
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=factory,
        proxy_store=store,
    )

    await service.start_rebind(agent_id, owner_id=owner_id)

    saved = await repository.get(agent_id)
    assert saved.proxy_id == proxy_id
    assert store.agent_calls == [agent_id]
    assert factory.proxies == [config]


@pytest.mark.asyncio
async def test_rebind_does_not_allocate_a_proxy_for_an_agent_without_one() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    proxy_id = uuid4()
    config = _proxy_config()
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
            completed_agent_id=agent_id,
        )
    )
    factory = FakeTelegramAuthClientFactory(FakeTelegramAccount())
    store = FakeTelegramProxyStore(
        allocation=TelegramProxyAssignment(proxy_id=proxy_id, config=config),
        configs={proxy_id: config},
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=factory,
        proxy_store=store,
    )

    await service.start_rebind(agent_id, owner_id=owner_id)

    saved = await repository.get(agent_id)
    assert saved.proxy_id is None
    assert factory.proxies == [None]
    assert store.allocate_calls == 0


@pytest.mark.asyncio
async def test_rebind_does_not_fall_back_when_the_agent_proxy_is_broken() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    proxy_id = uuid4()
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
            completed_agent_id=agent_id,
        )
    )
    factory = FakeTelegramAuthClientFactory(FakeTelegramAccount())
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=factory,
        proxy_store=FakeTelegramProxyStore(
            agent_assignments={
                agent_id: TelegramProxyAssignment(
                    proxy_id=proxy_id,
                    config=_proxy_config(),
                )
            }
        ),
    )

    with pytest.raises(TelegramProxyUnavailableError):
        await service.start_rebind(agent_id, owner_id=owner_id)

    assert factory.proxies == []


@pytest.mark.asyncio
async def test_rebind_clears_a_stale_onboarding_proxy_when_the_agent_has_none() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
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
            completed_agent_id=agent_id,
            proxy_id=uuid4(),
        )
    )
    factory = FakeTelegramAuthClientFactory(FakeTelegramAccount())
    store = FakeTelegramProxyStore()
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=factory,
        proxy_store=store,
    )

    await service.start_rebind(agent_id, owner_id=owner_id)

    saved = await repository.get(agent_id)
    assert saved.proxy_id is None
    assert factory.proxies == [None]
    assert store.load_calls == []


@pytest.mark.asyncio
async def test_rebind_without_agent_proxy_goes_direct() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
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
            completed_agent_id=agent_id,
        )
    )
    factory = FakeTelegramAuthClientFactory(FakeTelegramAccount())
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=factory,
        proxy_store=FakeTelegramProxyStore(),
    )

    await service.start_rebind(agent_id, owner_id=owner_id)

    assert factory.proxies == [None]
