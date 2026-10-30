from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from mimic42.core.admin import AdminProxyInUseError
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.crypto import FernetSecretCipher
from mimic42.core.onboarding import OnboardingSession, TelegramLoginStatus
from mimic42.integrations.database_admin import DatabaseAdminRepository
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.integrations.database_models import (
    AdminAuditLogModel,
    AgentOnboardingSessionModel,
    TelegramProxyModel,
    TelegramSessionModel,
)
from mimic42.integrations.database_proxies import DatabaseTelegramProxyStore
from mimic42.testing.slots import Slot, plain_dsn


def _cipher() -> FernetSecretCipher:
    return FernetSecretCipher(Fernet.generate_key().decode())


async def _agent(
    factory: async_sessionmaker[Any],
    owner_id: UUID,
    *,
    proxy_id: UUID | None = None,
    cipher: FernetSecretCipher | None = None,
) -> UUID:
    agent_id = uuid4()
    api_hash_secret = cipher.encrypt("hash") if cipher is not None else "encrypted-hash"
    session_secret = cipher.encrypt("session") if cipher is not None else "encrypted-session"
    await DatabaseAgentStore(factory).create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret=api_hash_secret,
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret=session_secret,
            name="Мимик",
            soul_prompt="Характер",
            proxy_id=proxy_id,
        )
    )
    return agent_id


async def _set_session_proxy(
    factory: async_sessionmaker[Any],
    agent_id: UUID,
    proxy_id: UUID | None,
) -> None:
    async with factory() as session, session.begin():
        telegram_session = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
        assert telegram_session is not None
        telegram_session.proxy_id = proxy_id


@pytest.mark.asyncio
async def test_admin_proxy_crud_encrypts_password_and_audits(
    admin_db_factory: async_sessionmaker[Any],
    test_slot: Slot,
) -> None:
    cipher = _cipher()
    repository = DatabaseAdminRepository(admin_db_factory, cipher=cipher)
    actor_id = test_slot.persona("full").user_id
    raw_password = "integration-proxy-password"

    created = await repository.create_proxy(
        {
            "label": "Основной",
            "protocol": "socks5",
            "host": "proxy.example.test",
            "port": 1080,
            "username": "mimic",
            "password": raw_password,
            "is_active": True,
        },
        actor_user_id=actor_id,
    )

    async with admin_db_factory() as session:
        stored = await session.get(TelegramProxyModel, created.id)
    assert stored is not None
    assert stored.password_ciphertext is not None
    assert stored.password_ciphertext != raw_password
    assert cipher.decrypt(stored.password_ciphertext) == raw_password
    assert created.has_password is True

    updated = await repository.update_proxy(
        created.id,
        {"label": "Резервный", "password": "new-password"},
        actor_user_id=actor_id,
    )
    assert updated.label == "Резервный"
    assert updated.has_password is True

    reader = await repository.read_proxy_config(created.id)
    assert reader.username == "mimic"
    assert reader.password is not None
    assert reader.password.get_secret_value() == "new-password"

    page = await repository.list_proxies(page=1, page_size=100)
    assert created.id in {proxy.id for proxy in page.items}

    await repository.delete_proxy(created.id, actor_user_id=actor_id)
    async with admin_db_factory() as session:
        assert await session.get(TelegramProxyModel, created.id) is None
        actions = list(
            await session.scalars(
                select(AdminAuditLogModel.action)
                .where(
                    AdminAuditLogModel.actor_user_id == actor_id,
                    AdminAuditLogModel.object_id == created.id,
                )
                .order_by(AdminAuditLogModel.created_at, AdminAuditLogModel.id)
            )
        )
    assert len(actions) == 3
    assert set(actions) == {"proxy.created", "proxy.updated", "proxy.deleted"}
    assert raw_password not in repr(actions)


