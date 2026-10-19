from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.config import Settings
from mimic42.core.admin import (
    ActivityCounts,
    AdminRepository,
    AdminStatistics,
    DailyActivity,
)
from mimic42.core.agent_runtime import AgentRuntimeConfig, AgentRuntimeState
from tests.api.admin_fakes import FakeAdminRepository
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier
from tests.api.fakes import FakeAgentManager, FakeAgentRecord


def _settings() -> Settings:
    return Settings(
        database_connection_string=None,
        mem0_api_key=None,
        braintrust_api_key=None,
        supabase_url=None,
        supabase_service_key=None,
        secret_key=None,
    )


def _statistics(days: Literal[7, 30] = 7) -> AdminStatistics:
    until = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    since = datetime(2026, 10, 12, tzinfo=UTC) if days == 7 else datetime(2026, 9, 19, tzinfo=UTC)
    return AdminStatistics(
        users=3,
        agents=2,
        states={AgentRuntimeState.RUNNING: 1, AgentRuntimeState.STOPPED: 1},
        input_tokens=100,
        output_tokens=30,
        period_days=days,
        since=since,
        until=until,
        totals=ActivityCounts(messages=3, actions=2, errors=2),
        daily=[DailyActivity(date=until.date(), messages=3, actions=2, errors=2)],
    )


def _manager_with_runtime(owner_id: UUID, agent_id: UUID) -> FakeAgentManager:
    manager = FakeAgentManager()
    config = AgentRuntimeConfig(
        agent_id=agent_id,
        owner_id=owner_id,
        telegram_api_id=12345,
        telegram_api_hash="test-hash",
        system_prompt="Test system prompt",
    )
    manager.created[agent_id] = FakeAgentRecord(
        config=config,
        state=AgentRuntimeState.RUNNING,
    )
    return manager


def _app(
    admin_id: UUID,
    repository: FakeAdminRepository,
    manager: FakeAgentManager,
) -> FastAPI:
    return create_app(
        manager=manager,
        admin_repository=cast(AdminRepository, repository),
        auth_verifier=FakeAuthVerifier(admin_id),
        settings=_settings(),
    )


@pytest.mark.asyncio
async def test_statistics_route_uses_allowed_period_and_runtime_snapshot() -> None:
    admin_id = uuid4()
    agent_id = uuid4()
    owner_id = uuid4()
    repository = FakeAdminRepository(admin_ids={admin_id}, statistics_value=_statistics(30))
    app = _app(admin_id, repository, _manager_with_runtime(owner_id, agent_id))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/admin/statistics?days=30",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["period_days"] == 30
    assert response.json()["states"] == {"running": 1, "stopped": 1}
    assert response.json()["totals"] == {"messages": 3, "actions": 2, "errors": 2}
    assert repository.statistics_calls[0]["days"] == 30
    assert repository.statistics_calls[0]["runtime_states"] == {agent_id: AgentRuntimeState.RUNNING}
    assert repository.statistics_calls[0]["now"].tzinfo is not None


@pytest.mark.asyncio
async def test_statistics_rejects_unsupported_period_and_does_not_hide_storage_errors() -> None:
    admin_id = uuid4()
    repository = FakeAdminRepository(admin_ids={admin_id}, statistics_value=_statistics())
    app = _app(admin_id, repository, FakeAgentManager())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid = await client.get(
            "/api/v1/admin/statistics?days=14",
            headers=AUTH_HEADERS,
        )
        assert repository.statistics_calls == []
        repository.statistics_error = RuntimeError("private database failure")
        failed = await client.get("/api/v1/admin/statistics", headers=AUTH_HEADERS)

    assert invalid.status_code == 422
    assert invalid.headers["cache-control"] == "no-store"
    assert failed.status_code == 503
    assert failed.json() == {"detail": "Администрирование временно недоступно"}
    assert "private database failure" not in failed.text
    assert failed.headers["cache-control"] == "no-store"
    assert len(repository.statistics_calls) == 1
