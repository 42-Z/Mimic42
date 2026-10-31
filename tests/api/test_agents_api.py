from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentRuntimeState,
    MimicAgentRuntime,
    TelegramProxyConfig,
)
from mimic42.core.agent_store import AgentRecord, InMemoryAgentStore
from mimic42.core.manager import AgentManager
from mimic42.core.onboarding import (
    AgentOnboardingService,
    InMemoryOnboardingRepository,
    OnboardingSession,
    TelegramCodeVerification,
    TelegramLoginStatus,
)
from mimic42.core.telegram_app_settings import TelegramAppSettings
from mimic42.core.telegram_proxy import TelegramProxyUnavailableError
from mimic42.testing.telegram import (
    FakeTelegramAccount,
    FakeTelegramAuthClientFactory,
    FakeTelegramClient,
)
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier
from tests.api.fakes import FakeAgentManager, configured_telegram_app
from tests.core.test_agent_runtime import FakeLangChainAgent


def create_test_app(**kwargs: Any) -> FastAPI:
    """Приложение с парой, сохранённой в панели (единственный источник)."""
    kwargs.setdefault("telegram_app_settings", configured_telegram_app())
    return create_app(**kwargs)


class SavedConfigAgentStore(InMemoryAgentStore):
    def __init__(self, config: AgentRuntimeConfig) -> None:
        super().__init__(
            agents=[
                AgentRecord(
                    agent_id=config.agent_id,
                    owner_id=config.owner_id,
                    name=config.name,
                    state=AgentRuntimeState.STOPPED,
                )
            ]
        )
        self.config = config
        self.loaded_ids: list[UUID] = []
        self.load_error: Exception | None = None

    async def get_runtime_config(self, agent_id: UUID) -> AgentRuntimeConfig:
        self.loaded_ids.append(agent_id)
        if self.load_error is not None:
            raise self.load_error
        if agent_id != self.config.agent_id:
            raise KeyError(agent_id)
        return self.config


@pytest.fixture
def saved_agent_config() -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_api_id=12345,
        telegram_api_hash="saved-app-hash",
        telegram_session_string="saved-session",
        telegram_session_token="saved-session-token",
        telegram_proxy=TelegramProxyConfig(protocol="socks5", host="assigned.invalid", port=1080),
        system_prompt="Saved system prompt",
        soul_prompt="Saved personality",
        name="Saved agent",
    )


def _create_runtime(config: AgentRuntimeConfig) -> MimicAgentRuntime:
    return MimicAgentRuntime(
        config=config,
        telegram_client=FakeTelegramClient(),
        langchain_agent=FakeLangChainAgent(),
    )


@pytest.mark.parametrize("auto_start", [False, True])
@pytest.mark.parametrize("assigned_proxy", [False, True])
@pytest.mark.parametrize("server_defaults", [False, True])
@pytest.mark.asyncio
async def test_create_saved_agent_uses_only_saved_runtime_config(
    saved_agent_config: AgentRuntimeConfig,
    auto_start: bool,
    assigned_proxy: bool,
    server_defaults: bool,
) -> None:
    if not assigned_proxy:
        saved_agent_config.telegram_proxy = None
    store = SavedConfigAgentStore(saved_agent_config)
    factory = Mock(side_effect=_create_runtime)
    manager = AgentManager(runtime_factory=factory, config_loader=store.get_runtime_config)
    app = create_app(
        manager=manager,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(saved_agent_config.owner_id),
        telegram_app_settings=(
            configured_telegram_app()
            if server_defaults
            else TelegramAppSettings(repository=None, cipher=None)
        ),
    )
    payload = {
        "agent_id": str(saved_agent_config.agent_id),
        "telegram_session_string": "request-session",
        "soul_prompt": "Request personality",
        "auto_start": auto_start,
    }

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/agents", headers=AUTH_HEADERS, json=payload)
            assert response.status_code == 201
            assert response.json() == {
                "agent_id": str(saved_agent_config.agent_id),
                "owner_id": str(saved_agent_config.owner_id),
                "state": "running" if auto_start else "stopped",
            }
            runtime = await manager.get_agent(saved_agent_config.agent_id)
            assert runtime.config == saved_agent_config
            duplicate = await client.post("/api/v1/agents", headers=AUTH_HEADERS, json=payload)

        assert duplicate.status_code == 409
        assert factory.call_count == 1
        assert (await manager.get_agent(saved_agent_config.agent_id)) is runtime
    finally:
        await manager.shutdown()


