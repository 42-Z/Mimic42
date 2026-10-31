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
    TelegramLoginRouteChangedError,
    TelegramLoginStaleError,
    TelegramLoginStatus,
)
from mimic42.core.telegram_proxy import (
    TelegramProxyAssignment,
    TelegramProxyUnavailableError,
)
from mimic42.testing.telegram import (
    FakeTelegramAccount,
    FakeTelegramAuthClient,
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
    assert set(store.load_calls) == {proxy_id}


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
    assert set(store.load_calls) == {proxy_id}
    assert store.allocate_calls == 0


@pytest.mark.asyncio
async def test_broken_existing_proxy_preserves_assignment_and_refuses_network() -> None:
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

    assigned = (await repository.get(onboarding_id)).proxy_id
    with pytest.raises(TelegramProxyUnavailableError):
        await service.request_telegram_code(
            _credentials(owner_id),
            onboarding_id=onboarding_id,
        )

    saved = await repository.get(onboarding_id)
    assert saved.proxy_id == assigned
    assert factory.proxies == []


@pytest.mark.asyncio
async def test_new_login_reserves_before_network_and_does_not_restore_deleted_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryOnboardingRepository()
    proxy_id = uuid4()
    replacement_id = uuid4()
    config = _proxy_config()
    account = FakeTelegramAccount()
    original = FakeTelegramAuthClient.send_code_request

    async def delete_during_request(client: FakeTelegramAuthClient, phone: str) -> object:
        assert len(repository._sessions) == 1
        reserved = next(iter(repository._sessions.values()))
        assert reserved.proxy_id == proxy_id
        reserved.proxy_id = replacement_id
        reserved.name = "Edited during login"
        return await original(client, phone)

    monkeypatch.setattr(FakeTelegramAuthClient, "send_code_request", delete_during_request)
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(account),
        proxy_store=FakeTelegramProxyStore(
            allocation=TelegramProxyAssignment(proxy_id=proxy_id, config=config),
            configs={proxy_id: config},
        ),
    )

    result = await service.request_telegram_code(_credentials(uuid4()))

    saved = await repository.get(result.onboarding_id)
    assert saved.proxy_id == replacement_id
    assert saved.name == "Edited during login"
    assert saved.authorization_status is TelegramLoginStatus.CODE_REQUESTED


@pytest.mark.asyncio
async def test_rebind_verification_uses_latest_assignment() -> None:
    owner_id, agent_id, old_id, new_id = uuid4(), uuid4(), uuid4(), uuid4()
    old_config, new_config = _proxy_config("old.test"), _proxy_config("new.test")
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="old-session",
            completed_agent_id=agent_id,
        )
    )
    store = FakeTelegramProxyStore(
        configs={old_id: old_config, new_id: new_config},
        agent_assignments={agent_id: TelegramProxyAssignment(proxy_id=old_id, config=old_config)},
    )
    account = FakeTelegramAccount()
    account.script_code("12345")
    factory = FakeTelegramAuthClientFactory(account)
    service = AgentOnboardingService(
        repository=repository, telegram_factory=factory, proxy_store=store
    )
    await service.start_rebind(agent_id, owner_id=owner_id)
    store.agent_assignments[agent_id] = TelegramProxyAssignment(proxy_id=new_id, config=new_config)

    result = await service.verify_telegram_code(agent_id, TelegramCodeVerification(code="12345"))

    assert result.authorization_status is TelegramLoginStatus.AUTHORIZED
    assert factory.proxies == [old_config, new_config]


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
    assert saved.proxy_id is None
    assert set(store.agent_calls) == {agent_id}
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


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["reset", "delete", "newer"])
async def test_cancelled_code_result_does_not_overwrite_current_draft(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    repository = InMemoryOnboardingRepository()
    owner_id, onboarding_id = uuid4(), uuid4()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.NOT_STARTED,
        )
    )
    original = FakeTelegramAuthClient.send_code_request
    newer = AgentOnboardingService(
        repository=repository, telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount())
    )
    entered = False

    async def cancel(client: FakeTelegramAuthClient, phone: str) -> object:
        nonlocal entered
        if not entered:
            entered = True
            if action == "reset":
                await repository.reset_authorization(onboarding_id)
            elif action == "delete":
                repository._sessions.pop(onboarding_id)
            else:
                await newer.request_telegram_code(
                    _credentials(owner_id), onboarding_id=onboarding_id
                )
        return await original(client, phone)

    monkeypatch.setattr(FakeTelegramAuthClient, "send_code_request", cancel)
    with pytest.raises(TelegramLoginStaleError):
        await newer.request_telegram_code(_credentials(owner_id), onboarding_id=onboarding_id)
    if action == "delete":
        assert onboarding_id not in repository._sessions
    else:
        expected = (
            TelegramLoginStatus.NOT_STARTED
            if action == "reset"
            else TelegramLoginStatus.CODE_REQUESTED
        )
        assert (await repository.get(onboarding_id)).authorization_status is expected


