from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.agent_store import AgentOwnershipError
from mimic42.core.crypto import FernetSecretCipher
from mimic42.core.model_catalog import DEFAULT_LLM_MODEL
from mimic42.core.onboarding import OnboardingSession, TelegramLoginStatus
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.integrations.database_models import (
    AgentEventModel,
    AgentMessageModel,
    AgentModel,
    AgentOnboardingSessionModel,
    TelegramSessionModel,
)
from mimic42.testing.slots import Slot


def _make_session(owner_id: UUID, onboarding_id: UUID, name: str) -> OnboardingSession:
    return OnboardingSession(
        onboarding_id=onboarding_id,
        owner_id=owner_id,
        api_id=12345,
        api_hash_secret="encrypted-hash",
        phone_number="+79990000000",
        authorization_status=TelegramLoginStatus.AUTHORIZED,
        session_secret="encrypted-session",
        name=name,
        soul_prompt="Soul",
    )


def _make_rebind_session(owner_id: UUID) -> OnboardingSession:
    return OnboardingSession(
        onboarding_id=uuid4(),
        owner_id=owner_id,
        api_id=12345,
        api_hash_secret="encrypted-hash",
        phone_number="+79990000000",
        authorization_status=TelegramLoginStatus.AUTHORIZED,
        session_secret="new-encrypted-session",
    )


