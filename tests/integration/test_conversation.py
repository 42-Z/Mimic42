from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.api.auth import CurrentUser
from mimic42.core.crypto import FernetSecretCipher
from mimic42.core.onboarding import OnboardingSession, TelegramLoginStatus
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.testing import registry
from mimic42.testing.llm import Reply
from mimic42.testing.peer import FakePeer
from mimic42.testing.server import build_test_app
from mimic42.testing.slots import Slot

# Разговор один на один (FakePeer) проверяется без базы в tests/testing/test_peer.py.


class _StubAuthVerifier:
    """Пропускает любой токен, всегда возвращая заранее заданного пользователя."""

    def __init__(self, user_id: UUID) -> None:
        self._user_id = user_id

    async def verify(self, token: str) -> CurrentUser:
        return CurrentUser(user_id=self._user_id)


@pytest.mark.asyncio
async def test_whole_turn_reaches_the_database_and_the_api(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Сообщение пришло, агент ответил, переписка сохранилась и видна через API."""
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()
    # Тот же ключ, что build_test_app() берёт из TEST_SECRET_KEY: конфиг
    # агента читается настоящим app.state.agent_store внутри lifespan,
    # а он расшифровывает api_hash этим ключом.
    cipher = FernetSecretCipher(os.environ["TEST_SECRET_KEY"])
    store = DatabaseAgentStore(db_session_factory, cipher=cipher)
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            api_id=1,
            api_hash_secret=cipher.encrypt("test-api-hash"),
            name="собеседник",
            soul_prompt="спокойный помощник, отвечает коротко",
        )
    )

    app = build_test_app(auth_verifier=_StubAuthVerifier(owner_id))
    async with app.router.lifespan_context(app):
        config = await app.state.agent_store.get_runtime_config(agent_id)
        await app.state.agent_manager.create_agent(config, start=True)
        app.state.scripted_agents.set_script(agent_id, [Reply("привет, чем помочь")])

        peer = FakePeer(registry.account_for(agent_id), chat_id=4242)
        await peer.send("привет")
        assert await peer.wait_for_reply(timeout=30.0) == "привет, чем помочь"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get(
                f"/api/v1/agents/{agent_id}/messages",
                headers={"Authorization": "Bearer test-token"},
            )

    assert response.status_code == 200
    texts = [item["content"] for item in response.json()]
    assert "привет" in texts
    assert "привет, чем помочь" in texts