@pytest.mark.asyncio
async def test_route_change_after_connect_prevents_next_rpc_without_erasing_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryOnboardingRepository()
    proxy_id = uuid4()
    config = _proxy_config()
    account = FakeTelegramAccount()
    factory = FakeTelegramAuthClientFactory(account)
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=factory,
        proxy_store=FakeTelegramProxyStore(
            allocation=TelegramProxyAssignment(proxy_id=proxy_id, config=config),
            configs={proxy_id: config},
        ),
    )
    started = await service.request_telegram_code(_credentials(uuid4()))
    before = await repository.get(started.onboarding_id)
    original = FakeTelegramAuthClient.connect

    async def unassign(client: FakeTelegramAuthClient) -> None:
        await original(client)
        repository._sessions[started.onboarding_id].proxy_id = None

    async def forbidden_sign_in(client: FakeTelegramAuthClient, **kwargs: str | None) -> object:
        raise AssertionError("old client must not issue another RPC")

    monkeypatch.setattr(FakeTelegramAuthClient, "connect", unassign)
    monkeypatch.setattr(FakeTelegramAuthClient, "sign_in", forbidden_sign_in)
    with pytest.raises(TelegramLoginRouteChangedError):
        await service.verify_telegram_code(
            started.onboarding_id, TelegramCodeVerification(code="12345")
        )
    saved = await repository.get(started.onboarding_id)
    assert saved.phone_code_hash_secret == before.phone_code_hash_secret
    assert saved.session_secret == before.session_secret
    assert saved.proxy_id is None


@pytest.mark.asyncio
async def test_successful_auth_survives_route_change_and_disconnect_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryOnboardingRepository()
    proxy_id = uuid4()
    config = _proxy_config()
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
        proxy_store=FakeTelegramProxyStore(
            allocation=TelegramProxyAssignment(proxy_id=proxy_id, config=config),
            configs={proxy_id: config},
        ),
    )
    started = await service.request_telegram_code(_credentials(uuid4()))
    original = FakeTelegramAuthClient.sign_in
    get_me_calls: list[bool] = []

    async def change_after_sign_in(client: FakeTelegramAuthClient, **kwargs: str | None) -> object:
        result = await original(client, **kwargs)
        repository._sessions[started.onboarding_id].proxy_id = None
        return result

    async def forbidden_get_me(client: FakeTelegramAuthClient) -> object:
        get_me_calls.append(True)
        raise AssertionError("optional RPC must not use the previous route")

    async def failed_disconnect(client: FakeTelegramAuthClient) -> None:
        raise RuntimeError("synthetic disconnect failure")

    monkeypatch.setattr(FakeTelegramAuthClient, "sign_in", change_after_sign_in)
    monkeypatch.setattr(FakeTelegramAuthClient, "get_me", forbidden_get_me)
    monkeypatch.setattr(FakeTelegramAuthClient, "disconnect", failed_disconnect)
    result = await service.verify_telegram_code(
        started.onboarding_id, TelegramCodeVerification(code="12345")
    )
    saved = await repository.get(started.onboarding_id)
    assert result.authorization_status is TelegramLoginStatus.AUTHORIZED
    assert saved.authorization_status is TelegramLoginStatus.AUTHORIZED
    assert saved.session_secret
    assert saved.proxy_id is None
    assert get_me_calls == []
