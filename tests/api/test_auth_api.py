from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.agent_store import AgentMessageRecord, AgentRecord, InMemoryAgentStore
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier
from tests.api.test_agents_api import FakeAgentManager


@pytest.mark.asyncio
async def test_agents_endpoint_requires_access_token() -> None:
    app = create_app(auth_verifier=FakeAuthVerifier(uuid4()))

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/agents")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_agents_endpoint_accepts_access_token_cookie() -> None:
    user_id = uuid4()
    verifier = FakeAuthVerifier(user_id)
    app = create_app(auth_verifier=verifier)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        client.cookies.set("mimic42_access_token", "cookie-token")
        response = await client.get("/api/v1/agents")

    assert response.status_code == 200
    assert verifier.tokens == ["cookie-token"]


@pytest.mark.asyncio
async def test_agent_messages_are_forbidden_for_other_owner() -> None:
    owner_id = uuid4()
    other_user_id = uuid4()
    agent_id = uuid4()
    store = InMemoryAgentStore(
        agents=[
            AgentRecord(
                agent_id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                state=AgentRuntimeState.STOPPED,
            )
        ],
        messages=[
            AgentMessageRecord(
                agent_id=agent_id,
                peer="chat",
                role="assistant",
                content="secret",
                created_at=datetime.now(UTC),
            )
        ],
    )
    app = create_app(agent_store=store, auth_verifier=FakeAuthVerifier(other_user_id))

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v1/agents/{agent_id}/messages",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_agent_uses_authenticated_user_not_payload_owner_id() -> None:
    user_id = uuid4()
    payload_owner_id = uuid4()
    app = create_app(manager=FakeAgentManager(), auth_verifier=FakeAuthVerifier(user_id))
    agent_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/agents",
            headers=AUTH_HEADERS,
            json={
                "agent_id": str(agent_id),
                "owner_id": str(payload_owner_id),
                "telegram_session_name": "sessions/api-agent",
                "telegram_api_id": 12345,
                "telegram_api_hash": "hash",
            },
        )

    assert response.status_code == 201
    assert response.json()["owner_id"] == str(user_id)
