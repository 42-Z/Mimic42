"""Схема атак: форма лимита, уникальность живого участия, каскады и статусы."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.integrations.database_models import (
    AgentModel,
    AttackAgentModel,
    AttackModel,
)
from mimic42.testing.slots import Slot

CLOSED_AT = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
EXITED_AT = datetime(2026, 11, 16, 12, 5, tzinfo=UTC)


@pytest.fixture(autouse=True)
async def _clean_attacks(
    clean_slot: Slot,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """purge_slot_data чистит агентов, но про атаки не знает."""
    async with db_session_factory() as session:
        await session.execute(
            delete(AttackModel).where(
                AttackModel.owner_id.in_([persona.user_id for persona in clean_slot.personas])
            )
        )
        await session.commit()


def _attack_row(owner_id: UUID, **overrides: Any) -> AttackModel:
    values: dict[str, Any] = {
        "owner_id": owner_id,
        "target_link": "https://t.me/example/412",
        "target_channel_peer": "example",
        "target_message_id": 412,
        "texts": ["Участвую!"],
        "media_paths": [],
        "limit_type": "messages",
        "limit_value": 40,
    }
    values.update(overrides)
    return AttackModel(**values)


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
                status=AgentRuntimeState.STOPPED.value,
                soul_prompt="Soul",
            )
        )
        await session.commit()
    return agent_id


async def _insert(
    db_session_factory: async_sessionmaker[AsyncSession],
    row: AttackModel | AttackAgentModel,
) -> UUID:
    async with db_session_factory() as session:
        session.add(row)
        await session.commit()
    return row.id


async def _expect_integrity_error(
    db_session_factory: async_sessionmaker[AsyncSession],
    row: AttackModel | AttackAgentModel,
) -> None:
    async with db_session_factory() as session:
        session.add(row)
        with pytest.raises(IntegrityError):
            await session.commit()


async def _count_participations(
    db_session_factory: async_sessionmaker[AsyncSession], attack_id: UUID
) -> int:
    async with db_session_factory() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(AttackAgentModel)
                .where(AttackAgentModel.attack_id == attack_id)
            )
            or 0
        )


async def test_limit_type_stores_messages_or_minutes(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    messages_id = await _insert(
        db_session_factory, _attack_row(owner_id, limit_type="messages", limit_value=30)
    )
    minutes_id = await _insert(
        db_session_factory, _attack_row(owner_id, limit_type="minutes", limit_value=5)
    )

    async with db_session_factory() as session:
        limits = {
            attack.id: (attack.limit_type, attack.limit_value)
            for attack in await session.scalars(
                select(AttackModel).where(AttackModel.id.in_([messages_id, minutes_id]))
            )
        }
    assert limits == {messages_id: ("messages", 30), minutes_id: ("minutes", 5)}


async def test_limit_value_must_be_positive(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id

    await _expect_integrity_error(
        db_session_factory, _attack_row(owner_id, limit_type="messages", limit_value=0)
    )
    await _expect_integrity_error(
        db_session_factory, _attack_row(owner_id, limit_type="minutes", limit_value=-1)
    )


async def test_running_attack_requires_started_at(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id

    await _expect_integrity_error(db_session_factory, _attack_row(owner_id, status="running"))
    await _insert(
        db_session_factory,
        _attack_row(owner_id, status="running", started_at=CLOSED_AT),
    )


@pytest.mark.parametrize("status", ["finished", "cancelled"])
@pytest.mark.parametrize(
    ("finished_at", "end_reason", "valid"),
    [
        (None, None, False),
        (None, "limit_reached", False),
        (CLOSED_AT, None, False),
        (CLOSED_AT, "limit_reached", True),
    ],
)
async def test_closed_attack_requires_finished_at_and_end_reason(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    status: str,
    finished_at: datetime | None,
    end_reason: str | None,
    valid: bool,
) -> None:
    row = _attack_row(
        clean_slot.persona("twofa").user_id,
        status=status,
        finished_at=finished_at,
        end_reason=end_reason,
    )
    if valid:
        await _insert(db_session_factory, row)
    else:
        await _expect_integrity_error(db_session_factory, row)


async def test_sent_count_cannot_exceed_claimed_count(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id

    await _expect_integrity_error(
        db_session_factory, _attack_row(owner_id, sent_count=1, claimed_count=0)
    )
    await _insert(db_session_factory, _attack_row(owner_id, sent_count=1, claimed_count=1))


@pytest.mark.parametrize("second_status", ["assigned", "active"])
async def test_agent_cannot_hold_two_live_participations(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    second_status: str,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    first_attack = await _insert(db_session_factory, _attack_row(owner_id))
    second_attack = await _insert(db_session_factory, _attack_row(owner_id))
    agent_id = await _create_agent(db_session_factory, owner_id)
    await _insert(
        db_session_factory,
        AttackAgentModel(attack_id=first_attack, agent_id=agent_id, status="assigned"),
    )

    await _expect_integrity_error(
        db_session_factory,
        AttackAgentModel(attack_id=second_attack, agent_id=agent_id, status=second_status),
    )


async def test_exited_participation_releases_the_agent(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    first_attack = await _insert(db_session_factory, _attack_row(owner_id))
    second_attack = await _insert(db_session_factory, _attack_row(owner_id))
    agent_id = await _create_agent(db_session_factory, owner_id)
    await _insert(
        db_session_factory,
        AttackAgentModel(
            attack_id=first_attack,
            agent_id=agent_id,
            status="exited",
            exit_reason="paused",
            exited_at=EXITED_AT,
        ),
    )

    new_participation = await _insert(
        db_session_factory,
        AttackAgentModel(attack_id=second_attack, agent_id=agent_id, status="assigned"),
    )

    async with db_session_factory() as session:
        stored = await session.get(AttackAgentModel, new_participation)
    assert stored is not None and stored.attack_id == second_attack and stored.status == "assigned"


@pytest.mark.parametrize(
    ("exit_reason", "exited_at", "valid"),
    [
        (None, None, False),
        (None, EXITED_AT, False),
        ("paused", None, False),
        ("paused", EXITED_AT, True),
    ],
)
async def test_exited_participation_requires_reason_and_time(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    exit_reason: str | None,
    exited_at: datetime | None,
    valid: bool,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    attack_id = await _insert(db_session_factory, _attack_row(owner_id))
    agent_id = await _create_agent(db_session_factory, owner_id)
    row = AttackAgentModel(
        attack_id=attack_id,
        agent_id=agent_id,
        status="exited",
        exit_reason=exit_reason,
        exited_at=exited_at,
    )
    if valid:
        await _insert(db_session_factory, row)
    else:
        await _expect_integrity_error(db_session_factory, row)


@pytest.mark.parametrize(
    ("pending_random_id", "pending_text", "valid"),
    [
        (None, None, True),
        (42, None, False),
        (None, "Участвую!", False),
        (42, "Участвую!", True),
    ],
)
async def test_pending_reservation_keeps_random_id_and_text_together(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    pending_random_id: int | None,
    pending_text: str | None,
    valid: bool,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    attack_id = await _insert(db_session_factory, _attack_row(owner_id))
    agent_id = await _create_agent(db_session_factory, owner_id)
    row = AttackAgentModel(
        attack_id=attack_id,
        agent_id=agent_id,
        pending_random_id=pending_random_id,
        pending_text=pending_text,
        pending_count=1 if pending_random_id is not None else 0,
    )
    if valid:
        await _insert(db_session_factory, row)
    else:
        await _expect_integrity_error(db_session_factory, row)


@pytest.mark.parametrize(
    ("pending_random_id", "pending_count", "valid"),
    [
        (None, 0, True),
        (None, 1, False),
        (42, 0, False),
        (42, 1, True),
    ],
)
async def test_pending_reservation_count_matches_the_random_id(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    pending_random_id: int | None,
    pending_count: int,
    valid: bool,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    attack_id = await _insert(db_session_factory, _attack_row(owner_id))
    agent_id = await _create_agent(db_session_factory, owner_id)
    row = AttackAgentModel(
        attack_id=attack_id,
        agent_id=agent_id,
        pending_random_id=pending_random_id,
        pending_text="Участвую!" if pending_random_id is not None else None,
        pending_count=pending_count,
    )
    if valid:
        await _insert(db_session_factory, row)
    else:
        await _expect_integrity_error(db_session_factory, row)


async def test_deleting_an_attack_deletes_its_participations(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    attack_id = await _insert(db_session_factory, _attack_row(owner_id))
    agent_id = await _create_agent(db_session_factory, owner_id)
    await _insert(db_session_factory, AttackAgentModel(attack_id=attack_id, agent_id=agent_id))

    async with db_session_factory() as session:
        attack = await session.get(AttackModel, attack_id)
        assert attack is not None
        await session.delete(attack)
        await session.commit()

    assert await _count_participations(db_session_factory, attack_id) == 0


async def test_deleting_an_agent_deletes_its_participations(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    attack_id = await _insert(db_session_factory, _attack_row(owner_id))
    agent_id = await _create_agent(db_session_factory, owner_id)
    await _insert(db_session_factory, AttackAgentModel(attack_id=attack_id, agent_id=agent_id))

    async with db_session_factory() as session:
        agent = await session.get(AgentModel, agent_id)
        assert agent is not None
        await session.delete(agent)
        await session.commit()

    assert await _count_participations(db_session_factory, attack_id) == 0
