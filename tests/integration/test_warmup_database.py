from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.warmup import (
    EVENT_OPENER_FAILED,
    EVENT_OPENER_SENT,
    EVENT_RECOVERED,
    EVENT_RECOVERY_STARTED,
    EVENT_RESTRICTED,
    WarmupState,
)
from mimic42.integrations.database_models import AgentEventModel, AgentModel
from mimic42.integrations.database_warmup import DatabaseWarmupHistory, DatabaseWarmupStateStore
from mimic42.testing.slots import Slot


async def _create_agent(
    db_session_factory: async_sessionmaker[AsyncSession], owner_id: UUID
) -> UUID:
    agent_id = uuid4()
    async with db_session_factory() as session:
        session.add(
            AgentModel(
                id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                status=AgentRuntimeState.RUNNING.value,
                soul_prompt="Soul",
            )
        )
        await session.commit()
    return agent_id


async def _add_event(
    db_session_factory: async_sessionmaker[AsyncSession],
    agent_id: UUID,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    async with db_session_factory() as session:
        session.add(
            AgentEventModel(
                agent_id=agent_id,
                event_type=event_type,
                status="succeeded",
                payload=payload or {},
            )
        )
        await session.commit()


async def _count_events(
    db_session_factory: async_sessionmaker[AsyncSession], agent_id: UUID, event_type: str
) -> int:
    async with db_session_factory() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(AgentEventModel)
                .where(
                    AgentEventModel.agent_id == agent_id, AgentEventModel.event_type == event_type
                )
            )
            or 0
        )


async def test_restriction_state_lives_in_columns_and_survives_a_stale_settings_write(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    agent_id = await _create_agent(db_session_factory, clean_slot.persona("twofa").user_id)
    store = DatabaseWarmupStateStore(db_session_factory)

    assert await store.load(agent_id) == WarmupState()

    await store.record(agent_id, EVENT_RESTRICTED)
    restricted = await store.load(agent_id)
    assert restricted.restricted_at is not None and restricted.recovery is False

    await store.record(agent_id, EVENT_RECOVERY_STARTED)
    assert (await store.load(agent_id)).recovery is True

    # Форма настроек перезаписывает agents.settings целиком, колонки состояния не трогает.
    async with db_session_factory() as session:
        agent = await session.get(AgentModel, agent_id)
        assert agent is not None
        agent.settings = {"warmup": {"enabled": True}}
        await session.commit()
    after_form = await store.load(agent_id)
    assert after_form.restricted_at == restricted.restricted_at
    assert after_form.recovery is True

    await store.record(agent_id, EVENT_RECOVERED)
    assert await store.load(agent_id) == WarmupState()


async def test_transitions_are_idempotent_and_respect_the_order(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    agent_id = await _create_agent(db_session_factory, clean_slot.persona("twofa").user_id)
    store = DatabaseWarmupStateStore(db_session_factory)

    # Восстанавливать и снимать нечего, пока аккаунт не ограничен.
    await store.record(agent_id, EVENT_RECOVERY_STARTED)
    await store.record(agent_id, EVENT_RECOVERED)
    assert await store.load(agent_id) == WarmupState()

    await store.record(agent_id, EVENT_RESTRICTED)
    first = await store.load(agent_id)
    await store.record(agent_id, EVENT_RESTRICTED)
    await store.record(agent_id, EVENT_RECOVERY_STARTED)
    await store.record(agent_id, EVENT_RECOVERY_STARTED)

    state = await store.load(agent_id)
    assert state.restricted_at == first.restricted_at and state.recovery is True
    # Повтор того же перехода не пишет второго события в ленту.
    assert await _count_events(db_session_factory, agent_id, EVENT_RESTRICTED) == 1
    assert await _count_events(db_session_factory, agent_id, EVENT_RECOVERY_STARTED) == 1
    assert await _count_events(db_session_factory, agent_id, EVENT_RECOVERED) == 0


async def test_database_refuses_recovery_without_restriction(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    agent_id = await _create_agent(db_session_factory, clean_slot.persona("twofa").user_id)

    async with db_session_factory() as session:
        agent = await session.get(AgentModel, agent_id)
        assert agent is not None
        agent.warmup_recovery = True
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_history_counts_attempts_of_the_sender_and_of_the_recipient(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    helper = await _create_agent(db_session_factory, owner_id)
    limited = await _create_agent(db_session_factory, owner_id)
    history = DatabaseWarmupHistory(db_session_factory)
    since = datetime.now(UTC) - timedelta(hours=1)
    payload = {"partner_agent_id": str(limited), "text": "привет"}

    await _add_event(db_session_factory, helper, EVENT_OPENER_SENT, payload)
    await _add_event(db_session_factory, helper, EVENT_OPENER_FAILED, {**payload, "text": "ку"})
    await _add_event(db_session_factory, helper, EVENT_RESTRICTED)

    # Ограничение — переход состояния, а не попытка; неудача и успех считаются обе.
    assert len(await history.attempt_times_since(helper, since)) == 2
    assert len(await history.received_times_since(limited, since)) == 2
    assert await history.received_times_since(helper, since) == []
    assert await history.used_openers(helper) == ["привет"]
    assert await history.recent_partners(helper) == [limited]
    assert await history.attempt_times_since(helper, datetime.now(UTC) + timedelta(hours=1)) == []