@pytest.mark.parametrize("target", ["unknown", "generated", "foreign", "foreign_cached"])
@pytest.mark.parametrize("auto_start", [False, True])
@pytest.mark.asyncio
async def test_create_saved_agent_rejects_unowned_ids_before_loading_config(
    saved_agent_config: AgentRuntimeConfig,
    target: str,
    auto_start: bool,
) -> None:
    user_id = uuid4()
    store = SavedConfigAgentStore(saved_agent_config)
    factory = Mock(side_effect=_create_runtime)
    manager = AgentManager(runtime_factory=factory, config_loader=store.get_runtime_config)
    if target == "foreign_cached":
        await manager.create_agent(saved_agent_config)
        factory.reset_mock()
    app = create_test_app(
        manager=manager,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(user_id),
    )
    payload: dict[str, object] = {
        "telegram_session_string": "request-session",
        "soul_prompt": "Request personality",
        "auto_start": auto_start,
    }
    if target != "generated":
        payload["agent_id"] = str(
            saved_agent_config.agent_id if target.startswith("foreign") else uuid4()
        )

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/agents", headers=AUTH_HEADERS, json=payload)

        assert response.status_code == 404
        assert response.json() == {"detail": "Агент не найден"}
        assert store.loaded_ids == []
        factory.assert_not_called()
        assert await manager.list_agents(owner_id=user_id) == []
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_create_saved_agent_rechecks_loaded_config_owner(
    saved_agent_config: AgentRuntimeConfig,
) -> None:
    store = SavedConfigAgentStore(saved_agent_config)
    store.config = saved_agent_config.model_copy(update={"owner_id": uuid4()})
    factory = Mock(side_effect=_create_runtime)
    manager = AgentManager(runtime_factory=factory, config_loader=store.get_runtime_config)
    app = create_test_app(
        manager=manager,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(saved_agent_config.owner_id),
    )

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/agents",
                headers=AUTH_HEADERS,
                json={"agent_id": str(saved_agent_config.agent_id), "auto_start": True},
            )

        assert response.status_code == 404
        assert response.json() == {"detail": "Агент не найден"}
        factory.assert_not_called()
        assert await manager.list_agents() == []
    finally:
        await manager.shutdown()


@pytest.mark.parametrize(
    ("load_error", "expected_status"),
    [(KeyError("missing saved config"), 404), (TelegramProxyUnavailableError("broken proxy"), 503)],
)
@pytest.mark.asyncio
async def test_create_saved_agent_load_failure_never_registers_raw_fallback(
    saved_agent_config: AgentRuntimeConfig,
    load_error: Exception,
    expected_status: int,
) -> None:
    store = SavedConfigAgentStore(saved_agent_config)
    store.load_error = load_error
    factory = Mock(side_effect=_create_runtime)
    manager = AgentManager(runtime_factory=factory, config_loader=store.get_runtime_config)
    app = create_test_app(
        manager=manager,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(saved_agent_config.owner_id),
    )
    payload = {
        "agent_id": str(saved_agent_config.agent_id),
        "telegram_session_string": "request-session",
        "auto_start": True,
    }

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/agents", headers=AUTH_HEADERS, json=payload)
            assert response.status_code == expected_status
            assert "broken proxy" not in response.text
            factory.assert_not_called()
            assert await manager.list_agents() == []
            store.load_error = None
            retry = await client.post("/api/v1/agents", headers=AUTH_HEADERS, json=payload)

        assert retry.status_code == 201
        assert (await manager.get_agent(saved_agent_config.agent_id)).config == saved_agent_config
    finally:
        await manager.shutdown()


