from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from mimic42.core.agent_store import InMemoryAgentStore
from mimic42.core.onboarding import OnboardingSession, TelegramLoginStatus


def _authorized_session(
    owner_id: UUID, onboarding_id: UUID, session_secret: str
) -> OnboardingSession:
    return OnboardingSession(
        onboarding_id=onboarding_id,
        owner_id=owner_id,
        api_id=777,
        api_hash_secret="new-encrypted-hash",
        phone_number="+79990000001",
        authorization_status=TelegramLoginStatus.AUTHORIZED,
        session_secret=session_secret,
    )


@pytest.mark.asyncio
async def test_rebind_updates_session_and_keeps_profile() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    store = InMemoryAgentStore()
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="old-encrypted-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="old-encrypted-session",
            name="Mimic",
            soul_prompt="Soul",
        )
    )

    await store.rebind_telegram_session(
        agent_id, _authorized_session(owner_id, uuid4(), "new-encrypted-session")
    )

    config = await store.get_runtime_config(agent_id)
    # Обновляется только строка сессии: номер/приложение остаются прежними.
    assert config.telegram_api_id == 12345
    assert config.telegram_api_hash == "old-encrypted-hash"
    assert config.telegram_session_string == "new-encrypted-session"
    assert config.name == "Mimic"
    assert config.soul_prompt == "Soul"
    assert config.agent_id == agent_id
    assert config.owner_id == owner_id
    agents = await store.list_agents(owner_id=owner_id)
    assert [agent.name for agent in agents] == ["Mimic"]


@pytest.mark.parametrize("missing_field", ["api_id", "api_hash_secret", "session_secret"])
@pytest.mark.asyncio
async def test_rebind_rejects_session_without_credentials(missing_field: str) -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    store = InMemoryAgentStore()
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="old-encrypted-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="old-encrypted-session",
            name="Mimic",
            soul_prompt="Soul",
        )
    )
    broken = _authorized_session(owner_id, uuid4(), "new-encrypted-session")
    setattr(broken, missing_field, None)

    with pytest.raises(ValueError):
        await store.rebind_telegram_session(agent_id, broken)

    config = await store.get_runtime_config(agent_id)
    assert config.telegram_api_id == 12345
    assert config.telegram_api_hash == "old-encrypted-hash"
    assert config.telegram_session_string == "old-encrypted-session"


@pytest.mark.asyncio
async def test_rebind_unknown_agent_raises_key_error() -> None:
    store = InMemoryAgentStore()

    with pytest.raises(KeyError):
        await store.rebind_telegram_session(
            uuid4(), _authorized_session(uuid4(), uuid4(), "new-encrypted-session")
        )
