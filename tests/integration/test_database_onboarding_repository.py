from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import TelegramProxyConfig
from mimic42.core.onboarding import (
    OnboardingNotFoundError,
    OnboardingSession,
    TelegramCredentials,
    TelegramLoginStaleError,
    TelegramLoginStatus,
)
from mimic42.core.telegram_proxy import TelegramProxyAssignment
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.integrations.database_models import AgentOnboardingSessionModel
from mimic42.integrations.database_onboarding import DatabaseOnboardingRepository
from mimic42.testing import seed_agent
from mimic42.testing.slots import Slot


class _ProxyStore:
    def __init__(self, assignment: TelegramProxyAssignment | None) -> None:
        self.assignment = assignment
        self.allocate_calls = 0

    async def allocate(self, *, exclude: UUID | None = None) -> TelegramProxyAssignment | None:
        self.allocate_calls += 1
        return self.assignment

    async def load(self, proxy_id: UUID) -> TelegramProxyConfig:
        if self.assignment is None:
            raise AssertionError("proxy is not configured")
        return self.assignment.config

    async def mark_unavailable(self, proxy_id: UUID) -> None:
        raise AssertionError("healthy allocation must not cool the proxy")

    async def assignment_for_agent(self, agent_id: UUID) -> TelegramProxyAssignment | None:
        return None