@pytest.mark.parametrize("auto_start", [False, True])
@pytest.mark.asyncio
async def test_create_without_store_keeps_server_defaults_and_request_config(
    auto_start: bool,
) -> None:
    owner_id = uuid4()
    manager = AgentManager(runtime_factory=_create_runtime)
    app = create_test_app(manager=manager, auth_verifier=FakeAuthVerifier(owner_id))
    agent_id = uuid4()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/agents",
                headers=AUTH_HEADERS,
                json={
                    "agent_id": str(agent_id),
                    "owner_id": str(uuid4()),
                    "telegram_api_id": 999,
                    "telegram_api_hash": "request-app-hash",
                    "telegram_session_string": "request-session",
                    "soul_prompt": "Request personality",
                    "auto_start": auto_start,
                },
            )

        assert response.status_code == 201
        assert response.json()["state"] == ("running" if auto_start else "stopped")
        config = (await manager.get_agent(agent_id)).config
        assert config.owner_id == owner_id
        assert config.telegram_api_id == 777
        assert config.telegram_api_hash == "deployment-hash"
        assert config.telegram_session_string == "request-session"
        assert config.soul_prompt == "Request personality"
        assert config.telegram_proxy is None
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_create_without_store_preserves_428_for_unauthorized_auto_start() -> None:
    manager = FakeAgentManager(start_unauthorized=True)
    app = create_test_app(manager=manager, auth_verifier=FakeAuthVerifier(uuid4()))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/agents", headers=AUTH_HEADERS, json={"auto_start": True}
        )

    assert response.status_code == 428
    assert manager.started == []


@pytest.mark.asyncio
async def test_agent_list_keeps_effective_state_rules_after_extraction() -> None:
    owner_id = uuid4()
    runtime_agent_id = uuid4()
    stale_agent_id = uuid4()
    error_agent_id = uuid4()
    manager = FakeAgentManager()
    await manager.create_agent(
        AgentRuntimeConfig(
            agent_id=runtime_agent_id,
            owner_id=owner_id,
            telegram_api_id=12345,
            telegram_api_hash="test-hash",
            system_prompt="Test system prompt",
        )
    )
    manager.created[runtime_agent_id].state = AgentRuntimeState.ERROR
    store = InMemoryAgentStore(
        agents=[
            AgentRecord(
                agent_id=runtime_agent_id,
                owner_id=owner_id,
                name="Runtime override",
                state=AgentRuntimeState.RUNNING,
            ),
            AgentRecord(
                agent_id=stale_agent_id,
                owner_id=owner_id,
                name="Stale database state",
                state=AgentRuntimeState.STARTING,
            ),
            AgentRecord(
                agent_id=error_agent_id,
                owner_id=owner_id,
                name="Saved error",
                state=AgentRuntimeState.ERROR,
            ),
        ]
    )
    app = create_test_app(
        manager=manager,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/agents", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert {UUID(row["agent_id"]): row["state"] for row in response.json()} == {
        runtime_agent_id: "error",
        stale_agent_id: "stopped",
        error_agent_id: "error",
    }


@pytest.mark.asyncio
async def test_health_endpoint() -> None:
    app = create_test_app(manager=FakeAgentManager())

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "mimic42-api"}


@pytest.mark.asyncio
async def test_create_start_and_trigger_agent_through_api() -> None:
    manager = FakeAgentManager()
    owner_id = uuid4()
    app = create_test_app(manager=manager, auth_verifier=FakeAuthVerifier(owner_id))
    agent_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        create_response = await client.post(
            "/api/v1/agents",
            headers=AUTH_HEADERS,
            json={
                "agent_id": str(agent_id),
                "telegram_session_string": "1BQANOTEuMTA4LjUuMLB6LjE",
                "soul_prompt": "Short replies",
                "auto_start": True,
            },
        )
        start_response = await client.post(
            f"/api/v1/agents/{agent_id}/start",
            headers=AUTH_HEADERS,
        )
        trigger_response = await client.post(
            f"/api/v1/agents/{agent_id}/messages/trigger",
            headers=AUTH_HEADERS,
            json={"peer": "me", "text": "hello"},
        )

    assert create_response.status_code == 201
    assert create_response.json() == {
        "agent_id": str(agent_id),
        "owner_id": str(owner_id),
        "state": "running",
    }
    assert start_response.status_code == 204
    assert trigger_response.status_code == 200
    assert trigger_response.json()["response_text"] == "api response"
    assert manager.started == [agent_id, agent_id]
    assert manager.triggers == [(agent_id, "me", "hello")]


