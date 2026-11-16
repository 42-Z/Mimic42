"""Репозиторий атак на настоящей схеме: переносы, резерв, учёт и финал."""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.attack import (
    AttackAgentStatus,
    AttackConfig,
    AttackEndReason,
    AttackPatch,
    AttackStateError,
    AttackStatus,
    AttackVersionConflictError,
    AttackView,
    ExitReason,
    MessagesLimit,
    MinutesLimit,
    SendFailure,
    SendOutcome,
    parse_target_link,
)
from mimic42.integrations.database_attack import DatabaseAttackRepository
from mimic42.integrations.database_models import (
    AgentModel,
    AttackAgentModel,
    AttackModel,
    TelegramSessionModel,
)
from mimic42.testing.slots import Slot

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
NEXT = NOW + timedelta(seconds=30)


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


def _config(
    *,
    limit: MessagesLimit | MinutesLimit | None = None,
    texts: tuple[str, ...] = ("Участвую!",),
    media_paths: tuple[str, ...] = (),
) -> AttackConfig:
    return AttackConfig(
        title="Розыгрыш",
        target=parse_target_link("https://t.me/example/412"),
        texts=texts,
        media_paths=media_paths,
        limit=limit if limit is not None else MessagesLimit(3),
    )


def _repo(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> DatabaseAttackRepository:
    return DatabaseAttackRepository(db_session_factory)


async def _create_agent(
    db_session_factory: async_sessionmaker[AsyncSession],
    owner_id: UUID,
    *,
    restricted: bool = False,
    authorized: bool = True,
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
                warmup_restricted_at=NOW if restricted else None,
            )
        )
        if authorized:
            session.add(
                TelegramSessionModel(
                    agent_id=agent_id,
                    session_name=agent_id.hex,
                    authorization_status="authorized",
                )
            )
        await session.commit()
    return agent_id


def _statuses(attack: AttackView) -> dict[UUID, AttackAgentStatus]:
    return {row.agent_id: row.status for row in attack.participations}


async def _pending_attempts(
    db_session_factory: async_sessionmaker[AsyncSession], participation_id: UUID
) -> int:
    async with db_session_factory() as session:
        row = await session.get(AttackAgentModel, participation_id)
        assert row is not None
        return row.pending_attempts


async def _pending_media_type(
    db_session_factory: async_sessionmaker[AsyncSession], participation_id: UUID
) -> str | None:
    """``None`` — SQL NULL; ``'null'`` — JSON-литерал, который не проходит CHECK."""
    async with db_session_factory() as session:
        return await session.scalar(
            select(func.jsonb_typeof(AttackAgentModel.pending_media)).where(
                AttackAgentModel.id == participation_id
            )
        )


