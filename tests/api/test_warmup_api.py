from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import AgentRuntimeConfig
from mimic42.core.warmup import WarmupState
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier
from tests.api.fakes import FakeAgentManager

RESTRICTED_AT = datetime(2026, 10, 3, 9, 30, tzinfo=UTC)


class WarmupAgentManager(FakeAgentManager):
    def __init__(self) -> None:
        super().__init__()
        self.states: dict[UUID, WarmupState] = {}

    async def get_warmup_state(self, agent_id: UUID) -> WarmupState:
        return self.states.get(agent_id, WarmupState())

    async def start_warmup_recovery(self, agent_id: UUID) -> bool:
        state = self.states.get(agent_id, WarmupState())
        if state.restricted_at is None:
            return False
        self.states[agent_id] = WarmupState(restricted_at=state.restricted_at, recovery=True)
        return True


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def _agent(manager: FakeAgentManager, owner_id: UUID) -> UUID:
    agent_id = uuid4()
    await manager.create_agent(
        AgentRuntimeConfig(
            agent_id=agent_id,
            owner_id=owner_id,
            telegram_api_id=1,
            telegram_api_hash="hash",
            telegram_session_string="session",
            system_prompt="system",
        )
    )
    return agent_id


@pytest.mark.asyncio
async def test_owner_reads_the_restriction_state_and_starts_recovery() -> None:
    owner_id = uuid4()
    manager = WarmupAgentManager()
    agent_id = await _agent(manager, owner_id)
    manager.states[agent_id] = WarmupState(restricted_at=RESTRICTED_AT)
    app = create_app(manager=manager, auth_verifier=FakeAuthVerifier(owner_id))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        before = await client.get(f"/api/v1/agents/{agent_id}/warmup", headers=AUTH_HEADERS)
        started = await client.post(
            f"/api/v1/agents/{agent_id}/warmup/recovery", headers=AUTH_HEADERS
        )

    assert before.status_code == 200
    assert before.json() == {"restricted_at": "2026-10-03T09:30:00Z", "recovery": False}
    assert started.status_code == 200
    assert started.json() == {"restricted_at": "2026-10-03T09:30:00Z", "recovery": True}


@pytest.mark.asyncio
async def test_recovery_of_a_healthy_agent_is_a_conflict() -> None:
    owner_id = uuid4()
    manager = WarmupAgentManager()
    agent_id = await _agent(manager, owner_id)
    app = create_app(manager=manager, auth_verifier=FakeAuthVerifier(owner_id))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/api/v1/agents/{agent_id}/warmup/recovery", headers=AUTH_HEADERS
        )

    assert response.status_code == 409
    assert manager.states == {}


@pytest.mark.asyncio
async def test_other_users_cannot_read_or_change_the_state() -> None:
    manager = WarmupAgentManager()
    agent_id = await _agent(manager, uuid4())
    manager.states[agent_id] = WarmupState(restricted_at=RESTRICTED_AT)
    app = create_app(manager=manager, auth_verifier=FakeAuthVerifier(uuid4()))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        read = await client.get(f"/api/v1/agents/{agent_id}/warmup", headers=AUTH_HEADERS)
        change = await client.post(
            f"/api/v1/agents/{agent_id}/warmup/recovery", headers=AUTH_HEADERS
        )

    assert read.status_code == 403
    assert change.status_code == 403
    assert manager.states[agent_id].recovery is False


@pytest.mark.asyncio
async def test_manager_without_warmup_support_answers_not_implemented() -> None:
    owner_id = uuid4()
    manager = FakeAgentManager()
    agent_id = await _agent(manager, owner_id)
    app = create_app(manager=manager, auth_verifier=FakeAuthVerifier(owner_id))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"/api/v1/agents/{agent_id}/warmup", headers=AUTH_HEADERS)

    assert response.status_code == 501