@pytest.mark.asyncio
async def test_reload_agent_returns_204_for_owner() -> None:
    manager = FakeAgentManager()
    owner_id = uuid4()
    app = create_test_app(manager=manager, auth_verifier=FakeAuthVerifier(owner_id))
    agent_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        await client.post(
            "/api/v1/agents",
            headers=AUTH_HEADERS,
            json={
                "agent_id": str(agent_id),
                "telegram_session_string": "1BQANOTEuMTA4LjUuMLB6LjE",
                "soul_prompt": "Short replies",
                "auto_start": True,
            },
        )
        response = await client.post(
            f"/api/v1/agents/{agent_id}/reload",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 204
    assert manager.reloaded == [agent_id]


@pytest.mark.asyncio
async def test_reload_agent_returns_404_for_unknown_agent() -> None:
    manager = FakeAgentManager()
    owner_id = uuid4()
    unknown_agent_id = uuid4()
    store = InMemoryAgentStore()
    app = create_test_app(
        manager=manager,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/agents/{unknown_agent_id}/reload",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 404
    assert manager.reloaded == []


@pytest.mark.asyncio
async def test_delete_agent_returns_204_for_owner() -> None:
    manager = FakeAgentManager()
    owner_id = uuid4()
    agent_id = uuid4()
    store = InMemoryAgentStore(
        agents=[
            AgentRecord(
                agent_id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                state=AgentRuntimeState.STOPPED,
            )
        ]
    )
    app = create_test_app(
        manager=manager,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.delete(
            f"/api/v1/agents/{agent_id}",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 204
    assert manager.removed == [agent_id]
    assert await store.list_agents(owner_id=owner_id) == []


@pytest.mark.asyncio
async def test_delete_agent_returns_404_for_foreign_agent() -> None:
    manager = FakeAgentManager()
    owner_id = uuid4()
    foreign_agent_id = uuid4()
    store = InMemoryAgentStore()
    app = create_test_app(
        manager=manager,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.delete(
            f"/api/v1/agents/{foreign_agent_id}",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 404
    assert manager.removed == []


@pytest.mark.asyncio
async def test_reset_context_moves_the_boundary_for_owner() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    store = InMemoryAgentStore(
        agents=[
            AgentRecord(
                agent_id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                state=AgentRuntimeState.RUNNING,
            )
        ]
    )
    app = create_test_app(
        manager=FakeAgentManager(),
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/agents/{agent_id}/context/reset",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    returned = datetime.fromisoformat(response.json()["context_reset_at"])
    assert returned == store.context_resets[agent_id]


@pytest.mark.asyncio
async def test_reset_context_returns_404_for_foreign_agent() -> None:
    foreign_agent_id = uuid4()
    store = InMemoryAgentStore(
        agents=[
            AgentRecord(
                agent_id=foreign_agent_id,
                owner_id=uuid4(),
                name="Someone else's",
                state=AgentRuntimeState.RUNNING,
            )
        ]
    )
    app = create_test_app(
        manager=FakeAgentManager(),
        agent_store=store,
        auth_verifier=FakeAuthVerifier(uuid4()),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/agents/{foreign_agent_id}/context/reset",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 404
    assert store.context_resets == {}


@pytest.mark.asyncio
async def test_start_agent_reports_unauthorized_session_in_russian() -> None:
    manager = FakeAgentManager(start_unauthorized=True)
    owner_id = uuid4()
    app = create_test_app(manager=manager, auth_verifier=FakeAuthVerifier(owner_id))
    agent_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        create_response = await client.post(
            "/api/v1/agents",
            headers=AUTH_HEADERS,
            json={
                "agent_id": str(agent_id),
                "telegram_session_string": "1BQANOTEuMTA4LjUuMLB6LjE",
                "soul_prompt": "Short replies",
            },
        )
        response = await client.post(
            f"/api/v1/agents/{agent_id}/start",
            headers=AUTH_HEADERS,
        )

    assert create_response.status_code == 201
    assert response.status_code == 428
    detail = response.json()["detail"]
    assert "не авторизована" in detail
    assert "повторная привязка" in detail
    assert manager.started == []


@pytest.mark.asyncio
async def test_rebind_flow_reuses_agent_session_and_keeps_agent_profile() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    manager = FakeAgentManager()
    store = InMemoryAgentStore()
    repository = InMemoryOnboardingRepository()
    # Строка мастера после finalize: id == agent_id, метка занята.
    await repository.save(
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
            completed_agent_id=agent_id,
        )
    )
    onboarding_service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
        agent_store=store,
    )
    app = create_test_app(
        manager=manager,
        onboarding_service=onboarding_service,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )
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

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        start_response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind",
            headers=AUTH_HEADERS,
        )
        assert start_response.status_code == 201
        assert start_response.json()["onboarding_id"] == str(agent_id)
        onboarding_id = UUID(start_response.json()["onboarding_id"])

        verify_response = await client.post(
            f"/api/v1/onboarding/{onboarding_id}/telegram/code",
            headers=AUTH_HEADERS,
            json={"code": "12345"},
        )

        confirm_response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind/confirm",
            headers=AUTH_HEADERS,
            json={"onboarding_id": str(onboarding_id)},
        )

    assert start_response.json()["authorization_status"] == "code_requested"
    assert verify_response.status_code == 200
    assert verify_response.json()["authorization_status"] == "authorized"

    assert confirm_response.status_code == 200
    assert confirm_response.json() == {
        "agent_id": str(agent_id),
        "owner_id": str(owner_id),
        "state": "stopped",
    }
    assert manager.calls[-2:] == [("stop", agent_id), ("reload", agent_id)]
    assert manager.stopped == [agent_id]
    assert manager.reloaded == [agent_id]

    config = await store.get_runtime_config(agent_id)
    # Номер и приложение агента не меняются — обновляется только сессия.
    assert config.telegram_api_id == 12345
    assert config.telegram_api_hash == "old-hash"
    assert config.telegram_session_string == "fake-session:+79990000000"
    assert config.name == "Mimic"
    assert config.soul_prompt == "Short replies"

    saved = await repository.get(agent_id)
    assert saved.completed_agent_id == agent_id
    assert saved.authorization_status is TelegramLoginStatus.AUTHORIZED


@pytest.mark.asyncio
async def test_rebind_start_reuses_stored_phone_without_payload() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    store = InMemoryAgentStore()
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
            name="Mimic",
            soul_prompt="Short replies",
            completed_agent_id=agent_id,
        )
    )
    onboarding_service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
        agent_store=store,
    )
    app = create_test_app(
        manager=FakeAgentManager(),
        onboarding_service=onboarding_service,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )
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

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 201
    assert response.json()["authorization_status"] == "code_requested"
    assert response.json()["phone_number"] == "+79990000000"


@pytest.mark.asyncio
async def test_rebind_confirm_rejects_foreign_onboarding_session() -> None:
    owner_id = uuid4()
    foreign_owner = uuid4()
    agent_id = uuid4()
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
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=foreign_owner,
            authorization_status=TelegramLoginStatus.AUTHORIZED,
        )
    )
    onboarding_service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
        agent_store=store,
    )
    app = create_test_app(
        manager=FakeAgentManager(),
        onboarding_service=onboarding_service,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind/confirm",
            headers=AUTH_HEADERS,
            json={"onboarding_id": str(onboarding_id)},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rebind_confirm_cannot_apply_authorization_completed_during_stop() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    store = InMemoryAgentStore()
    repository = InMemoryOnboardingRepository()
    working_session = OnboardingSession(
        onboarding_id=agent_id,
        owner_id=owner_id,
        api_id=12345,
        api_hash_secret="saved-hash",
        phone_number="+79990000000",
        authorization_status=TelegramLoginStatus.AUTHORIZED,
        session_secret="working-session",
        name="Mimic",
        soul_prompt="Short replies",
        completed_agent_id=agent_id,
    )
    await store.create_from_onboarding(working_session)
    working_config = await store.get_runtime_config(agent_id)
    await repository.save(
        working_session.model_copy(update={"session_secret": "first-authorized-rebind"})
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
        agent_store=store,
    )

    class AuthorizeDuringStopManager(FakeAgentManager):
        async def stop_agent(self, agent_id: UUID) -> None:
            await super().stop_agent(agent_id)
            if len(self.stopped) == 1:
                await service.start_rebind(agent_id, owner_id=owner_id)
                await service.verify_telegram_code(
                    agent_id, TelegramCodeVerification(code="12345"), owner_id=owner_id
                )

    manager = AuthorizeDuringStopManager()
    app = create_test_app(
        manager=manager,
        onboarding_service=service,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )
    initial_authorization = (await repository.get(agent_id)).authorization_ref()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        stale_response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind/confirm",
            headers=AUTH_HEADERS,
            json={"onboarding_id": str(agent_id)},
        )

        assert stale_response.status_code == 409
        assert set(stale_response.json()) == {"detail"}
        for secret in ("saved-hash", "working-session", "first-authorized-rebind", "+79990000000"):
            assert secret not in stale_response.text
        latest = await repository.get(agent_id)
        assert latest.authorization_ref() != initial_authorization
        assert latest.authorization_status is TelegramLoginStatus.AUTHORIZED
        assert latest.session_secret == "fake-session:+79990000000"
        assert latest.applied_auth_generation is None
        assert await store.get_runtime_config(agent_id) == working_config
        assert manager.stopped == [agent_id]
        assert manager.reloaded == []

        fresh_response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind/confirm",
            headers=AUTH_HEADERS,
            json={"onboarding_id": str(agent_id)},
        )

    assert fresh_response.status_code == 200
    assert fresh_response.json() == {
        "agent_id": str(agent_id),
        "owner_id": str(owner_id),
        "state": "stopped",
    }
    config = await store.get_runtime_config(agent_id)
    assert config.telegram_session_string == latest.session_secret
    assert config.name == "Mimic"
    assert config.soul_prompt == "Short replies"
    applied = await repository.get(agent_id)
    assert applied.authorization_ref() == latest.authorization_ref()
    assert applied.applied_auth_generation == latest.auth_generation
    assert manager.reloaded == [agent_id]


