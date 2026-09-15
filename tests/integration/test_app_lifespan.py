"""То, что раньше не выполнялось ни в одном тесте: построение движка,
расшифровка Fernet, восстановление запущенных агентов после рестарта."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.crypto import FernetSecretCipher
from mimic42.core.onboarding import OnboardingSession, TelegramLoginStatus
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.testing.server import build_test_app
from mimic42.testing.slots import Slot


def _cipher() -> FernetSecretCipher:
    """Тот же ключ, что build_test_app() берёт из TEST_SECRET_KEY — без
    этого настоящий lifespan не сможет расшифровать данные, записанные
    тестом другим ключом (или вообще без шифрования)."""
    return FernetSecretCipher(os.environ["TEST_SECRET_KEY"])


@pytest.mark.asyncio
async def test_running_agent_is_restored_after_restart(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Агент лежит в базе в состоянии «запущен», как после падения процесса —
    настоящий lifespan должен поднять его заново при старте приложения."""
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()
    cipher = _cipher()
    store = DatabaseAgentStore(db_session_factory, cipher=cipher)
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            api_id=1,
            api_hash_secret=cipher.encrypt("test-api-hash"),
            name="восстановленный",
            soul_prompt="спокойный помощник, отвечает коротко",
        )
    )
    await store.update_status(agent_id, AgentRuntimeState.RUNNING)

    app = build_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        async with app.router.lifespan_context(app):
            statuses = await app.state.agent_manager.list_agents()
            assert agent_id in {status.agent_id for status in statuses}
            response = await client.get("/health")
            assert response.status_code == 200


@pytest.mark.asyncio
async def test_encrypted_telegram_session_is_decrypted_on_start(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Сессия телеги лежит в базе зашифрованной; при старте она должна
    расшифроваться тем же ключом, иначе агент не поднимется."""
    cipher = _cipher()
    owner_id = clean_slot.persona("empty").user_id
    agent_id = uuid4()
    store = DatabaseAgentStore(db_session_factory, cipher=cipher)
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            api_id=1,
            api_hash_secret=cipher.encrypt("test-api-hash"),
            session_secret=cipher.encrypt("fake-session:+79990000000"),
            name="с сессией",
            soul_prompt="спокойный помощник, отвечает коротко",
        )
    )

    app = build_test_app()
    async with app.router.lifespan_context(app):
        config = await app.state.agent_store.get_runtime_config(agent_id)

    assert config.telegram_session_string == "fake-session:+79990000000"
