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
    assert config.telegram_api_id == 777
    assert config.telegram_api_hash == "deployment-hash"
    assert config.telegram_session_string == "fake-session:+79990000000"
    assert config.name == "Mimic"
    assert config.soul_prompt == "Short replies"

    saved = await repository.get(agent_id)
    assert saved.completed_agent_id == agent_id
    assert saved.authorization_status is TelegramLoginStatus.AUTHORIZED


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
    app = create_app(
        manager=manager,
        onboarding_service=AgentOnboardingService(
            repository=repository,
            telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
            agent_store=store,
        ),
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
    app = create_app(
        manager=FakeAgentManager(),
        onboarding_service=AgentOnboardingService(
            repository=InMemoryOnboardingRepository(),
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
            json={"onboarding_id": str(uuid4())},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rebind_start_returns_404_for_unknown_agent() -> None:
    owner_id = uuid4()
    store = InMemoryAgentStore()
    app = create_app(
        manager=FakeAgentManager(),
        onboarding_service=AgentOnboardingService(
            repository=InMemoryOnboardingRepository(),
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
            f"/api/v1/agents/{uuid4()}/telegram/rebind",
            headers=AUTH_HEADERS,
            json={"phone_number": "+79990000000"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rebind_requires_agent_store() -> None:
    owner_id = uuid4()
    manager = FakeAgentManager(default_owner_id=owner_id)
    app = create_app(
        manager=manager,
        auth_verifier=FakeAuthVerifier(owner_id),
        settings=Settings(telegram_api_id=777, telegram_api_hash="deployment-hash"),
    )
    agent_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        start_response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind",
            headers=AUTH_HEADERS,
            json={"phone_number": "+79990000000"},
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
    [(True, False), (False, True), (True, True)],
)
@pytest.mark.asyncio
async def test_rebind_confirm_succeeds_when_runtime_stop_or_reload_fails(
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
    app = create_app(
        manager=manager,
        onboarding_service=AgentOnboardingService(
            repository=repository,
            telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
            agent_store=store,
        ),
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

    # Перепривязка уже применена в базе: сбой рантайма не отменяет confirm.
    assert confirm_response.status_code == 200
    assert manager.calls[-2:] == [("stop", agent_id), ("reload", agent_id)]
    assert manager.stopped == ([] if stop_error else [agent_id])
    assert manager.reloaded == ([] if reload_error else [agent_id])
