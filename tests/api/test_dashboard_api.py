from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import AgentRuntimeConfig, AgentRuntimeState
from mimic42.core.agent_store import (
    AgentActivity,
    AgentMessageRecord,
    AgentRecord,
    InMemoryAgentStore,
)
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier
from tests.api.fakes import FakeAgentManager


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
            "warmup_restricted_at": None,
        }
    ]
    assert messages.status_code == 200
    assert messages.json()[0]["content"] == "hello"
    assert actions.status_code == 200
    assert actions.json()[0]["event_type"] == "telegram.message.received"


@pytest.mark.asyncio
async def test_agent_list_carries_the_spam_block_moment() -> None:
    owner_id = uuid4()
    blocked_id = uuid4()
    free_id = uuid4()
    blocked_since = datetime(2026, 10, 10, 20, 14, 44, tzinfo=UTC)
    store = InMemoryAgentStore(
        agents=[
            AgentRecord(
                agent_id=blocked_id,
                owner_id=owner_id,
                name="Серёга",
                state=AgentRuntimeState.RUNNING,
                warmup_restricted_at=blocked_since,
            ),
            AgentRecord(
                agent_id=free_id,
                owner_id=owner_id,
                name="Аня",
                state=AgentRuntimeState.RUNNING,
            ),
        ]
    )
    app = create_app(agent_store=store, auth_verifier=FakeAuthVerifier(owner_id))

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/agents", headers=AUTH_HEADERS)

    assert response.status_code == 200
    by_id = {item["agent_id"]: item for item in response.json()}
    assert by_id[str(blocked_id)]["warmup_restricted_at"] == "2026-10-10T20:14:44Z"
    assert by_id[str(free_id)]["warmup_restricted_at"] is None


@pytest.mark.asyncio
async def test_agent_list_reports_current_runtime_state() -> None:
    owner_id = uuid4()
    unrestored_id = uuid4()
    running_id = uuid4()
    failed_id = uuid4()
    store = InMemoryAgentStore(
        agents=[
            AgentRecord(
                agent_id=unrestored_id,
                owner_id=owner_id,
                name="Unrestored",
                state=AgentRuntimeState.RUNNING,
                restore_on_start=False,
            ),
            AgentRecord(
                agent_id=running_id,
                owner_id=owner_id,
                name="Running",
                state=AgentRuntimeState.STOPPED,
            ),
            AgentRecord(
                agent_id=failed_id,
                owner_id=owner_id,
                name="Failed",
                state=AgentRuntimeState.ERROR,
            ),
        ]
    )

    manager = FakeAgentManager()
    await manager.create_agent(
        AgentRuntimeConfig(
            agent_id=running_id,
            owner_id=owner_id,
            telegram_api_id=1,
            telegram_api_hash="hash",
            telegram_session_string="session",
            system_prompt="system",
        )
    )
    await manager.start_agent(running_id)
    app = create_app(
        manager=manager,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/agents", headers=AUTH_HEADERS)

    assert response.status_code == 200
    states = {item["agent_id"]: item["state"] for item in response.json()}
    assert states == {
        str(unrestored_id): "stopped",
        str(running_id): "running",
        str(failed_id): "error",
    }


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
    body = conversation.json()
    turns = body["turns"]
    assert len(turns) == 1
    assert turns[0]["direction"] == "both"
    assert turns[0]["incoming"] == "hi"
    assert turns[0]["outgoing"] == "hello"
    assert turns[0]["peer_name"] == "Ivan"
    assert "next_before" in body
    assert limited.status_code == 200
    assert len(limited.json()["turns"]) == 1
