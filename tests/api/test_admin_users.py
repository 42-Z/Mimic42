from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.config import Settings
from mimic42.core.admin import (
    AdminAgentSummary,
    AdminPage,
    AdminRepository,
    AdminUserDetail,
    AdminUserSummary,
)
from mimic42.core.agent_runtime import AgentRuntimeConfig, AgentRuntimeState
from mimic42.core.model_catalog import DEFAULT_LLM_MODEL
from tests.api.admin_fakes import FakeAdminRepository
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier
from tests.api.fakes import FakeAgentManager


def _settings() -> Settings:
    return Settings(
        database_connection_string=None,
        mem0_api_key=None,
        braintrust_api_key=None,
        supabase_url=None,
        supabase_service_key=None,
        secret_key=None,
    )


def _user(
    user_id: UUID,
    *,
    display_name: str | None,
    created_at: datetime,
    agents_total: int = 0,
    states: dict[AgentRuntimeState, int] | None = None,
) -> AdminUserSummary:
    return AdminUserSummary(
        user_id=user_id,
        email=f"{user_id.hex[:8]}@example.test",
        display_name=display_name,
        created_at=created_at,
        agents_total=agents_total,
        states=states or {},
    )


def _app(
    admin_id: UUID,
    repository: FakeAdminRepository,
    manager: FakeAgentManager | None = None,
) -> FastAPI:
    return create_app(
        manager=manager or FakeAgentManager(),
        admin_repository=cast(AdminRepository, repository),
        auth_verifier=FakeAuthVerifier(admin_id),
        settings=_settings(),
    )


async def _manager_with_runtime(
    agent_id: UUID,
    owner_id: UUID,
    state: AgentRuntimeState,
) -> FakeAgentManager:
    manager = FakeAgentManager()
    await manager.create_agent(
        AgentRuntimeConfig(
            agent_id=agent_id,
            owner_id=owner_id,
            telegram_api_id=12345,
            telegram_api_hash="test-hash",
            system_prompt="Test system prompt",
        )
    )
    manager.created[agent_id].state = state
    return manager


@pytest.mark.asyncio
async def test_user_list_includes_empty_profiles_and_passes_one_runtime_snapshot() -> None:
    admin_id = uuid4()
    owner_id = uuid4()
    empty_profile = _user(
        owner_id,
        display_name="Empty profile",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    repository = FakeAdminRepository(admin_ids={admin_id}, users=[empty_profile])
    runtime_agent_id = uuid4()
    manager = await _manager_with_runtime(
        runtime_agent_id,
        owner_id,
        AgentRuntimeState.RUNNING,
    )
    app = _app(admin_id, repository, manager)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/admin/users",
            params={"q": "  EMPTY  ", "page": 1, "page_size": 10},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "items": [
            {
                "user_id": str(owner_id),
                "email": empty_profile.email,
                "display_name": "Empty profile",
                "created_at": empty_profile.created_at.isoformat().replace("+00:00", "Z"),
                "agents_total": 0,
                "states": {},
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 10,
    }
    assert repository.user_calls == [
        (
            "list",
            {
                "q": "EMPTY",
                "page": 1,
                "page_size": 10,
                "runtime_states": {runtime_agent_id: AgentRuntimeState.RUNNING},
            },
        )
    ]


@pytest.mark.asyncio
async def test_user_detail_is_minimal_and_unknown_user_returns_404() -> None:
    admin_id = uuid4()
    user_id = uuid4()
    agent_id = uuid4()
    profile = _user(
        user_id,
        display_name="Profile",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        agents_total=1,
        states={AgentRuntimeState.STOPPED: 1},
    )
    agent = AdminAgentSummary(
        agent_id=agent_id,
        name="Mimic",
        llm_model=DEFAULT_LLM_MODEL,
        state=AgentRuntimeState.STOPPED,
    )
    detail = AdminUserDetail(
        profile=profile,
        agents=AdminPage(items=[agent], total=1, page=2, page_size=1),
    )
    repository = FakeAdminRepository(
        admin_ids={admin_id},
        user_details={user_id: detail},
    )
    app = _app(admin_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        found = await client.get(
            f"/api/v1/admin/users/{user_id}",
            params={"page": 2, "page_size": 1},
            headers=AUTH_HEADERS,
        )
        missing = await client.get(
            f"/api/v1/admin/users/{uuid4()}",
            headers=AUTH_HEADERS,
        )

    assert found.status_code == 200
    assert found.headers["cache-control"] == "no-store"
    assert found.json()["profile"]["agents_total"] == 1
    assert found.json()["agents"] == {
        "items": [
            {
                "agent_id": str(agent_id),
                "name": "Mimic",
                "llm_model": DEFAULT_LLM_MODEL,
                "state": "stopped",
            }
        ],
        "total": 1,
        "page": 2,
        "page_size": 1,
    }
    assert "soul_prompt" not in found.text
    assert "settings" not in found.text
    assert "session" not in found.text
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Пользователь не найден"}