async def test_get_telegram_rebind_credentials_returns_stored_secret(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()
    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(_make_session(owner_id, agent_id, "Mimic"))

    credentials = await store.get_telegram_rebind_credentials(agent_id)

    assert credentials.owner_id == owner_id
    assert credentials.api_id == 12345
    assert credentials.api_hash_secret == "encrypted-hash"
    assert credentials.phone_number == "+79990000000"


async def test_rebind_telegram_session_updates_session_and_keeps_profile(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()

    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(_make_session(owner_id, agent_id, "Mimic"))
    async with db_session_factory() as session:
        await session.execute(
            update(AgentModel)
            .where(AgentModel.id == agent_id)
            .values(settings={"model": "custom/model"})
        )
        await session.commit()
    await store.rebind_telegram_session(agent_id, _make_rebind_session(owner_id))

    config = await store.get_runtime_config(agent_id)
    # Номер и приложение агента не меняются — обновляется только сессия.
    assert config.telegram_api_id == 12345
    assert config.telegram_api_hash == "encrypted-hash"
    assert config.telegram_session_string == "new-encrypted-session"
    assert config.soul_prompt == "Soul"
    # Настройки агента (выбранная модель) переживают перепривязку.
    assert config.llm_model == "custom/model"
    agents = await store.list_agents(owner_id=owner_id)
    assert [agent.name for agent in agents if agent.agent_id == agent_id] == ["Mimic"]

    async with db_session_factory() as session:
        row = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
    assert row is not None
    assert row.session_name == agent_id.hex
    assert row.phone_number == "+79990000000"
    assert row.api_id == 12345
    assert row.api_hash_ciphertext == "encrypted-hash"
    assert row.authorization_status == "authorized"
    assert row.last_authorized_at is not None
    assert row.last_error is None


async def test_rebind_telegram_session_clears_revoked_state(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()

    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(_make_session(owner_id, agent_id, "Mimic"))
    async with db_session_factory() as session:
        await session.execute(
            update(TelegramSessionModel)
            .where(TelegramSessionModel.agent_id == agent_id)
            .values(
                authorization_status="revoked",
                last_error="Сессия Telegram не авторизована",
            )
        )
        await session.commit()

    await store.rebind_telegram_session(agent_id, _make_rebind_session(owner_id))

    async with db_session_factory() as session:
        row = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
    assert row is not None
    assert row.authorization_status == "authorized"
    assert row.last_error is None


async def test_rebind_accepts_fresh_ciphertexts_for_the_same_account(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()
    cipher = FernetSecretCipher(Fernet.generate_key().decode())
    store = DatabaseAgentStore(db_session_factory, cipher=cipher)
    initial = _make_session(owner_id, agent_id, "Mimic")
    initial.api_hash_secret = cipher.encrypt("api-hash")
    initial.session_secret = cipher.encrypt("old-session")
    await store.create_from_onboarding(initial)
    rebound = _make_rebind_session(owner_id)
    rebound.api_hash_secret = cipher.encrypt("api-hash")
    rebound.session_secret = cipher.encrypt("new-session")

    await store.rebind_telegram_session(agent_id, rebound)

    config = await store.get_runtime_config(agent_id)
    assert config.telegram_api_hash == "api-hash"
    assert config.telegram_session_string == "new-session"


@pytest.mark.parametrize(
    "missing_field", ["api_id", "api_hash_secret", "session_secret", "phone_number"]
)
async def test_rebind_telegram_session_rejects_missing_credentials(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    missing_field: str,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()

    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(_make_session(owner_id, agent_id, "Mimic"))

    broken = _make_rebind_session(owner_id)
    setattr(broken, missing_field, None)

    with pytest.raises(ValueError):
        await store.rebind_telegram_session(agent_id, broken)

    config = await store.get_runtime_config(agent_id)
    assert config.telegram_api_id == 12345
    assert config.telegram_api_hash == "encrypted-hash"
    assert config.telegram_session_string == "encrypted-session"

    async with db_session_factory() as session:
        row = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
    assert row is not None
    assert row.phone_number == "+79990000000"
    assert row.authorization_status == "authorized"
    assert row.last_error is None


async def test_rebind_telegram_session_unknown_agent_raises_key_error(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    store = DatabaseAgentStore(db_session_factory)

    with pytest.raises(KeyError):
        await store.rebind_telegram_session(
            uuid4(), _make_rebind_session(clean_slot.persona("empty").user_id)
        )


async def test_database_agent_store_creates_agent_session_and_runtime_config(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    onboarding_id = uuid4()

    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=onboarding_id,
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

    agents = await store.list_agents(owner_id=owner_id)
    runtime_config = await store.get_runtime_config(onboarding_id)
    await store.update_status(onboarding_id, AgentRuntimeState.RUNNING)
    updated_agents = await store.list_agents(owner_id=owner_id)

    assert agents[0].name == "Mimic"
    assert runtime_config.telegram_api_hash == "encrypted-hash"
    assert runtime_config.telegram_session_string == "encrypted-session"
    assert runtime_config.llm_model == DEFAULT_LLM_MODEL
    assert updated_agents[0].state is AgentRuntimeState.RUNNING


async def test_create_from_onboarding_twice_creates_two_agents(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("empty").user_id

    store = DatabaseAgentStore(db_session_factory)
    first_id = uuid4()
    second_id = uuid4()
    await store.create_from_onboarding(_make_session(owner_id, first_id, "First"))
    await store.create_from_onboarding(_make_session(owner_id, second_id, "Second"))

    agents = await store.list_agents(owner_id=owner_id)

    assert {agent.agent_id for agent in agents} == {first_id, second_id}


async def test_create_from_onboarding_keeps_agent_of_another_owner(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Issue #95: строка онбординга с id чужого агента не переприсваивает его."""
    owner_id = clean_slot.persona("full").user_id
    intruder_id = clean_slot.persona("code").user_id
    agent_id = uuid4()
    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(_make_session(owner_id, agent_id, "Легальный агент"))

    with pytest.raises(AgentOwnershipError):
        await store.create_from_onboarding(_make_session(intruder_id, agent_id, "Хакер"))

    kept = await store.list_agents(owner_id=owner_id)
    assert [(agent.agent_id, agent.name) for agent in kept] == [(agent_id, "Легальный агент")]
    assert await store.list_agents(owner_id=intruder_id) == []
    # Telegram-сессия жертвы остаётся его собственной.
    credentials = await store.get_telegram_rebind_credentials(agent_id)
    assert credentials.owner_id == owner_id
    assert credentials.api_hash_secret == "encrypted-hash"


async def test_create_from_onboarding_repeats_for_the_same_owner(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Повторная финализация тем же пользователем остаётся идемпотентной."""
    owner_id = clean_slot.persona("flow").user_id
    agent_id = uuid4()
    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(_make_session(owner_id, agent_id, "Mimic"))

    await store.create_from_onboarding(_make_session(owner_id, agent_id, "Mimic 2"))

    agents = await store.list_agents(owner_id=owner_id)
    assert [(agent.agent_id, agent.name) for agent in agents] == [(agent_id, "Mimic 2")]


async def test_delete_agent_removes_agent_and_onboarding_row_only_for_it(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("flow").user_id

    store = DatabaseAgentStore(db_session_factory)
    first_id = uuid4()
    second_id = uuid4()
    await store.create_from_onboarding(_make_session(owner_id, first_id, "First"))
    await store.create_from_onboarding(_make_session(owner_id, second_id, "Second"))

    async with db_session_factory() as session:
        # The originating onboarding row: id == agent id, finalize marker lost
        session.add(
            AgentOnboardingSessionModel(
                id=first_id,
                owner_id=owner_id,
                authorization_status=TelegramLoginStatus.AUTHORIZED.value,
            )
        )
        session.add(
            AgentOnboardingSessionModel(
                id=uuid4(),
                owner_id=owner_id,
                completed_agent_id=first_id,
                authorization_status=TelegramLoginStatus.AUTHORIZED.value,
            )
        )
        session.add(
            AgentOnboardingSessionModel(
                id=uuid4(),
                owner_id=owner_id,
                completed_agent_id=second_id,
                authorization_status=TelegramLoginStatus.AUTHORIZED.value,
            )
        )
        await session.commit()

    await store.delete_agent(first_id)

    agents = await store.list_agents(owner_id=owner_id)
    assert [agent.agent_id for agent in agents] == [second_id]

    async with db_session_factory() as session:
        onboarding_rows = (
            await session.scalars(
                select(AgentOnboardingSessionModel).where(
                    AgentOnboardingSessionModel.owner_id == owner_id
                )
            )
        ).all()
        assert len(onboarding_rows) == 1
        assert onboarding_rows[0].completed_agent_id == second_id

        telegram_sessions = (
            await session.scalars(
                select(TelegramSessionModel).where(TelegramSessionModel.agent_id == second_id)
            )
        ).all()
        assert [session_row.agent_id for session_row in telegram_sessions] == [second_id]


async def test_delete_agent_for_missing_agent_is_noop(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = DatabaseAgentStore(db_session_factory)

    await store.delete_agent(uuid4())


async def test_unknown_agent_status_does_not_break_listing(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """The DB enum has extra values (the `draft` default): one of them must
    not break the whole agent list / startup restore."""
    owner_id = clean_slot.persona("empty").user_id
    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(_make_session(owner_id, uuid4(), "Drafty"))

    async with db_session_factory() as session:
        await session.execute(
            update(AgentModel).where(AgentModel.owner_id == owner_id).values(status="draft")
        )
        await session.commit()

    agents = await store.list_agents(owner_id=owner_id)

    assert [agent.state for agent in agents] == [AgentRuntimeState.STOPPED]


async def test_database_conversation_groups_messages_and_tool_events(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    agent_id = uuid4()
    base = datetime(2026, 5, 19, 23, 30, tzinfo=UTC)
    async with db_session_factory() as session:
        session.add(
            AgentModel(
                id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                status=AgentRuntimeState.STOPPED.value,
                soul_prompt="Soul",
            )
        )
        await session.commit()
    async with db_session_factory() as session:
        session.add(
            AgentMessageModel(
                agent_id=agent_id,
                direction="incoming",
                role="user",
                content="hi",
                payload={"peer": "chat", "peer_name": "Ivan"},
                created_at=base,
            )
        )
        session.add(
            AgentEventModel(
                agent_id=agent_id,
                event_type="get_profile",
                status="succeeded",
                payload={"args": {"peer": "chat"}, "parent_peer": "chat"},
                created_at=base + timedelta(seconds=1),
                started_at=base,
                completed_at=base + timedelta(seconds=1),
            )
        )
        session.add(
            AgentMessageModel(
                agent_id=agent_id,
                direction="agent_response",
                role="assistant",
                content="hello",
                payload={"peer": "chat", "agent_name": "Mimic"},
                created_at=base + timedelta(seconds=2),
            )
        )
        # Orphan outgoing (proactive message, direction "outgoing")
        session.add(
            AgentMessageModel(
                agent_id=agent_id,
                direction="outgoing",
                role="assistant",
                content="proactive",
                payload={"peer": "chat", "agent_name": "Mimic"},
                created_at=base + timedelta(seconds=3),
            )
        )
        await session.commit()

    store = DatabaseAgentStore(db_session_factory)
    page = await store.get_conversation(agent_id=agent_id)
    turns = page.turns

    # Newest first: proactive outgoing, then the grouped both-turn.
    assert len(turns) == 2
    assert turns[0].direction == "outgoing"
    assert turns[0].outgoing == "proactive"
    grouped = turns[1]
    assert grouped.direction == "both"
    assert grouped.incoming == "hi"
    assert grouped.outgoing == "hello"
    assert len(grouped.tools) == 1
    assert grouped.tools[0].name == "get_profile"
    assert grouped.tools[0].duration_ms == 1000.0

    limited = await store.get_conversation(agent_id=agent_id, limit=1)
    assert len(limited.turns) == 1
    assert limited.turns[0].outgoing == "proactive"


async def test_runtime_config_carries_the_first_comment_setting(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Настройка живёт в JSON-колонке, и рантайм обязан видеть её как модель."""
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()

    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(_make_session(owner_id, agent_id, "Mimic"))

    async with db_session_factory() as session:
        await session.execute(
            update(AgentModel)
            .where(AgentModel.id == agent_id)
            .values(
                settings={
                    "first_comment": {
                        "enabled": True,
                        "variants": [
                            {"text": "Первый!"},
                            {"text": "  "},
                            {"text": "", "image_path": f"{agent_id}/u/pic.jpg"},
                        ],
                    }
                }
            )
        )
        await session.commit()

    config = await store.get_runtime_config(agent_id)

    assert config.first_comment.enabled is True
    # Пустой вариант отброшен: он не дал бы Телеграму что отправить.
    assert [variant.text for variant in config.first_comment.variants] == ["Первый!", ""]
    assert config.first_comment.variants[1].image_path == f"{agent_id}/u/pic.jpg"


async def test_runtime_config_defaults_first_comment_to_off(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()

    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(_make_session(owner_id, agent_id, "Mimic"))

    config = await store.get_runtime_config(agent_id)

    assert config.first_comment.is_active is False
