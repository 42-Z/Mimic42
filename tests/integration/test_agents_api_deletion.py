from __future__ import annotations

from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import MimicAgentRuntime
from mimic42.core.manager import AgentManager
from mimic42.core.onboarding import OnboardingSession, TelegramLoginStatus
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.testing.slots import Slot
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier
from tests.core.test_agent_runtime import FakeLangChainAgent, FakeTelegramClient


async def test_get_agent_returns_404_after_real_deletion(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()

    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="encrypted-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="encrypted-session",
            name="Mimic",
            soul_prompt="Soul",
        )
    )

    manager = AgentManager(
        runtime_factory=lambda runtime_config: MimicAgentRuntime(
            config=runtime_config,
            telegram_client=FakeTelegramClient(),
            langchain_agent=FakeLangChainAgent(),
        ),
        config_loader=store.get_runtime_config,
        status_sink=store.update_status,
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
        before = await client.get(f"/api/v1/agents/{agent_id}", headers=AUTH_HEADERS)
        deleted = await client.delete(f"/api/v1/agents/{agent_id}", headers=AUTH_HEADERS)
        after = await client.get(f"/api/v1/agents/{agent_id}", headers=AUTH_HEADERS)
        unknown = await client.get(f"/api/v1/agents/{uuid4()}", headers=AUTH_HEADERS)
        listing = await client.get("/api/v1/agents", headers=AUTH_HEADERS)

    assert before.status_code == 200
    assert before.json()["agent_id"] == str(agent_id)
    assert deleted.status_code == 204
    # The deleted agent must be 404, not a re-materialised 200 or a 500
    assert after.status_code == 404
    assert unknown.status_code == 404
    assert listing.status_code == 200
    assert listing.json() == []