@pytest.mark.asyncio
async def test_assigned_proxy_cannot_be_deleted_and_is_visible_on_the_agent(
    admin_db_factory: async_sessionmaker[Any],
    test_slot: Slot,
) -> None:
    cipher = _cipher()
    repository = DatabaseAdminRepository(admin_db_factory, cipher=cipher)
    actor_id = test_slot.persona("full").user_id
    owner_id = test_slot.persona("full").user_id
    proxy = await repository.create_proxy(
        {
            "label": "Рабочий",
            "protocol": "http",
            "host": "proxy.example.test",
            "port": 3128,
            "username": None,
            "password": None,
            "is_active": True,
        },
        actor_user_id=actor_id,
    )
    agent_id = await _agent(admin_db_factory, owner_id)

    assigned = await repository.assign_agent_proxy(
        agent_id,
        proxy.id,
        actor_user_id=actor_id,
    )
    assert assigned is not None
    assert assigned.id == proxy.id

    detail = await repository.get_user(
        owner_id,
        page=1,
        page_size=100,
        runtime_states={},
    )
    agent = next(item for item in detail.agents.items if item.agent_id == agent_id)
    assert agent.proxy is not None
    assert agent.proxy.id == proxy.id
    assert agent.state is AgentRuntimeState.STOPPED

    with pytest.raises(AdminProxyInUseError):
        await repository.delete_proxy(proxy.id, actor_user_id=actor_id)

    await repository.assign_agent_proxy(agent_id, None, actor_user_id=actor_id)
    async with admin_db_factory() as session:
        session_row = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
    assert session_row is not None
    assert session_row.proxy_id is None


@pytest.mark.asyncio
async def test_allocation_prefers_the_least_loaded_active_proxy(
    admin_db_factory: async_sessionmaker[Any],
    test_slot: Slot,
) -> None:
    cipher = _cipher()
    repository = DatabaseAdminRepository(admin_db_factory, cipher=cipher)
    actor_id = test_slot.persona("full").user_id
    older = await repository.create_proxy(
        {
            "label": "Старый",
            "protocol": "socks5",
            "host": "old.example.test",
            "port": 1080,
            "username": None,
            "password": None,
            "is_active": True,
        },
        actor_user_id=actor_id,
    )
    newer = await repository.create_proxy(
        {
            "label": "Новый",
            "protocol": "socks5",
            "host": "new.example.test",
            "port": 1080,
            "username": "mimic",
            "password": "secret",
            "is_active": True,
        },
        actor_user_id=actor_id,
    )
    async with admin_db_factory() as session, session.begin():
        stored_older = await session.get(TelegramProxyModel, older.id)
        stored_newer = await session.get(TelegramProxyModel, newer.id)
        assert stored_older is not None and stored_newer is not None
        stored_older.created_at = datetime.now(UTC) - timedelta(days=1)
        stored_newer.created_at = datetime.now(UTC)

    owner_id = test_slot.persona("code").user_id
    for _ in range(2):
        agent_id = await _agent(admin_db_factory, owner_id)
        await _set_session_proxy(admin_db_factory, agent_id, older.id)

    store = DatabaseTelegramProxyStore(admin_db_factory, cipher=cipher)
    assignment = await store.allocate()

    assert assignment is not None
    assert assignment.proxy_id == newer.id
    assert assignment.config.password is not None
    assert assignment.config.password.get_secret_value() == "secret"

    newer_agent_id = await _agent(admin_db_factory, owner_id)
    await _set_session_proxy(admin_db_factory, newer_agent_id, newer.id)
    async with admin_db_factory() as session, session.begin():
        stored_newer = await session.get(TelegramProxyModel, newer.id)
        assert stored_newer is not None
        stored_newer.is_active = False

    # Отключённый прокси не получают новые мимики, но старые им продолжают
    # пользоваться: assignment_for_agent не смотрит на is_active.
    disabled_assignment = await store.assignment_for_agent(newer_agent_id)
    assert disabled_assignment is not None
    assert disabled_assignment.proxy_id == newer.id

    fallback = await store.allocate()
    assert fallback is not None
    assert fallback.proxy_id == older.id


@pytest.mark.asyncio
async def test_rebind_persists_the_proxy_used_for_the_login(
    admin_db_factory: async_sessionmaker[Any],
    test_slot: Slot,
) -> None:
    owner_id = test_slot.persona("full").user_id
    proxy_id = uuid4()
    async with admin_db_factory() as session, session.begin():
        session.add(
            TelegramProxyModel(
                id=proxy_id,
                label="Для перепривязки",
                protocol="socks5",
                host="proxy.example.test",
                port=1080,
                is_active=True,
                created_by=owner_id,
            )
        )
    agent_id = await _agent(admin_db_factory, owner_id)
    store = DatabaseAgentStore(admin_db_factory)

    await store.rebind_telegram_session(
        agent_id,
        OnboardingSession(
            onboarding_id=uuid4(),
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="encrypted-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="new-session",
            proxy_id=proxy_id,
        ),
    )

    async with admin_db_factory() as session:
        telegram_session = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
    assert telegram_session is not None
    assert telegram_session.proxy_id == proxy_id