async def test_database_onboarding_repository_maps_session_rows(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    repository = DatabaseOnboardingRepository(db_session_factory)
    session = OnboardingSession(
        onboarding_id=uuid4(),
        owner_id=clean_slot.persona("code").user_id,
        api_id=12345,
        api_hash_secret="encrypted-hash",
        phone_number="+79990000000",
        authorization_status=TelegramLoginStatus.AUTHORIZED,
        phone_code_hash_secret="encrypted-code-hash",
        session_secret="encrypted-session",
        name="Mimic",
        soul_prompt="Short replies",
    )

    await repository.create(session)
    # completed_agent_id ссылается на agents.id — сначала заводим агента,
    # как это делает finalize.
    await DatabaseAgentStore(db_session_factory).create_from_onboarding(session)
    session.completed_agent_id = session.onboarding_id
    session.applied_auth_generation = session.auth_generation
    loaded = await repository.get(session.onboarding_id)

    assert loaded == session


async def test_database_onboarding_repository_raises_when_missing(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = DatabaseOnboardingRepository(db_session_factory)

    with pytest.raises(OnboardingNotFoundError):
        await repository.get(uuid4())


async def test_database_onboarding_repository_finds_session_for_agent(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    repository = DatabaseOnboardingRepository(db_session_factory)
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()
    # Агент существует (FK completed_agent_id → agents.id), но его
    # онбординг-строка — отдельная, скрытая меткой.
    await seed_agent(
        DatabaseAgentStore(db_session_factory),
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="encrypted-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="encrypted-session",
            name="Mimic",
            soul_prompt="Short replies",
        ),
    )
    session = OnboardingSession(
        onboarding_id=uuid4(),
        owner_id=owner_id,
        api_id=12345,
        api_hash_secret="encrypted-hash",
        phone_number="+79990000000",
        authorization_status=TelegramLoginStatus.AUTHORIZED,
        session_secret="encrypted-session",
        name="Mimic",
        soul_prompt="Short replies",
        completed_agent_id=agent_id,
    )
    await repository.create(session)

    loaded = await repository.get_for_agent(agent_id)

    assert loaded.onboarding_id == session.onboarding_id
    assert loaded.completed_agent_id == agent_id
    with pytest.raises(OnboardingNotFoundError):
        await repository.get_for_agent(uuid4())


async def test_draft_settings_round_trip(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    repository = DatabaseOnboardingRepository(db_session_factory)
    session = OnboardingSession(
        onboarding_id=uuid4(),
        owner_id=clean_slot.persona("code").user_id,
        api_id=12345,
        api_hash_secret="encrypted-hash",
        phone_number="+79990000000",
        authorization_status=TelegramLoginStatus.AUTHORIZED,
        session_secret="encrypted-session",
        name="Mimic",
        soul_prompt="Short replies",
        settings={"enabled_tools": ["send_text_message", "view_image"]},
    )

    await repository.create(session)
    loaded = await repository.get(session.onboarding_id)

    assert loaded.settings == {"enabled_tools": ["send_text_message", "view_image"]}


@pytest.mark.parametrize("change", ["reset", "delete"])
async def test_auth_result_cannot_undo_a_browser_cancellation(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    change: str,
) -> None:
    repository = DatabaseOnboardingRepository(db_session_factory)
    draft = OnboardingSession(
        onboarding_id=uuid4(),
        owner_id=clean_slot.persona("code").user_id,
        authorization_status=TelegramLoginStatus.NOT_STARTED,
    )
    await repository.create(draft)
    async with db_session_factory() as db, db.begin():
        if change == "delete":
            await db.execute(
                delete(AgentOnboardingSessionModel).where(
                    AgentOnboardingSessionModel.id == draft.onboarding_id
                )
            )
        else:
            await db.execute(
                update(AgentOnboardingSessionModel)
                .where(AgentOnboardingSessionModel.id == draft.onboarding_id)
                .values(authorization_status="not_started")
            )

    with pytest.raises(TelegramLoginStaleError):
        await repository.record_auth(
            draft.authorization_ref(),
            status=TelegramLoginStatus.CODE_REQUESTED,
            phone_code_hash_secret="late-hash",
            session_secret="late-session",
        )

    async with db_session_factory() as db:
        current = await db.scalar(
            select(AgentOnboardingSessionModel).where(
                AgentOnboardingSessionModel.id == draft.onboarding_id
            )
        )
    if change == "delete":
        assert current is None
    else:
        assert current is not None
        assert current.authorization_status == "not_started"
        assert current.session_ciphertext is None


async def test_auth_result_preserves_browser_profile_and_settings_edits(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    repository = DatabaseOnboardingRepository(db_session_factory)
    draft = OnboardingSession(
        onboarding_id=uuid4(),
        owner_id=clean_slot.persona("code").user_id,
        authorization_status=TelegramLoginStatus.NOT_STARTED,
        name="Old",
    )
    await repository.create(draft)
    async with db_session_factory() as db, db.begin():
        await db.execute(
            update(AgentOnboardingSessionModel)
            .where(AgentOnboardingSessionModel.id == draft.onboarding_id)
            .values(
                agent_name="Edited", soul_prompt="Edited soul", settings={"model": "edited/model"}
            )
        )

    await repository.record_auth(
        draft.authorization_ref(),
        status=TelegramLoginStatus.CODE_REQUESTED,
        phone_code_hash_secret="code-hash",
        session_secret="partial-session",
    )

    current = await repository.get(draft.onboarding_id)
    assert current.name == "Edited"
    assert current.soul_prompt == "Edited soul"
    assert current.settings == {"model": "edited/model"}
    assert current.authorization_status is TelegramLoginStatus.CODE_REQUESTED


async def test_begin_login_allocates_a_proxy_before_saving_the_draft(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    proxy_id = uuid4()
    store = _ProxyStore(
        TelegramProxyAssignment(
            proxy_id=proxy_id,
            config=TelegramProxyConfig(protocol="socks5", host="proxy.example.test", port=1080),
        )
    )
    repository = DatabaseOnboardingRepository(db_session_factory, proxy_store=store)

    session = await repository.begin_login(
        TelegramCredentials(
            owner_id=clean_slot.persona("code").user_id,
            api_id=12345,
            api_hash="hash",
            phone_number="+79990000000",
        ),
        api_hash_secret="hash",
    )

    assert store.allocate_calls == 1
    assert session.proxy_id == proxy_id
    async with db_session_factory() as db:
        row = await db.get(AgentOnboardingSessionModel, session.onboarding_id)
    assert row is not None
    assert row.proxy_id == proxy_id


async def test_begin_login_keeps_an_existing_proxy_without_a_new_allocation(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    proxy_id = uuid4()
    draft = OnboardingSession(
        onboarding_id=uuid4(),
        owner_id=clean_slot.persona("code").user_id,
        authorization_status=TelegramLoginStatus.NOT_STARTED,
        proxy_id=proxy_id,
    )
    store = _ProxyStore(None)
    repository = DatabaseOnboardingRepository(db_session_factory, proxy_store=store)
    await repository.create(draft)

    session = await repository.begin_login(
        TelegramCredentials(
            owner_id=draft.owner_id,
            api_id=12345,
            api_hash="hash",
            phone_number="+79990000000",
        ),
        api_hash_secret="hash",
        onboarding_id=draft.onboarding_id,
    )

    assert store.allocate_calls == 0
    assert session.proxy_id == proxy_id