async def test_create_moves_agents_out_of_a_previous_draft(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    first_agent = await _create_agent(db_session_factory, owner_id)
    second_agent = await _create_agent(db_session_factory, owner_id)
    first_attack = await repository.create(owner_id, _config(), [first_agent, second_agent], NOW)

    await repository.create(owner_id, _config(), [first_agent], NOW)
    stored = await repository.load(first_attack.id)

    assert stored is not None
    assert stored.status is AttackStatus.DRAFT
    by_agent = {row.agent_id: row for row in stored.participations}
    assert by_agent[first_agent].status is AttackAgentStatus.EXITED
    assert by_agent[first_agent].exit_reason is ExitReason.MOVED
    assert by_agent[second_agent].status is AttackAgentStatus.ASSIGNED


async def test_moving_the_last_agent_cancels_a_running_attack(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    running = await repository.create(owner_id, _config(), [agent_id], NOW)
    await repository.start(running.id, NOW)
    target = await repository.create(owner_id, _config(), [], NOW)

    participation = await repository.assign(target.id, agent_id, owner_id, NEXT)
    stored = await repository.load(running.id)

    assert participation.status is AttackAgentStatus.ASSIGNED
    assert stored is not None
    assert stored.status is AttackStatus.CANCELLED
    assert stored.end_reason is AttackEndReason.NO_AGENTS


async def test_assigning_to_a_running_attack_activates_the_participation(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    first_agent = await _create_agent(db_session_factory, owner_id)
    second_agent = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(), [first_agent], NOW)
    await repository.start(attack.id, NOW)

    participation = await repository.assign(attack.id, second_agent, owner_id, NEXT)

    assert participation.status is AttackAgentStatus.ACTIVE


async def test_start_requires_an_assigned_agent(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    attack = await repository.create(owner_id, _config(), [], NOW)

    with pytest.raises(AttackStateError):
        await repository.start(attack.id, NOW)


async def test_start_sets_started_at_and_the_deadline_and_is_idempotent(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(limit=MinutesLimit(5)), [agent_id], NOW)

    started = await repository.start(attack.id, NOW)
    again = await repository.start(attack.id, NEXT)

    assert started.status is AttackStatus.RUNNING
    assert started.started_at == NOW
    assert started.deadline_at == NOW + timedelta(minutes=5)
    assert started.participations[0].status is AttackAgentStatus.ACTIVE
    assert again.started_at == NOW


async def test_two_claims_for_the_last_slot_give_one_reservation(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    first_agent = await _create_agent(db_session_factory, owner_id)
    second_agent = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(
        owner_id, _config(limit=MessagesLimit(1)), [first_agent, second_agent], NOW
    )
    await repository.start(attack.id, NOW)

    results = await asyncio.gather(
        repository.claim(attack.id, first_agent, NOW, random.Random(1)),
        repository.claim(attack.id, second_agent, NOW, random.Random(2)),
    )
    stored = await repository.load(attack.id)

    assert sum(result is not None for result in results) == 1
    assert stored is not None
    assert stored.claimed_count == 1


async def test_claim_returns_the_same_reservation_until_it_settles(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(), [agent_id], NOW)
    await repository.start(attack.id, NOW)

    first = await repository.claim(attack.id, agent_id, NOW, random.Random(1))
    second = await repository.claim(attack.id, agent_id, NEXT, random.Random(2))
    stored = await repository.load(attack.id)

    assert first is not None and second is not None
    assert (first.random_id, first.text, first.media) == (
        second.random_id,
        second.text,
        second.media,
    )
    assert stored is not None
    assert stored.claimed_count == 1


async def test_settle_sent_counts_once_and_a_repeat_is_a_noop(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(), [agent_id], NOW)
    await repository.start(attack.id, NOW)
    claim = await repository.claim(attack.id, agent_id, NOW, random.Random(1))
    assert claim is not None

    first = await repository.settle(claim, SendOutcome.sent(77), NOW, NEXT)
    second = await repository.settle(
        claim, SendOutcome.not_sent(SendFailure.FLOOD_WAIT), NEXT, NEXT
    )
    stored = await repository.load(attack.id)

    assert (first.sent_count, first.claimed_count) == (1, 1)
    assert second == first
    assert stored is not None
    assert stored.participations[0].sent_count == 1
    assert stored.participations[0].next_at == NEXT
    assert await _pending_media_type(db_session_factory, claim.participation_id) is None


async def test_not_sent_releases_the_slot_and_records_the_error(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(), [agent_id], NOW)
    await repository.start(attack.id, NOW)
    claim = await repository.claim(attack.id, agent_id, NOW, random.Random(1))
    assert claim is not None

    settlement = await repository.settle(
        claim, SendOutcome.not_sent(SendFailure.FLOOD_WAIT), NOW, NEXT
    )
    stored = await repository.load(attack.id)

    assert settlement.claimed_count == 0 and settlement.sent_count == 0
    assert stored is not None
    assert "FloodWait" in (stored.participations[0].last_error or "")


async def test_unknown_keeps_the_reservation_and_counts_attempts(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(), [agent_id], NOW)
    await repository.start(attack.id, NOW)
    claim = await repository.claim(attack.id, agent_id, NOW, random.Random(1))
    assert claim is not None

    settlement = await repository.settle(
        claim, SendOutcome.unknown(SendFailure.TRANSIENT), NOW, NEXT
    )
    repeated = await repository.claim(attack.id, agent_id, NEXT, random.Random(2))

    assert settlement.claimed_count == 1 and settlement.sent_count == 0
    assert repeated is not None and repeated.random_id == claim.random_id
    assert await _pending_attempts(db_session_factory, claim.participation_id) == 1


async def test_interrupted_releases_the_slot(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(), [agent_id], NOW)
    await repository.start(attack.id, NOW)
    claim = await repository.claim(attack.id, agent_id, NOW, random.Random(1))
    assert claim is not None

    settlement = await repository.settle(claim, SendOutcome.interrupted(), NOW, NEXT)

    assert settlement.claimed_count == 0
    assert settlement.sent_count == 0


async def test_lowered_limit_finishes_after_the_reservations_settle(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    first_agent = await _create_agent(db_session_factory, owner_id)
    second_agent = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(
        owner_id, _config(limit=MessagesLimit(3)), [first_agent, second_agent], NOW
    )
    await repository.start(attack.id, NOW)
    first = await repository.claim(attack.id, first_agent, NOW, random.Random(1))
    second = await repository.claim(attack.id, second_agent, NOW, random.Random(2))
    assert first is not None and second is not None

    lowered = await repository.update(
        attack.id,
        AttackPatch(
            version=attack.version,
            title=attack.config.title,
            texts=attack.config.texts,
            media_paths=attack.config.media_paths,
            limit=MessagesLimit(1),
        ),
        NOW,
    )
    pending = await repository.settle(first, SendOutcome.sent(1), NOW, NEXT)
    finished = await repository.settle(second, SendOutcome.sent(2), NOW, NEXT)
    stored = await repository.load(attack.id)

    assert lowered.sent_count == 0 and lowered.version == 2
    assert pending.finished is False
    assert finished.finished is True
    assert finished.end_reason is AttackEndReason.LIMIT_REACHED
    assert stored is not None
    assert stored.status is AttackStatus.FINISHED
    assert all(row.status is AttackAgentStatus.EXITED for row in stored.participations)
    assert all(row.exit_reason is ExitReason.ATTACK_FINISHED for row in stored.participations)


async def test_deadline_finishes_when_the_last_reservation_settles(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(limit=MinutesLimit(5)), [agent_id], NOW)
    await repository.start(attack.id, NOW)
    claim = await repository.claim(attack.id, agent_id, NOW, random.Random(1))
    assert claim is not None
    after_deadline = NOW + timedelta(minutes=5, seconds=1)

    settlement = await repository.settle(
        claim, SendOutcome.not_sent(SendFailure.FLOOD_WAIT), after_deadline, NEXT
    )

    assert settlement.finished is True
    assert settlement.end_reason is AttackEndReason.DEADLINE


async def test_cancel_exits_participants_and_releases_their_reservations(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    first_agent = await _create_agent(db_session_factory, owner_id)
    second_agent = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(), [first_agent, second_agent], NOW)
    await repository.start(attack.id, NOW)
    claim = await repository.claim(attack.id, first_agent, NOW, random.Random(1))
    assert claim is not None

    cancelled = await repository.cancel(attack.id, AttackEndReason.CANCELLED_BY_USER, NEXT)
    again = await repository.cancel(attack.id, AttackEndReason.TARGET_UNAVAILABLE, NEXT)

    assert cancelled.status is AttackStatus.CANCELLED
    assert cancelled.end_reason is AttackEndReason.CANCELLED_BY_USER
    assert cancelled.claimed_count == 0
    assert all(
        row.status is AttackAgentStatus.EXITED and row.exit_reason is ExitReason.ATTACK_CANCELLED
        for row in cancelled.participations
    )
    assert again.end_reason is AttackEndReason.CANCELLED_BY_USER


async def test_exit_of_the_last_participation_cancels_the_attack(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(), [agent_id], NOW)
    await repository.start(attack.id, NOW)
    claim = await repository.claim(attack.id, agent_id, NOW, random.Random(1))
    assert claim is not None

    await repository.exit_participation(claim.participation_id, ExitReason.PAUSED, NEXT)
    stored = await repository.load(attack.id)

    assert stored is not None
    assert stored.claimed_count == 0
    assert stored.status is AttackStatus.CANCELLED
    assert stored.end_reason is AttackEndReason.NO_AGENTS
    assert stored.participations[0].exit_reason is ExitReason.PAUSED


async def test_repeat_keeps_only_eligible_agents(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    eligible = await _create_agent(db_session_factory, owner_id)
    restricted = await _create_agent(db_session_factory, owner_id, restricted=True)
    unauthorized = await _create_agent(db_session_factory, owner_id, authorized=False)
    busy = await _create_agent(db_session_factory, owner_id)
    old = await repository.create(
        owner_id,
        _config(limit=MessagesLimit(1)),
        [eligible, restricted, unauthorized, busy],
        NOW,
    )
    await repository.start(old.id, NOW)
    claim = await repository.claim(old.id, eligible, NOW, random.Random(1))
    assert claim is not None
    await repository.settle(claim, SendOutcome.sent(1), NOW, NEXT)
    await repository.create(owner_id, _config(), [busy], NOW)

    repeated = await repository.repeat(old.id, NEXT)

    assert repeated.status is AttackStatus.DRAFT
    assert repeated.sent_count == 0 and repeated.claimed_count == 0
    assert repeated.config.target.link == old.config.target.link
    assert _statuses(repeated) == {eligible: AttackAgentStatus.ASSIGNED}


async def test_update_rejects_a_stale_version_and_keeps_the_counts(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(), [agent_id], NOW)
    await repository.start(attack.id, NOW)
    claim = await repository.claim(attack.id, agent_id, NOW, random.Random(1))
    assert claim is not None
    await repository.settle(claim, SendOutcome.sent(1), NOW, NEXT)
    patch = AttackPatch(
        version=attack.version,
        title="Новое название",
        texts=("Другой текст",),
        media_paths=(),
        limit=MessagesLimit(5),
    )

    updated = await repository.update(attack.id, patch, NEXT)

    assert updated.version == 2
    assert updated.config.title == "Новое название"
    assert updated.config.texts == ("Другой текст",)
    assert updated.config.target.link == "https://t.me/example/412"
    assert (updated.sent_count, updated.claimed_count) == (1, 1)
    with pytest.raises(AttackVersionConflictError):
        await repository.update(attack.id, patch, NEXT)


async def test_update_recomputes_the_deadline_for_a_time_limit(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(limit=MinutesLimit(5)), [agent_id], NOW)
    started = await repository.start(attack.id, NOW)

    longer = await repository.update(
        attack.id,
        AttackPatch(
            version=started.version,
            title=started.config.title,
            texts=started.config.texts,
            media_paths=started.config.media_paths,
            limit=MinutesLimit(10),
        ),
        NEXT,
    )
    to_messages = await repository.update(
        attack.id,
        AttackPatch(
            version=longer.version,
            title=longer.config.title,
            texts=longer.config.texts,
            media_paths=longer.config.media_paths,
            limit=MessagesLimit(4),
        ),
        NEXT,
    )

    assert longer.deadline_at == NOW + timedelta(minutes=10)
    assert to_messages.deadline_at is None
    assert to_messages.started_at == NOW


async def test_note_marker_is_idempotent_and_pending_notes_is_drained(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(), [agent_id], NOW)
    await repository.start(attack.id, NOW)
    participation_id = attack.participations[0].id
    await repository.exit_participation(participation_id, ExitReason.PAUSED, NEXT)

    queued = await repository.pending_notes()
    first = await repository.mark_note_written(participation_id, NEXT)
    second = await repository.mark_note_written(participation_id, NEXT)

    assert [note.id for note in queued] == [participation_id]
    assert first is True
    assert second is False
    assert await repository.pending_notes() == []


async def test_load_running_lists_only_running_attacks(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    draft_agent = await _create_agent(db_session_factory, owner_id)
    running_agent = await _create_agent(db_session_factory, owner_id)
    await repository.create(owner_id, _config(), [draft_agent], NOW)
    running = await repository.create(owner_id, _config(), [running_agent], NOW)
    await repository.start(running.id, NOW)

    listed = await repository.load_running()

    assert [attack.id for attack in listed] == [running.id]


async def test_finish_waits_for_the_reservation_and_is_idempotent(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(limit=MessagesLimit(1)), [agent_id], NOW)
    await repository.start(attack.id, NOW)
    claim = await repository.claim(attack.id, agent_id, NOW, random.Random(1))
    assert claim is not None

    waiting = await repository.finish(attack.id, AttackEndReason.LIMIT_REACHED, NEXT)

    assert waiting.status is AttackStatus.RUNNING
    assert waiting.claimed_count == 1 and waiting.sent_count == 0

    await repository.settle(claim, SendOutcome.sent(77), NEXT, NEXT)
    closed = await repository.finish(attack.id, AttackEndReason.LIMIT_REACHED, NEXT)
    again = await repository.finish(attack.id, AttackEndReason.DEADLINE, NEXT)

    assert closed.status is AttackStatus.FINISHED
    assert closed.end_reason is AttackEndReason.LIMIT_REACHED
    assert all(row.status is AttackAgentStatus.EXITED for row in closed.participations)
    assert all(row.exit_reason is ExitReason.ATTACK_FINISHED for row in closed.participations)
    assert again.end_reason is AttackEndReason.LIMIT_REACHED


async def test_finish_closes_an_expired_attack_without_reservations(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(limit=MinutesLimit(1)), [agent_id], NOW)
    await repository.start(attack.id, NOW)

    closed = await repository.finish(
        attack.id, AttackEndReason.DEADLINE, NOW + timedelta(minutes=2)
    )

    assert closed.status is AttackStatus.FINISHED
    assert closed.end_reason is AttackEndReason.DEADLINE
    assert closed.participations[0].exit_reason is ExitReason.ATTACK_FINISHED


async def test_set_target_stores_public_ids_and_slowmode(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    attack = await repository.create(owner_id, _config(), [], NOW)

    await repository.set_target(attack.id, -100_123, 77, 15, NEXT)
    stored = await repository.load(attack.id)

    assert stored is not None
    assert stored.target_channel_id == -100_123
    assert stored.anchor_message_id == 77
    assert stored.slowmode_seconds == 15


async def test_clear_media_keeps_the_same_reservation(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(
        owner_id,
        _config(media_paths=("attacks/owner/a.jpg",)),
        [agent_id],
        NOW,
    )
    await repository.start(attack.id, NOW)
    claim = await repository.claim(attack.id, agent_id, NOW, random.Random(1))
    assert claim is not None

    cleared = await repository.clear_media(attack.id, claim.participation_id, claim.random_id)
    repeated = await repository.claim(attack.id, agent_id, NEXT, random.Random(2))
    stored = await repository.load(attack.id)

    assert cleared is True
    assert repeated is not None
    assert repeated.random_id == claim.random_id
    assert repeated.media == ()
    assert stored is not None
    assert stored.participations[0].id == claim.participation_id


async def test_live_participation_follows_the_agent_until_it_exits(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(), [agent_id], NOW)

    live = await repository.live_participation(agent_id)

    assert live is not None
    assert live.attack_id == attack.id
    assert live.id == attack.participations[0].id

    await repository.pause(attack.id, agent_id, owner_id, NEXT)

    assert await repository.live_participation(agent_id) is None


async def test_exiting_the_last_mimic_on_a_missing_target_keeps_the_reason(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    repository = _repo(db_session_factory)
    agent_id = await _create_agent(db_session_factory, owner_id)
    attack = await repository.create(owner_id, _config(), [agent_id], NOW)
    await repository.start(attack.id, NOW)

    await repository.exit_participation(
        attack.participations[0].id, ExitReason.TARGET_UNAVAILABLE, NEXT
    )
    stored = await repository.load(attack.id)

    assert stored is not None
    assert stored.status is AttackStatus.CANCELLED
    assert stored.end_reason is AttackEndReason.TARGET_UNAVAILABLE
