"""Tests for GET /api/v1/agents/{id}/media (Telegram media download proxy)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from telethon.errors import FileReferenceExpiredError

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.agent_store import AgentRecord, InMemoryAgentStore
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier
from tests.api.fakes import FakeAgentManager


class FakeRuntime:
    def __init__(self, behaviour: str = "ok") -> None:
        self.behaviour = behaviour
        self.requested: list[str] = []

    async def download_media_by_id(self, media_id: str) -> tuple[bytes, str]:
        from mimic42.integrations.telegram_tools import parse_media_id

        parse_media_id(media_id)  # same contract as production: ValueError on bad format
        self.requested.append(media_id)
        if self.behaviour == "expired":
            raise FileReferenceExpiredError(None)
        return b"\x89PNG\r\n\x1a\nfake-bytes", "image/png"


def _make_app(
    manager: FakeAgentManager,
    store: InMemoryAgentStore,
    owner_id: Any,
) -> Any:
    return create_app(
        manager=manager,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )


def _make_store(agent_id: Any, owner_id: Any) -> InMemoryAgentStore:
    return InMemoryAgentStore(
        agents=[
            AgentRecord(
                agent_id=agent_id,
                owner_id=owner_id,
                name="Media Agent",
                state=AgentRuntimeState.RUNNING,
            )
        ]
    )


@pytest.mark.asyncio
async def test_get_media_returns_bytes_with_mime_type() -> None:
    manager = FakeAgentManager()
    owner_id = uuid4()
    agent_id = uuid4()
    store = _make_store(agent_id, owner_id)
    manager.runtimes[agent_id] = FakeRuntime("ok")
    app = _make_app(manager, store, owner_id)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v1/agents/{agent_id}/media",
            headers=AUTH_HEADERS,
            params={"media_id": "photo:123:456:abcd:4"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")
    assert manager.runtimes[agent_id].requested == ["photo:123:456:abcd:4"]


@pytest.mark.asyncio
async def test_get_media_returns_422_for_malformed_reference() -> None:
    manager = FakeAgentManager()
    owner_id = uuid4()
    agent_id = uuid4()
    store = _make_store(agent_id, owner_id)
    manager.runtimes[agent_id] = FakeRuntime("ok")
    app = _make_app(manager, store, owner_id)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v1/agents/{agent_id}/media",
            headers=AUTH_HEADERS,
            params={"media_id": "not-a-media-id"},
        )

    assert response.status_code == 422
    assert manager.runtimes[agent_id].requested == []


@pytest.mark.asyncio
async def test_get_media_returns_410_for_expired_reference() -> None:
    manager = FakeAgentManager()
    owner_id = uuid4()
    agent_id = uuid4()
    store = _make_store(agent_id, owner_id)
    manager.runtimes[agent_id] = FakeRuntime("expired")
    app = _make_app(manager, store, owner_id)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v1/agents/{agent_id}/media",
            headers=AUTH_HEADERS,
            params={"media_id": "photo:123:456:abcd:4"},
        )

    assert response.status_code == 410
    assert "устарела" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_media_returns_404_for_foreign_agent() -> None:
    manager = FakeAgentManager()
    owner_id = uuid4()
    agent_id = uuid4()
    store = _make_store(agent_id, owner_id)
    manager.runtimes[agent_id] = FakeRuntime("ok")
    app = _make_app(manager, store, uuid4())  # different user

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v1/agents/{agent_id}/media",
            headers=AUTH_HEADERS,
            params={"media_id": "photo:123:456:abcd:4"},
        )

    assert response.status_code == 404
    assert manager.runtimes[agent_id].requested == []