@pytest.mark.asyncio
async def test_repeated_finalization_does_not_roll_back_a_manual_proxy_change(
    admin_db_factory: async_sessionmaker[Any],
    test_slot: Slot,
) -> None:
    cipher = _cipher()
    owner_id = test_slot.persona("full").user_id
    actor_id = test_slot.persona("full").user_id
    repository = DatabaseAdminRepository(admin_db_factory, cipher=cipher)
    initial = await repository.create_proxy(
        {
            "label": "Исходный",
            "protocol": "socks5",
            "host": "initial.example.test",
            "port": 1080,
            "username": None,
            "password": None,
            "is_active": True,
        },
        actor_user_id=actor_id,
    )
    replacement = await repository.create_proxy(
        {
            "label": "Новый",
            "protocol": "socks5",
            "host": "replacement.example.test",
            "port": 1080,
            "username": None,
            "password": None,
            "is_active": True,
        },
        actor_user_id=actor_id,
    )
    agent_id = await _agent(admin_db_factory, owner_id, proxy_id=initial.id, cipher=cipher)
    await repository.assign_agent_proxy(
        agent_id,
        replacement.id,
        actor_user_id=actor_id,
    )

    await DatabaseAgentStore(admin_db_factory, cipher=cipher).create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret=cipher.encrypt("hash"),
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret=cipher.encrypt("session"),
            name="Мимик",
            soul_prompt="Характер",
            proxy_id=initial.id,
        )
    )

    async with admin_db_factory() as session:
        telegram_session = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
    assert telegram_session is not None
    assert telegram_session.proxy_id == replacement.id


@pytest.mark.asyncio
async def test_proxy_in_a_pending_onboarding_cannot_be_deleted(
    admin_db_factory: async_sessionmaker[Any],
    test_slot: Slot,
) -> None:
    actor_id = test_slot.persona("full").user_id
    owner_id = test_slot.persona("code").user_id
    repository = DatabaseAdminRepository(admin_db_factory, cipher=_cipher())
    proxy = await repository.create_proxy(
        {
            "label": "В онбординге",
            "protocol": "socks5",
            "host": "onboarding.example.test",
            "port": 1080,
            "username": None,
            "password": None,
            "is_active": True,
        },
        actor_user_id=actor_id,
    )
    async with admin_db_factory() as session, session.begin():
        session.add(
            AgentOnboardingSessionModel(
                id=uuid4(),
                owner_id=owner_id,
                authorization_status="code_requested",
                proxy_id=proxy.id,
            )
        )

    page = await repository.list_proxies(page=1, page_size=100)
    listed = next(item for item in page.items if item.id == proxy.id)
    assert listed.agents_total == 0
    assert listed.onboarding_total == 1

    with pytest.raises(AdminProxyInUseError):
        await repository.delete_proxy(proxy.id, actor_user_id=actor_id)


@pytest.mark.asyncio
async def test_runtime_config_contains_the_assigned_proxy(
    admin_db_factory: async_sessionmaker[Any],
    test_slot: Slot,
) -> None:
    cipher = _cipher()
    repository = DatabaseAdminRepository(admin_db_factory, cipher=cipher)
    actor_id = test_slot.persona("full").user_id
    owner_id = test_slot.persona("full").user_id
    proxy = await repository.create_proxy(
        {
            "label": "Рабочий",
            "protocol": "socks5",
            "host": "proxy.example.test",
            "port": 1080,
            "username": "mimic",
            "password": "secret",
            "is_active": True,
        },
        actor_user_id=actor_id,
    )
    agent_id = await _agent(
        admin_db_factory,
        owner_id,
        proxy_id=proxy.id,
        cipher=cipher,
    )

    config = await DatabaseAgentStore(admin_db_factory, cipher=cipher).get_runtime_config(agent_id)

    assert config.telegram_proxy is not None
    assert config.telegram_proxy.protocol == "socks5"
    assert config.telegram_proxy.host == "proxy.example.test"
    assert config.telegram_proxy.username == "mimic"
    assert config.telegram_proxy.password is not None
    assert config.telegram_proxy.password.get_secret_value() == "secret"


@pytest.mark.asyncio
async def test_client_roles_cannot_read_proxies_or_write_assignments(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        assert (
            await connection.fetchval(
                "select has_table_privilege('authenticated', 'public.telegram_proxies', 'select')"
            )
            is False
        )
        assert (
            await connection.fetchval(
                "select has_column_privilege("
                "'authenticated', 'public.telegram_sessions', 'proxy_id', 'update')"
            )
            is False
        )
        assert (
            await connection.fetchval(
                "select has_column_privilege("
                "'authenticated', 'public.agent_onboarding_sessions', 'proxy_id', 'update')"
            )
            is False
        )
    finally:
        await connection.close()
