"""Контракт гейта атаки без базы: резерв, settle, финал и выход.

Фейк повторяет поверхность ``DatabaseAttackRepository`` на обычных объектах.
SQL проверяют интеграционные тесты, а здесь зафиксировано поведение, на
которое опирается сервис: двойной settle, учёт исходов, финал после резервов
и освобождение слота при выходе.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from mimic42.core.attack import (
    AttackAgentStatus,
    AttackConfig,
    AttackEndReason,
    AttackStateError,
    AttackStatus,
    AttackView,
    ExitReason,
    MessagesLimit,
    MinutesLimit,
    ParticipationView,
    SendFailure,
    SendOutcome,
    Settlement,
    SlotClaim,
    TargetRef,
    attack_end_reason,
    compose_comment,
)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
NEXT = NOW + timedelta(seconds=30)


def make_config(
    *,
    limit: MessagesLimit | MinutesLimit | None = None,
    media_paths: tuple[str, ...] = (),
) -> AttackConfig:
    return AttackConfig(
        title="Розыгрыш",
        target=TargetRef(link="https://t.me/example/412", channel="example", post_id=412),
        texts=("Участвую!", "Бросаю в зачёт"),
        media_paths=media_paths,
        limit=limit if limit is not None else MessagesLimit(2),
    )


@dataclass
class _FakeParticipation:
    id: UUID
    attack_id: UUID
    agent_id: UUID
    status: AttackAgentStatus
    sent_count: int = 0
    next_at: datetime | None = None
    pending_random_id: int | None = None
    pending_text: str | None = None
    pending_media: tuple[str, ...] = ()
    pending_count: int = 0
    pending_attempts: int = 0
    last_error: str | None = None
    exit_reason: ExitReason | None = None
    note_written_at: datetime | None = None


@dataclass
class _FakeAttack:
    id: UUID
    owner_id: UUID
    config: AttackConfig
    status: AttackStatus = AttackStatus.DRAFT
    sent_count: int = 0
    claimed_count: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    end_reason: AttackEndReason | None = None
    deadline_at: datetime | None = None
    participations: list[_FakeParticipation] = field(default_factory=list)


class FakeAttackGate:
    """Повторяет контракт репозитория на памяти; БД и SQL здесь нет."""

    def __init__(self) -> None:
        self.attacks: dict[UUID, _FakeAttack] = {}

    async def create(
        self, owner_id: UUID, config: AttackConfig, agent_ids: list[UUID], now: datetime
    ) -> AttackView:
        attack = _FakeAttack(id=uuid4(), owner_id=owner_id, config=config)
        attack.participations = [
            _FakeParticipation(
                id=uuid4(),
                attack_id=attack.id,
                agent_id=agent_id,
                status=AttackAgentStatus.ASSIGNED,
            )
            for agent_id in dict.fromkeys(agent_ids)
        ]
        self.attacks[attack.id] = attack
        return self._view(attack)

    async def start(self, attack_id: UUID, now: datetime) -> AttackView:
        attack = self._attack(attack_id)
        if attack.status is not AttackStatus.DRAFT:
            raise AttackStateError("Запустить можно только черновик")
        if not attack.participations:
            raise AttackStateError("В атаке нет назначенных мимиков")
        attack.status = AttackStatus.RUNNING
        attack.started_at = now
        if isinstance(attack.config.limit, MinutesLimit):
            attack.deadline_at = now + timedelta(minutes=attack.config.limit_value)
        for participation in attack.participations:
            participation.status = AttackAgentStatus.ACTIVE
        return self._view(attack)

    async def claim(
        self, attack_id: UUID, agent_id: UUID, now: datetime, rng: random.Random
    ) -> SlotClaim | None:
        attack = self._attack(attack_id)
        participation = next(
            (row for row in reversed(attack.participations) if row.agent_id == agent_id),
            None,
        )
        if participation is None:
            return None
        if (
            attack.status is not AttackStatus.RUNNING
            or participation.status is not AttackAgentStatus.ACTIVE
        ):
            self._release(attack, participation)
            return None
        if participation.pending_random_id is not None:
            return SlotClaim(
                attack_id=attack.id,
                agent_id=agent_id,
                participation_id=participation.id,
                random_id=participation.pending_random_id,
                text=participation.pending_text or "",
                media=participation.pending_media,
                message_count=max(1, participation.pending_count),
            )
        remaining: int | None = None
        if isinstance(attack.config.limit, MinutesLimit):
            if attack.deadline_at is not None and attack.deadline_at <= now:
                return None
        else:
            remaining = attack.config.limit_value - attack.claimed_count
            if remaining <= 0:
                return None
        content = compose_comment(attack.config.texts, attack.config.media_paths, rng)
        if remaining is not None and len(content.media) > remaining:
            content = replace(content, media=content.media[:remaining])
        message_count = max(1, len(content.media))
        random_id = rng.getrandbits(63) + 1
        attack.claimed_count += message_count
        participation.pending_random_id = random_id
        participation.pending_text = content.text
        participation.pending_media = content.media
        participation.pending_count = message_count
        return SlotClaim(
            attack_id=attack.id,
            agent_id=agent_id,
            participation_id=participation.id,
            random_id=random_id,
            text=content.text,
            media=content.media,
            message_count=message_count,
        )

    async def settle(
        self,
        claim: SlotClaim,
        outcome: SendOutcome,
        now: datetime,
        next_at: datetime,
    ) -> Settlement:
        attack = self._attack(claim.attack_id)
        participation = next(
            (row for row in attack.participations if row.id == claim.participation_id), None
        )
        if participation is None or participation.pending_random_id != claim.random_id:
            return self._settlement(attack)
        if outcome.kind == "sent":
            sent_messages = (
                outcome.delivered if outcome.delivered is not None else max(1, len(claim.media))
            )
            sent_messages = min(max(sent_messages, 1), claim.message_count)
            attack.sent_count += sent_messages
            participation.sent_count += sent_messages
            attack.claimed_count -= claim.message_count - sent_messages
            participation.pending_attempts = 0
            participation.last_error = None
            self._clear(participation)
        elif outcome.kind == "not_sent":
            self._release(attack, participation)
            participation.pending_attempts = 0
            participation.last_error = outcome.failure.value if outcome.failure else None
        elif outcome.kind == "unknown":
            participation.pending_attempts += 1
            participation.last_error = outcome.failure.value if outcome.failure else None
        else:
            self._release(attack, participation)
            participation.last_error = "результат отправки неизвестен"
        participation.next_at = next_at
        reason = attack_end_reason(
            limit_type=attack.config.limit_type,
            limit_value=attack.config.limit_value,
            deadline_at=attack.deadline_at,
            sent_count=attack.sent_count,
            claimed_count=attack.claimed_count,
            now=now,
        )
        if attack.status is AttackStatus.RUNNING and reason is not None:
            attack.status = AttackStatus.FINISHED
            attack.finished_at = now
            attack.end_reason = reason
            for row in attack.participations:
                if row.status in (AttackAgentStatus.ASSIGNED, AttackAgentStatus.ACTIVE):
                    self._exit(attack, row, ExitReason.ATTACK_FINISHED)
        return self._settlement(attack)

    async def exit_participation(
        self, participation_id: UUID, reason: ExitReason, now: datetime
    ) -> None:
        for attack in self.attacks.values():
            for participation in attack.participations:
                if participation.id != participation_id:
                    continue
                if participation.status is AttackAgentStatus.EXITED:
                    return
                self._exit(attack, participation, reason)
                self._cancel_if_empty(attack, now)
                return

    async def mark_note_written(self, participation_id: UUID, now: datetime) -> bool:
        for attack in self.attacks.values():
            for participation in attack.participations:
                if participation.id != participation_id:
                    continue
                if participation.note_written_at is not None:
                    return False
                participation.note_written_at = now
                return True
        return False

    async def load(self, attack_id: UUID) -> AttackView | None:
        attack = self.attacks.get(attack_id)
        return self._view(attack) if attack is not None else None

    async def pending_notes(self) -> list[ParticipationView]:
        return [
            self._participation_view(participation)
            for attack in self.attacks.values()
            for participation in attack.participations
            if participation.status is AttackAgentStatus.EXITED
            and participation.note_written_at is None
        ]

    def _attack(self, attack_id: UUID) -> _FakeAttack:
        attack = self.attacks.get(attack_id)
        if attack is None:
            raise KeyError(f"Атака {attack_id} не найдена")
        return attack

    @staticmethod
    def _clear(participation: _FakeParticipation) -> None:
        participation.pending_random_id = None
        participation.pending_text = None
        participation.pending_media = ()
        participation.pending_count = 0

    def _release(self, attack: _FakeAttack, participation: _FakeParticipation) -> None:
        if participation.pending_random_id is None:
            return
        attack.claimed_count -= max(1, participation.pending_count)
        self._clear(participation)

    def _exit(
        self,
        attack: _FakeAttack,
        participation: _FakeParticipation,
        reason: ExitReason,
    ) -> None:
        self._release(attack, participation)
        participation.status = AttackAgentStatus.EXITED
        participation.exit_reason = reason

    def _cancel_if_empty(self, attack: _FakeAttack, now: datetime) -> None:
        if attack.status is not AttackStatus.RUNNING:
            return
        if any(row.status is not AttackAgentStatus.EXITED for row in attack.participations):
            return
        attack.status = AttackStatus.CANCELLED
        attack.finished_at = now
        attack.end_reason = AttackEndReason.NO_AGENTS

    def _view(self, attack: _FakeAttack) -> AttackView:
        return AttackView(
            id=attack.id,
            owner_id=attack.owner_id,
            config=attack.config,
            status=attack.status,
            sent_count=attack.sent_count,
            claimed_count=attack.claimed_count,
            version=1,
            started_at=attack.started_at,
            finished_at=attack.finished_at,
            end_reason=attack.end_reason,
            participations=tuple(self._participation_view(row) for row in attack.participations),
            deadline_at=attack.deadline_at,
        )

    @staticmethod
    def _participation_view(participation: _FakeParticipation) -> ParticipationView:
        return ParticipationView(
            id=participation.id,
            attack_id=participation.attack_id,
            agent_id=participation.agent_id,
            status=participation.status,
            sent_count=participation.sent_count,
            next_at=participation.next_at,
            last_error=participation.last_error,
            exit_reason=participation.exit_reason,
            note_written_at=participation.note_written_at,
        )

    @staticmethod
    def _settlement(attack: _FakeAttack) -> Settlement:
        return Settlement(
            sent_count=attack.sent_count,
            claimed_count=attack.claimed_count,
            finished=attack.status in (AttackStatus.FINISHED, AttackStatus.CANCELLED),
            end_reason=attack.end_reason,
        )


async def _running_gate(
    *, limit: MessagesLimit | MinutesLimit | None = None, agents: int = 1
) -> tuple[FakeAttackGate, AttackView]:
    gate = FakeAttackGate()
    attack = await gate.create(
        uuid4(), make_config(limit=limit), [uuid4() for _ in range(agents)], NOW
    )
    await gate.start(attack.id, NOW)
    return gate, attack


async def _claim(
    gate: FakeAttackGate, attack: AttackView, index: int = 0, seed: int = 1
) -> SlotClaim:
    claim = await gate.claim(
        attack.id, attack.participations[index].agent_id, NOW, random.Random(seed)
    )
    assert claim is not None
    return claim


async def test_a_repeated_settle_does_not_count_twice() -> None:
    gate, attack = await _running_gate()
    claim = await _claim(gate, attack)

    first = await gate.settle(claim, SendOutcome.sent(77), NOW, NEXT)
    second = await gate.settle(claim, SendOutcome.not_sent(SendFailure.FLOOD_WAIT), NEXT, NEXT)

    assert (first.sent_count, first.claimed_count) == (1, 1)
    assert second == first
    stored = await gate.load(attack.id)
    assert stored is not None
    assert stored.participations[0].sent_count == 1


async def test_sent_counts_the_comment_and_clears_the_reservation() -> None:
    gate, attack = await _running_gate()
    claim = await _claim(gate, attack)

    settlement = await gate.settle(claim, SendOutcome.sent(77), NOW, NEXT)
    stored = await gate.load(attack.id)

    assert settlement.sent_count == 1 and settlement.claimed_count == 1
    assert stored is not None
    participation = stored.participations[0]
    assert participation.sent_count == 1
    assert participation.next_at == NEXT
    assert participation.last_error is None


async def test_an_album_counts_every_image_as_a_telegram_message() -> None:
    gate = FakeAttackGate()
    media = tuple(f"attacks/owner/{index}.jpg" for index in range(10))
    attack = await gate.create(
        uuid4(), make_config(limit=MessagesLimit(25), media_paths=media), [uuid4()], NOW
    )
    await gate.start(attack.id, NOW)

    first = await _claim(gate, attack, seed=1)
    assert len(first.media) == 10 and first.message_count == 10
    first_settlement = await gate.settle(first, SendOutcome.sent(1), NOW, NEXT)
    assert first_settlement.sent_count == 10
    assert first_settlement.claimed_count == 10

    second = await _claim(gate, attack, seed=2)
    second_settlement = await gate.settle(second, SendOutcome.sent(2), NOW, NEXT)
    assert second_settlement.sent_count == 20

    last = await _claim(gate, attack, seed=3)
    assert len(last.media) == 5 and last.message_count == 5
    finished = await gate.settle(last, SendOutcome.sent(3), NOW, NEXT)
    assert finished.sent_count == 25
    assert finished.finished is True
    assert finished.end_reason is AttackEndReason.LIMIT_REACHED


async def test_a_text_fallback_releases_the_unused_album_reservation() -> None:
    gate = FakeAttackGate()
    media = tuple(f"attacks/owner/{index}.jpg" for index in range(10))
    attack = await gate.create(
        uuid4(), make_config(limit=MessagesLimit(25), media_paths=media), [uuid4()], NOW
    )
    await gate.start(attack.id, NOW)
    claim = await _claim(gate, attack)

    settlement = await gate.settle(replace(claim, media=()), SendOutcome.sent(1), NOW, NEXT)

    assert settlement.sent_count == 1
    assert settlement.claimed_count == 1
    stored = await gate.load(attack.id)
    assert stored is not None
    assert stored.participations[0].sent_count == 1


async def test_not_sent_releases_the_whole_album_reservation() -> None:
    gate = FakeAttackGate()
    media = tuple(f"attacks/owner/{index}.jpg" for index in range(10))
    attack = await gate.create(
        uuid4(), make_config(limit=MessagesLimit(25), media_paths=media), [uuid4()], NOW
    )
    await gate.start(attack.id, NOW)
    claim = await _claim(gate, attack)

    settlement = await gate.settle(claim, SendOutcome.not_sent(SendFailure.FLOOD_WAIT), NOW, NEXT)

    assert settlement.sent_count == 0
    assert settlement.claimed_count == 0


async def test_not_sent_releases_the_slot() -> None:
    gate, attack = await _running_gate()
    claim = await _claim(gate, attack)

    settlement = await gate.settle(claim, SendOutcome.not_sent(SendFailure.FLOOD_WAIT), NOW, NEXT)
    stored = await gate.load(attack.id)

    assert settlement.sent_count == 0 and settlement.claimed_count == 0
    assert stored is not None
    assert stored.participations[0].last_error == "flood_wait"
    assert stored.participations[0].next_at == NEXT


async def test_unknown_keeps_the_reservation_for_the_same_random_id() -> None:
    gate, attack = await _running_gate()
    claim = await _claim(gate, attack)

    first = await gate.settle(claim, SendOutcome.unknown(SendFailure.TRANSIENT), NOW, NEXT)
    stored = await gate.load(attack.id)

    assert first.claimed_count == 1 and first.sent_count == 0
    assert stored is not None
    assert stored.participations[0].next_at == NEXT
    repeated = await gate.claim(
        attack.id, attack.participations[0].agent_id, NEXT, random.Random(2)
    )
    assert repeated is not None and repeated.random_id == claim.random_id
    assert repeated.text == claim.text

    second = await gate.settle(claim, SendOutcome.unknown(SendFailure.TRANSIENT), NEXT, NEXT)
    assert second.claimed_count == 1


async def test_interrupted_releases_the_slot_and_records_an_error() -> None:
    gate, attack = await _running_gate()
    claim = await _claim(gate, attack)

    settlement = await gate.settle(claim, SendOutcome.interrupted(), NOW, NEXT)
    stored = await gate.load(attack.id)

    assert settlement.claimed_count == 0
    assert stored is not None
    assert "неизвестен" in (stored.participations[0].last_error or "")


async def test_messages_limit_finishes_when_the_last_reservation_settles() -> None:
    gate, attack = await _running_gate(limit=MessagesLimit(2), agents=2)
    first = await _claim(gate, attack, index=0, seed=1)
    second = await _claim(gate, attack, index=1, seed=2)

    pending = await gate.settle(first, SendOutcome.sent(1), NOW, NEXT)
    assert pending.finished is False

    finished = await gate.settle(second, SendOutcome.sent(2), NOW, NEXT)
    stored = await gate.load(attack.id)

    assert finished.finished is True
    assert finished.end_reason is AttackEndReason.LIMIT_REACHED
    assert stored is not None
    assert stored.status is AttackStatus.FINISHED
    assert all(row.status is AttackAgentStatus.EXITED for row in stored.participations)
    assert all(row.exit_reason is ExitReason.ATTACK_FINISHED for row in stored.participations)


async def test_deadline_finishes_after_the_pending_reservation_settles() -> None:
    gate, attack = await _running_gate(limit=MinutesLimit(5))
    claim = await _claim(gate, attack)
    after_deadline = NOW + timedelta(minutes=5, seconds=1)

    pending = await gate.settle(
        claim, SendOutcome.unknown(SendFailure.TRANSIENT), after_deadline, NEXT
    )
    assert pending.finished is False

    finished = await gate.settle(claim, SendOutcome.sent(1), after_deadline, NEXT)
    assert finished.finished is True
    assert finished.end_reason is AttackEndReason.DEADLINE


async def test_claim_after_the_deadline_does_not_reserve_a_new_slot() -> None:
    gate, attack = await _running_gate(limit=MinutesLimit(5))
    after_deadline = NOW + timedelta(minutes=6)

    claim = await gate.claim(
        attack.id, attack.participations[0].agent_id, after_deadline, random.Random(1)
    )

    assert claim is None


async def test_exit_releases_the_pending_slot() -> None:
    gate, attack = await _running_gate(agents=2)
    claim = await _claim(gate, attack)
    stored = await gate.load(attack.id)
    assert stored is not None

    await gate.exit_participation(claim.participation_id, ExitReason.PAUSED, NEXT)
    after = await gate.load(attack.id)

    assert after is not None
    assert after.claimed_count == 0
    assert after.status is AttackStatus.RUNNING
    assert after.participations[0].exit_reason is ExitReason.PAUSED


async def test_exit_of_the_last_agent_cancels_the_attack() -> None:
    gate, attack = await _running_gate()

    await gate.exit_participation(attack.participations[0].id, ExitReason.AGENT_STOPPED, NEXT)
    stored = await gate.load(attack.id)

    assert stored is not None
    assert stored.status is AttackStatus.CANCELLED
    assert stored.end_reason is AttackEndReason.NO_AGENTS


async def test_claim_on_a_cancelled_attack_closes_its_reservation_as_interrupted() -> None:
    gate, attack = await _running_gate()
    await _claim(gate, attack)
    fake = gate.attacks[attack.id]
    fake.status = AttackStatus.CANCELLED

    assert (
        await gate.claim(attack.id, attack.participations[0].agent_id, NEXT, random.Random(1))
        is None
    )
    stored = await gate.load(attack.id)
    assert stored is not None
    assert stored.claimed_count == 0
    assert fake.participations[0].pending_random_id is None


async def test_note_marker_is_idempotent_and_queues_the_note_once() -> None:
    gate, attack = await _running_gate()
    participation_id = attack.participations[0].id
    await gate.exit_participation(participation_id, ExitReason.ATTACK_FINISHED, NOW)

    assert await gate.mark_note_written(participation_id, NEXT) is True
    assert await gate.mark_note_written(participation_id, NEXT) is False
    assert await gate.pending_notes() == []


async def test_pending_notes_lists_an_exited_participation_without_a_note() -> None:
    gate, attack = await _running_gate()
    await gate.exit_participation(attack.participations[0].id, ExitReason.PAUSED, NOW)

    notes = await gate.pending_notes()

    assert [note.id for note in notes] == [attack.participations[0].id]
