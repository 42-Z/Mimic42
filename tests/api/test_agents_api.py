from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentRuntimeState,
    AgentStatus,
    AgentTrigger,
    AgentTriggerResult,
)
from mimic42.core.agent_store import AgentRecord, InMemoryAgentStore
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier


@dataclass
class FakeAgentRecord:
    config: AgentRuntimeConfig
    state: AgentRuntimeState


class FakeAgentManager:
    def __init__(self) -> None:
        self.created: dict[UUID, FakeAgentRecord] = {}
        self.started: list[UUID] = []
        self.stopped: list[UUID] = []
        self.removed: list[UUID] = []
        self.triggers: list[tuple[UUID, str, str]] = []

    async def create_agent(
        self,
        config: AgentRuntimeConfig,
        *,
        start: bool = False,
    ) -> object:
        self.created[config.agent_id] = FakeAgentRecord(
            config=config,
            state=AgentRuntimeState.STOPPED,
        )
        if start:
            await self.start_agent(config.agent_id)
        return self

    async def start_agent(self, agent_id: UUID) -> None:
        self.started.append(agent_id)
        self.created[agent_id].state = AgentRuntimeState.RUNNING

    async def stop_agent(self, agent_id: UUID) -> None:
        self.stopped.append(agent_id)
        self.created[agent_id].state = AgentRuntimeState.STOPPED

    async def remove_agent(self, agent_id: UUID) -> None:
        self.removed.append(agent_id)

    async def get_agent_status(self, agent_id: UUID) -> AgentStatus:
        item = self.created[agent_id]
        return AgentStatus(
            agent_id=item.config.agent_id,
            owner_id=item.config.owner_id,
            state=item.state,
        )

    async def list_agents(self, *, owner_id: UUID | None = None) -> list[AgentStatus]:
        statuses = []
        for item in self.created.values():
            if owner_id is None or item.config.owner_id == owner_id:
                statuses.append(
                    AgentStatus(
                        agent_id=item.config.agent_id,
                        owner_id=item.config.owner_id,
                        state=item.state,
                    )
                )
        return statuses

    async def trigger_message(
        self,
        agent_id: UUID,
        trigger: AgentTrigger,
    ) -> AgentTriggerResult:
        self.triggers.append((agent_id, trigger.peer, trigger.text))
        return AgentTriggerResult(
            agent_id=agent_id,
            peer=trigger.peer,
            input_text=trigger.text,
            response_text="api response",
            telegram_message_id="42",
        )

    async def shutdown(self) -> None:
        return None


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