@pytest.mark.asyncio
async def test_rebind_confirm_requires_completed_authorization() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    manager = FakeAgentManager()
    store = InMemoryAgentStore()
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
            name="Mimic",
            soul_prompt="Short replies",
            completed_agent_id=agent_id,
        )
    )
    app = create_test_app(
        manager=manager,
        onboarding_service=AgentOnboardingService(
            repository=repository,
            telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
            agent_store=store,
        ),
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )
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

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        start_response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind",
            headers=AUTH_HEADERS,
        )
        assert start_response.status_code == 201
        assert start_response.json()["onboarding_id"] == str(agent_id)

        # Код не вводили — сессия осталась неавторизованной.
        response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind/confirm",
            headers=AUTH_HEADERS,
            json={"onboarding_id": str(agent_id)},
        )

    assert response.status_code == 409
    assert "авторизация" in response.json()["detail"].lower()
    assert manager.stopped == []


@pytest.mark.asyncio
async def test_rebind_confirm_returns_404_for_unknown_onboarding_session() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
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
    app = create_test_app(
        manager=FakeAgentManager(),
        onboarding_service=AgentOnboardingService(
            repository=InMemoryOnboardingRepository(),
            telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
            agent_store=store,
        ),
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind/confirm",
            headers=AUTH_HEADERS,
            json={"onboarding_id": str(uuid4())},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rebind_start_returns_404_for_unknown_agent() -> None:
    owner_id = uuid4()
    store = InMemoryAgentStore()
    app = create_test_app(
        manager=FakeAgentManager(),
        onboarding_service=AgentOnboardingService(
            repository=InMemoryOnboardingRepository(),
            telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
            agent_store=store,
        ),
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/agents/{uuid4()}/telegram/rebind",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rebind_start_restores_missing_onboarding_from_agent_store() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    store = InMemoryAgentStore()
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="session",
            name="Mimic",
            soul_prompt="Short replies",
        )
    )
    repository = InMemoryOnboardingRepository()
    account = FakeTelegramAccount()
    app = create_test_app(
        manager=FakeAgentManager(),
        onboarding_service=AgentOnboardingService(
            repository=repository,
            telegram_factory=FakeTelegramAuthClientFactory(account),
            agent_store=store,
        ),
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 201
    assert response.json()["authorization_status"] == "code_requested"
    assert account.phone == "+79990000000"
    restored = await repository.get(agent_id)
    assert restored.completed_agent_id == agent_id
    assert restored.api_id == 12345


@pytest.mark.asyncio
async def test_rebind_requires_agent_store() -> None:
    owner_id = uuid4()
    manager = FakeAgentManager(default_owner_id=owner_id)
    app = create_test_app(
        manager=manager,
        auth_verifier=FakeAuthVerifier(owner_id),
    )
    agent_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        start_response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind",
            headers=AUTH_HEADERS,
        )
        confirm_response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind/confirm",
            headers=AUTH_HEADERS,
            json={"onboarding_id": str(uuid4())},
        )

    assert start_response.status_code == 503
    assert confirm_response.status_code == 503
    assert "хранилище агентов" in start_response.json()["detail"]


