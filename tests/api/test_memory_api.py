from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import AgentRuntimeState, AgentStatus
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier


class FakeAgentManager:
    def __init__(self, owner_id: UUID) -> None:
        self.owner_id = owner_id

    async def create_agent(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def get_agent_status(self, agent_id: UUID) -> AgentStatus:
        return AgentStatus(
            agent_id=agent_id,
            owner_id=self.owner_id,
            state=AgentRuntimeState.RUNNING,
        )

    async def list_agents(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def start_agent(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def stop_agent(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def trigger_message(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def shutdown(self) -> None:
        pass


class FakeMem0LongTermMemory:
    def __init__(self) -> None:
        self.get_all_called: list[UUID] = []
        self.search_called: list[tuple[UUID, str]] = []
        self.history_called: list[str] = []

    async def get_all_memories(self, agent_id: UUID) -> list[dict[str, Any]]:
        self.get_all_called.append(agent_id)
        return [{"id": "mem-1", "memory": "test memory", "user_id": str(agent_id)}]

    async def search_memories(self, agent_id: UUID, query: str) -> list[dict[str, Any]]:
        self.search_called.append((agent_id, query))
        return [{"id": "mem-1", "memory": f"searched {query}", "user_id": str(agent_id)}]

    async def get_memory_history(self, memory_id: str) -> list[dict[str, Any]]:
        self.history_called.append(memory_id)
        return [{"id": "hist-1", "memory_id": memory_id, "new_value": "new"}]


@pytest.mark.asyncio
async def test_get_memories_endpoint() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    manager = FakeAgentManager(owner_id)
    memory_store = FakeMem0LongTermMemory()

    app = create_app(manager=manager, auth_verifier=FakeAuthVerifier(owner_id))
    app.state.long_term_memory = memory_store

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        # Test without query
        response = await client.get(
            f"/api/v1/agents/{agent_id}/memory",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200
        assert response.json() == [
            {"id": "mem-1", "memory": "test memory", "user_id": str(agent_id)}
        ]
        assert memory_store.get_all_called == [agent_id]

        # Test with query
        response_search = await client.get(
            f"/api/v1/agents/{agent_id}/memory?query=coffee",
            headers=AUTH_HEADERS,
        )
        assert response_search.status_code == 200
        assert response_search.json() == [
            {"id": "mem-1", "memory": "searched coffee", "user_id": str(agent_id)}
        ]
        assert memory_store.search_called == [(agent_id, "coffee")]


@pytest.mark.asyncio
async def test_get_memory_history_endpoint() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    memory_id = "mem-1"
    manager = FakeAgentManager(owner_id)
    memory_store = FakeMem0LongTermMemory()

    app = create_app(manager=manager, auth_verifier=FakeAuthVerifier(owner_id))
    app.state.long_term_memory = memory_store

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v1/agents/{agent_id}/memory/{memory_id}/history",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200
        assert response.json() == [{"id": "hist-1", "memory_id": memory_id, "new_value": "new"}]
        assert memory_store.history_called == [memory_id]


@pytest.mark.asyncio
async def test_get_memory_history_rejects_foreign_memory_id() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    manager = FakeAgentManager(owner_id)
    memory_store = FakeMem0LongTermMemory()

    app = create_app(manager=manager, auth_verifier=FakeAuthVerifier(owner_id))
    app.state.long_term_memory = memory_store

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v1/agents/{agent_id}/memory/mem-foreign/history",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 404
        assert memory_store.history_called == []


@pytest.mark.asyncio
async def test_memory_endpoint_returns_501_when_not_configured() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    manager = FakeAgentManager(owner_id)

    app = create_app(manager=manager, auth_verifier=FakeAuthVerifier(owner_id))
    # app.state.long_term_memory is None by default

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v1/agents/{agent_id}/memory",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 501
        assert "не настроена" in response.json()["detail"]
