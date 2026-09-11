from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import (
    AgentRuntimeState,
)
from mimic42.core.agent_store import AgentRecord, InMemoryAgentStore
from mimic42.integrations.database_models import Base
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
                "telegram_session_name": "sessions/api-agent",
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
                "telegram_session_name": "sessions/api-agent",
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


@pytest.fixture
async def sqlite_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_agent_returns_404_after_real_deletion(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from mimic42.core.agent_runtime import MimicAgentRuntime
    from mimic42.core.manager import AgentManager
    from mimic42.core.onboarding import OnboardingSession, TelegramLoginStatus
    from mimic42.integrations.database_agent_store import DatabaseAgentStore
    from mimic42.integrations.database_models import ProfileModel
    from tests.core.test_agent_runtime import FakeLangChainAgent, FakeTelegramClient

    owner_id = uuid4()
    agent_id = uuid4()
    async with sqlite_session_factory() as session:
        session.add(ProfileModel(id=owner_id))
        await session.commit()

    store = DatabaseAgentStore(sqlite_session_factory)
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="encrypted-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="encrypted-session",
            name="Mimic",
            soul_prompt="Soul",
        )
    )

    manager = AgentManager(
        runtime_factory=lambda runtime_config: MimicAgentRuntime(
            config=runtime_config,
            telegram_client=FakeTelegramClient(),
            langchain_agent=FakeLangChainAgent(),
        ),
        config_loader=store.get_runtime_config,
        status_sink=store.update_status,
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
        before = await client.get(f"/api/v1/agents/{agent_id}", headers=AUTH_HEADERS)
        deleted = await client.delete(f"/api/v1/agents/{agent_id}", headers=AUTH_HEADERS)
        after = await client.get(f"/api/v1/agents/{agent_id}", headers=AUTH_HEADERS)
        unknown = await client.get(f"/api/v1/agents/{uuid4()}", headers=AUTH_HEADERS)
        listing = await client.get("/api/v1/agents", headers=AUTH_HEADERS)

    assert before.status_code == 200
    assert before.json()["agent_id"] == str(agent_id)
    assert deleted.status_code == 204
    # The deleted agent must be 404, not a re-materialised 200 or a 500
    assert after.status_code == 404
    assert unknown.status_code == 404
    assert listing.status_code == 200
    assert listing.json() == []