@pytest.mark.parametrize(
    ("stop_error", "reload_error"),
    [(True, False), (False, True)],
    ids=["stop_fails", "reload_fails"],
)
@pytest.mark.asyncio
async def test_rebind_confirm_returns_503_when_runtime_lifecycle_fails(
    stop_error: bool,
    reload_error: bool,
) -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    manager = FakeAgentManager(stop_error=stop_error, reload_error=reload_error)
    store = InMemoryAgentStore()
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
            name="Mimic",
            soul_prompt="Short replies",
            completed_agent_id=agent_id,
        )
    )
    app = create_test_app(
        manager=manager,
        onboarding_service=AgentOnboardingService(
            repository=repository,
            telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
            agent_store=store,
        ),
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )
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

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        start_response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind",
            headers=AUTH_HEADERS,
        )
        assert start_response.status_code == 201

        await client.post(
            f"/api/v1/onboarding/{agent_id}/telegram/code",
            headers=AUTH_HEADERS,
            json={"code": "12345"},
        )
        confirm_response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind/confirm",
            headers=AUTH_HEADERS,
            json={"onboarding_id": str(agent_id)},
        )

    # Сбой lifecycle не выдаём за успех: клиент получает 503 и может повторить
    # подтверждение (перепривязка в базе идемпотентна).
    assert confirm_response.status_code == 503
    assert "Повторите подтверждение" in confirm_response.json()["detail"]
    config = await store.get_runtime_config(agent_id)
    if stop_error:
        # Живой рантайм не пересобираем: reload_agent вынимает старый из реестра
        # до close, и новый клиент поднялся бы со свежей сессией, пока старый
        # ещё держит старую.
        assert ("reload", agent_id) not in manager.calls
        assert config.telegram_session_string == "old-session"
    else:
        assert manager.calls[-2:] == [("stop", agent_id), ("reload", agent_id)]
        assert config.telegram_session_string == "fake-session:+79990000000"


@pytest.mark.asyncio
async def test_rebind_confirm_is_idempotent_for_consumed_session() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    manager = FakeAgentManager()
    store = InMemoryAgentStore()
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
            name="Mimic",
            soul_prompt="Short replies",
            completed_agent_id=agent_id,
        )
    )
    app = create_test_app(
        manager=manager,
        onboarding_service=AgentOnboardingService(
            repository=repository,
            telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
            agent_store=store,
        ),
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )
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

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        first_response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind/confirm",
            headers=AUTH_HEADERS,
            json={"onboarding_id": str(agent_id)},
        )
        second_response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind/confirm",
            headers=AUTH_HEADERS,
            json={"onboarding_id": str(agent_id)},
        )

    # Строка не удаляется после confirm, поэтому повторный вызов не падает.
    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["state"] == "stopped"
    assert second_response.json()["state"] == "stopped"
    assert manager.reloaded == [agent_id, agent_id]
    saved = await repository.get(agent_id)
    assert saved.completed_agent_id == agent_id
