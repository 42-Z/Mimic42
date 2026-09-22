from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.config import Settings
from mimic42.core.agent_runtime import (
    AgentRuntimeState,
)
from mimic42.core.agent_store import AgentRecord, InMemoryAgentStore
from mimic42.core.onboarding import (
    AgentOnboardingService,
    InMemoryOnboardingRepository,
    OnboardingSession,
    TelegramLoginStatus,
)
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramAuthClientFactory
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier
from tests.api.fakes import FakeAgentManager


@pytest.mark.asyncio
async def test_health_endpoint() -> None:
    app = create_app(manager=FakeAgentManager())

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
    app = create_app(manager=manager, auth_verifier=FakeAuthVerifier(owner_id))
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
                "telegram_api_id": 12345,
                "telegram_api_hash": "hash",
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
    app = create_app(manager=manager, auth_verifier=FakeAuthVerifier(owner_id))
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
                "telegram_api_id": 12345,
                "telegram_api_hash": "hash",
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
    app = create_app(
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
    app = create_app(
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
    app = create_app(
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
async def test_start_agent_reports_unauthorized_session_in_russian() -> None:
    manager = FakeAgentManager(start_unauthorized=True)
    owner_id = uuid4()
    app = create_app(manager=manager, auth_verifier=FakeAuthVerifier(owner_id))
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
                "telegram_api_id": 12345,
                "telegram_api_hash": "hash",
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
async def test_rebind_flow_replaces_session_and_keeps_agent_profile() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    manager = FakeAgentManager()
    store = InMemoryAgentStore()
    onboarding_service = AgentOnboardingService(
        repository=InMemoryOnboardingRepository(),
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
        agent_store=store,
    )
    app = create_app(
        manager=manager,
        onboarding_service=onboarding_service,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
        settings=Settings(telegram_api_id=777, telegram_api_hash="deployment-hash"),
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
            json={"phone_number": "+79990000000"},
        )
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

    assert start_response.status_code == 201
    assert start_response.json()["authorization_status"] == "code_requested"
    assert verify_response.status_code == 200
    assert verify_response.json()["authorization_status"] == "authorized"

    assert confirm_response.status_code == 200
    assert confirm_response.json() == {
        "agent_id": str(agent_id),
        "owner_id": str(owner_id),
        "state": "stopped",
    }
    assert manager.stopped == [agent_id]
    assert manager.reloaded == [agent_id]

    config = await store.get_runtime_config(agent_id)
    assert config.telegram_api_hash == "deployment-hash"
    assert config.telegram_session_string != "old-session"
    assert config.name == "Mimic"
    assert config.soul_prompt == "Short replies"


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
    app = create_app(
        manager=FakeAgentManager(),
        onboarding_service=onboarding_service,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
        settings=Settings(telegram_api_id=777, telegram_api_hash="deployment-hash"),
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
async def test_rebind_confirm_requires_completed_authorization() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    onboarding_id = uuid4()
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
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.CODE_REQUESTED,
        )
    )
    app = create_app(
        manager=FakeAgentManager(),
        onboarding_service=AgentOnboardingService(
            repository=repository,
            telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
            agent_store=store,
        ),
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
        settings=Settings(telegram_api_id=777, telegram_api_hash="deployment-hash"),
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

    assert response.status_code == 409
    assert "авторизация" in response.json()["detail"].lower()
