from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.config import Settings
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.agent_store import AgentRecord, InMemoryAgentStore
from mimic42.core.media import MediaFile
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier


def _settings_without_supabase() -> Settings:
    return Settings(supabase_url=None, supabase_service_key=None)


class FakeMediaStorage:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    async def upload(
        self,
        *,
        agent_id: UUID,
        filename: str,
        data: bytes,
        mime_type: str,
        kind: str = "doc",
    ) -> MediaFile | None:
        return None

    async def open(self, path: str) -> bytes | None:
        return self.files.get(path)

    async def remove_prefix(self, agent_id: UUID) -> None:
        self.files.clear()


def _store_with_agent(owner_id: UUID, agent_id: UUID) -> InMemoryAgentStore:
    return InMemoryAgentStore(
        agents=[
            AgentRecord(
                agent_id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                state=AgentRuntimeState.STOPPED,
            )
        ]
    )


@pytest.mark.asyncio
async def test_media_returns_file_for_owner() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    path = f"{agent_id}/{uuid4()}/img.jpeg"
    app = create_app(
        agent_store=_store_with_agent(owner_id, agent_id),
        auth_verifier=FakeAuthVerifier(owner_id),
        media_uploader=FakeMediaStorage({path: b"IMG"}),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get(f"/api/v1/agents/{agent_id}/media/{path}", headers=AUTH_HEADERS)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/jpeg")
    assert resp.content == b"IMG"


@pytest.mark.asyncio
async def test_media_rejects_path_of_other_agent() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    app = create_app(
        agent_store=_store_with_agent(owner_id, agent_id),
        auth_verifier=FakeAuthVerifier(owner_id),
        media_uploader=FakeMediaStorage({"other-agent/1/x.jpeg": b"X"}),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get(
            f"/api/v1/agents/{agent_id}/media/other-agent/1/x.jpeg", headers=AUTH_HEADERS
        )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_media_404_when_file_missing() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    app = create_app(
        agent_store=_store_with_agent(owner_id, agent_id),
        auth_verifier=FakeAuthVerifier(owner_id),
        media_uploader=FakeMediaStorage({}),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get(
            f"/api/v1/agents/{agent_id}/media/{agent_id}/nowhere.jpeg", headers=AUTH_HEADERS
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_media_404_when_storage_not_configured() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    app = create_app(
        agent_store=_store_with_agent(owner_id, agent_id),
        auth_verifier=FakeAuthVerifier(owner_id),
        media_uploader=None,
        settings=_settings_without_supabase(),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get(
            f"/api/v1/agents/{agent_id}/media/{agent_id}/nowhere.jpeg", headers=AUTH_HEADERS
        )

    assert resp.status_code == 404
