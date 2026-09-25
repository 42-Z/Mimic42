"""Клиентские роли не могут подделать онбординг-сессию (issue #95).

Проверяется путь браузера: PostgREST выполняет запросы от роли ``authenticated``
с JWT-клеймами пользователя (в тестах роль и клеймы выставляются так же, как их
ставит PostgREST). Бэкенд пишет в таблицу своей ролью и RLS не затрагивается.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.onboarding import OnboardingSession, TelegramLoginStatus
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.testing.slots import CONNECT_TIMEOUT_SECONDS, Slot, plain_dsn

VICTIM_AGENT_NAME = "Легальный агент"


async def _act_as_client(connection: asyncpg.Connection, user_id: UUID) -> None:
    """Роль authenticated + клеймы пользователя — как их видит PostgREST."""
    await connection.execute("set local role authenticated")
    await connection.execute(
        "select set_config('request.jwt.claims', $1, true)",
        f'{{"sub":"{user_id}","role":"authenticated"}}',
    )
    await connection.execute("select set_config('request.jwt.claim.sub', $1, true)", str(user_id))


async def _seed_victim_agent(
    db_session_factory: async_sessionmaker[AsyncSession],
    dsn: str,
    owner_id: UUID,
) -> UUID:
    """Агент жертвы вместе с завершённой строкой онбординга (id == id агента)."""
    agent_id = uuid4()
    await DatabaseAgentStore(db_session_factory).create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="encrypted-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="encrypted-session",
            name=VICTIM_AGENT_NAME,
            soul_prompt="Честный характер",
        )
    )
    connection = await asyncpg.connect(plain_dsn(dsn), timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        await connection.execute(
            "insert into public.agent_onboarding_sessions "
            "(id, owner_id, agent_name, soul_prompt, authorization_status, completed_agent_id) "
            "values ($1, $2, $3, 'Честный характер', 'authorized', $1)",
            agent_id,
            owner_id,
            VICTIM_AGENT_NAME,
        )
    finally:
        await connection.close()
    return agent_id


async def _insert_draft(connection: asyncpg.Connection, owner_id: UUID, name: str) -> UUID:
    return await connection.fetchval(
        "insert into public.agent_onboarding_sessions "
        "(owner_id, agent_name, soul_prompt, updated_at) "
        "values ($1, $2, 'Характер взломщика', now()) returning id",
        owner_id,
        name,
    )


async def test_client_cannot_choose_row_identity(
    test_dsn: str,
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Id строки — это id будущего агента: клиенту его не выдают."""
    victim = clean_slot.persona("full")
    intruder = clean_slot.persona("code")
    agent_id = await _seed_victim_agent(db_session_factory, test_dsn, victim.user_id)
    connection = await asyncpg.connect(plain_dsn(test_dsn), timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        async with connection.transaction():
            await _act_as_client(connection, intruder.user_id)

            with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
                async with connection.transaction():
                    await connection.execute(
                        "insert into public.agent_onboarding_sessions "
                        "(id, owner_id, agent_name, soul_prompt, authorization_status) "
                        "values ($1, $2, 'Хакер', 'Характер взломщика', 'authorized')",
                        agent_id,
                        intruder.user_id,
                    )

            draft_id = await _insert_draft(connection, intruder.user_id, "Хакер")

            with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
                async with connection.transaction():
                    await connection.execute(
                        "update public.agent_onboarding_sessions set id = $1 where id = $2",
                        agent_id,
                        draft_id,
                    )

            with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
                async with connection.transaction():
                    await connection.execute(
                        "update public.agent_onboarding_sessions "
                        "set completed_agent_id = $1 where id = $2",
                        agent_id,
                        draft_id,
                    )
    finally:
        await connection.close()

    check = await asyncpg.connect(plain_dsn(test_dsn), timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        assert (
            await check.fetchval(
                "select count(*) from public.agent_onboarding_sessions where id = $1",
                agent_id,
            )
            == 1
        )
    finally:
        await check.close()


async def test_client_cannot_authorize_itself_or_write_telegram_secrets(
    test_dsn: str,
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Авторизацию выдаёт бэкенд после входа в Telegram — не клиент."""
    victim = clean_slot.persona("full")
    intruder = clean_slot.persona("code")
    await _seed_victim_agent(db_session_factory, test_dsn, victim.user_id)
    connection = await asyncpg.connect(plain_dsn(test_dsn), timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        async with connection.transaction():
            await _act_as_client(connection, intruder.user_id)
            draft_id = await _insert_draft(connection, intruder.user_id, "Хакер")

            # Колонка обновляемая (её сбрасывает кнопка «Назад»), поэтому
            # повышение статуса держит политика, а не гранты.
            with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
                async with connection.transaction():
                    await connection.execute(
                        "update public.agent_onboarding_sessions "
                        "set authorization_status = 'authorized' where id = $1",
                        draft_id,
                    )

            with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
                async with connection.transaction():
                    await connection.execute(
                        "update public.agent_onboarding_sessions "
                        "set session_ciphertext = 'forged-session' where id = $1",
                        draft_id,
                    )

            with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
                async with connection.transaction():
                    await connection.execute(
                        "update public.agent_onboarding_sessions "
                        "set api_hash_ciphertext = 'forged-hash' where id = $1",
                        draft_id,
                    )
    finally:
        await connection.close()


async def test_client_draft_lifecycle_still_works(
    test_dsn: str,
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Визард не сломан: черновик создаётся, правится и сбрасывается, чужие
    строки остаются невидимыми."""
    victim = clean_slot.persona("full")
    client = clean_slot.persona("code")
    agent_id = await _seed_victim_agent(db_session_factory, test_dsn, victim.user_id)
    connection = await asyncpg.connect(plain_dsn(test_dsn), timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        async with connection.transaction():
            await _act_as_client(connection, client.user_id)

            draft_id = await _insert_draft(connection, client.user_id, "Мой агент")
            await connection.execute(
                "update public.agent_onboarding_sessions "
                "set soul_prompt = 'Спокойный характер', updated_at = now() where id = $1",
                draft_id,
            )

        # Так бэкенд отмечает отправку кода — своей ролью, без RLS.
        async with connection.transaction():
            await connection.execute(
                "update public.agent_onboarding_sessions "
                "set authorization_status = 'code_requested' where id = $1",
                draft_id,
            )

        async with connection.transaction():
            await _act_as_client(connection, client.user_id)
            # ...а кнопка «Назад» возвращает шаг выбора номера.
            await connection.execute(
                "update public.agent_onboarding_sessions "
                "set authorization_status = 'not_started' where id = $1",
                draft_id,
            )

            assert (
                await connection.fetchval(
                    "select count(*) from public.agent_onboarding_sessions where owner_id = $1",
                    client.user_id,
                )
                == 1
            )
            # Чужая строка онбординга не видна и не трогается.
            assert (
                await connection.fetchval(
                    "select count(*) from public.agent_onboarding_sessions where id = $1",
                    agent_id,
                )
                == 0
            )
            assert (
                await connection.execute(
                    "update public.agent_onboarding_sessions "
                    "set agent_name = 'Хакер' where id = $1",
                    agent_id,
                )
                == "UPDATE 0"
            )

            await connection.execute(
                "delete from public.agent_onboarding_sessions where id = $1", draft_id
            )
    finally:
        await connection.close()


async def test_policies_reject_forged_rows_even_with_extra_grants(
    test_dsn: str,
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Оборона в глубину: политики отклоняют подделку, даже если широкие гранты
    на колонки однажды вернут."""
    victim = clean_slot.persona("full")
    intruder = clean_slot.persona("code")
    agent_id = await _seed_victim_agent(db_session_factory, test_dsn, victim.user_id)
    connection = await asyncpg.connect(plain_dsn(test_dsn), timeout=CONNECT_TIMEOUT_SECONDS)
    transaction = connection.transaction()
    await transaction.start()
    try:
        await connection.execute(
            "grant insert (id, completed_agent_id, authorization_status), "
            "update (id, completed_agent_id, authorization_status) "
            "on table public.agent_onboarding_sessions to authenticated"
        )
        await _act_as_client(connection, intruder.user_id)

        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
            async with connection.transaction():
                await connection.execute(
                    "insert into public.agent_onboarding_sessions "
                    "(id, owner_id, agent_name, soul_prompt, "
                    "completed_agent_id, authorization_status) "
                    "values ($1, $2, 'Хакер', 'Характер взломщика', $1, 'authorized')",
                    agent_id,
                    intruder.user_id,
                )

        draft_id = await _insert_draft(connection, intruder.user_id, "Хакер")
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
            async with connection.transaction():
                await connection.execute(
                    "update public.agent_onboarding_sessions "
                    "set authorization_status = 'authorized' where id = $1",
                    draft_id,
                )
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
            async with connection.transaction():
                await connection.execute(
                    "update public.agent_onboarding_sessions "
                    "set completed_agent_id = $1 where id = $2",
                    agent_id,
                    draft_id,
                )
    finally:
        # Гранты и черновик живут только внутри этой транзакции.
        await transaction.rollback()

    assert not await connection.fetchval(
        "select has_column_privilege('authenticated', 'public.agent_onboarding_sessions', "
        "'id', 'insert')"
    )
    await connection.close()
