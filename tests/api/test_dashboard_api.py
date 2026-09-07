from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.agent_store import (
    AgentActivity,
    AgentMessageRecord,
    AgentRecord,
    InMemoryAgentStore,
)
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier


@pytest.mark.asyncio
async def test_dashboard_can_list_agents_messages_and_actions() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    now = datetime(2026, 5, 19, 23, 30, tzinfo=UTC)
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
                content="hello",
                created_at=now,
            )
        ],
        activities=[
            AgentActivity(
                agent_id=agent_id,
                event_type="telegram.message.received",
                status="succeeded",
                created_at=now,
            )
        ],
    )
    app = create_app(agent_store=store, auth_verifier=FakeAuthVerifier(owner_id))

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        agents = await client.get("/api/v1/agents", headers=AUTH_HEADERS)
        messages = await client.get(
            f"/api/v1/agents/{agent_id}/messages",
            headers=AUTH_HEADERS,
        )
        actions = await client.get(
            f"/api/v1/agents/{agent_id}/actions",
            headers=AUTH_HEADERS,
        )

    assert agents.status_code == 200
    assert agents.json() == [
        {
            "agent_id": str(agent_id),
            "owner_id": str(owner_id),
            "name": "Mimic",
            "state": "stopped",
        }
    ]
    assert messages.status_code == 200
    assert messages.json()[0]["content"] == "hello"
    assert actions.status_code == 200
    assert actions.json()[0]["event_type"] == "telegram.message.received"


@pytest.mark.asyncio
async def test_dashboard_conversation_groups_incoming_and_outgoing() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    now = datetime(2026, 5, 19, 23, 30, tzinfo=UTC)
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
                peer_name="Ivan",
                role="user",
                content="hi",
                direction="incoming",
                created_at=now,
            ),
            AgentMessageRecord(
                agent_id=agent_id,
                peer="chat",
                agent_name="Mimic",
                role="assistant",
                content="hello",
                direction="agent_response",
                created_at=now,
            ),
        ],
    )
    app = create_app(agent_store=store, auth_verifier=FakeAuthVerifier(owner_id))

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        conversation = await client.get(
            f"/api/v1/agents/{agent_id}/conversation",
            headers=AUTH_HEADERS,
        )
        limited = await client.get(
            f"/api/v1/agents/{agent_id}/conversation?limit=1",
            headers=AUTH_HEADERS,
        )

    assert conversation.status_code == 200
    turns = conversation.json()
    assert len(turns) == 1
    assert turns[0]["direction"] == "both"
    assert turns[0]["incoming"] == "hi"
    assert turns[0]["outgoing"] == "hello"
    assert turns[0]["peer_name"] == "Ivan"
    assert limited.status_code == 200
    assert len(limited.json()) == 1
