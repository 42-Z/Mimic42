"""Сервис атаки на фейках: ростер, отправители, резерв, заметки и рестарт.

Сеть и база здесь не участвуют: рантайм, репозиторий, менеджер и телеметрия
подменены, а проверяется то, что видно снаружи — статусы атаки, исходит ли
комментарий, какой исход лёг в резерв и записалась ли заметка один раз.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from telethon import errors

import mimic42.core.attack_service as attack_service_module
from mimic42.core.agent_runtime import AgentRuntimeState, CommentMediaUnavailable
from mimic42.core.attack import (
    AttackAgentStatus,
    AttackConfig,
    AttackEndReason,
    AttackNotFoundError,
    AttackPatch,
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
)
from mimic42.core.attack_service import AgentAvailability, AttackService
from mimic42.core.attack_target import (
    AttackTarget,
    CommentsDisabledError,
    PostNotFoundError,
)
from tests.core.test_attack_gate import FakeAttackGate, _FakeAttack, _FakeParticipation

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
LIVE = (AttackAgentStatus.ASSIGNED, AttackAgentStatus.ACTIVE)
CLOSED = (AttackStatus.FINISHED, AttackStatus.CANCELLED)
CHANNEL_ID = 4242
ROOT_REPLY_ID = 77


def _config(
    *,
    limit: MessagesLimit | MinutesLimit | None = None,
    media_paths: tuple[str, ...] = (),
) -> AttackConfig:
    return AttackConfig(
        title="Розыгрыш",
        target=TargetRef(link="https://t.me/example/412", channel="example", post_id=412),
        texts=("Участвую!", "Бросаю в зачёт"),
        media_paths=media_paths,
        limit=limit if limit is not None else MessagesLimit(5),
    )


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
        await asyncio.sleep(0)


class Resolver:
    """Подмена разрешения цели: считает, сколько раз цель реально спросили."""

    def __init__(self, target: AttackTarget) -> None:
        self.target = target
        self.calls: list[TargetRef] = []

    async def __call__(self, client: Any, ref: TargetRef) -> AttackTarget:
        self.calls.append(ref)
        return self.target


@pytest.fixture(autouse=True)
def resolver(monkeypatch: pytest.MonkeyPatch) -> Resolver:
    target = AttackTarget(
        group=SimpleNamespace(id=CHANNEL_ID + 100),
        root_reply_id=ROOT_REPLY_ID,
        slowmode_seconds=None,
        channel_id=CHANNEL_ID,
    )
    fake = Resolver(target)

    async def join(client: Any, resolved: AttackTarget) -> None:
        return None

    monkeypatch.setattr(attack_service_module, "resolve_target", fake)
    monkeypatch.setattr(attack_service_module, "join_if_needed", join)
    return fake


class FakeRuntime:
    def __init__(
        self,
        agent_id: UUID,
        *,
        state: AgentRuntimeState = AgentRuntimeState.RUNNING,
    ) -> None:
        self.agent_id = agent_id
        self.state = state
        self.attack_id: UUID | None = None
        self.entered: list[UUID] = []
        self.calls: list[dict[str, Any]] = []
        self.notes: list[tuple[str, str]] = []
        self.note_calls = 0
        self.note_error: BaseException | None = None
        self.script: list[Any] = []
        self.block: asyncio.Event | None = None
        self.lease_error: BaseException | None = None
        self.lease_count = 0
        self.message_id = 500

    def enter_attack(self, attack_id: UUID) -> None:
        self.attack_id = attack_id
        self.entered.append(attack_id)

    def exit_attack(self) -> None:
        self.attack_id = None

    @asynccontextmanager
    async def leased_telegram_client(self) -> AsyncIterator[Any]:
        if self.lease_error is not None:
            raise self.lease_error
        self.lease_count += 1
        yield SimpleNamespace(name="client")

    async def send_humanized_comment(
        self,
        client: Any,
        *,
        entity: Any,
        text: str,
        media: Sequence[str],
        reply_to: int | None = None,
        random_id: int,
    ) -> Any:
        self.calls.append(
            {
                "entity": entity,
                "text": text,
                "media": tuple(media),
                "reply_to": reply_to,
                "random_id": random_id,
            }
        )
        if self.block is not None:
            await self.block.wait()
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, BaseException):
                raise item
            return SimpleNamespace(id=item)
        self.message_id += 1
        return SimpleNamespace(id=self.message_id)

    async def remember_note(self, peer: str, text: str) -> None:
        self.note_calls += 1
        if self.note_error is not None:
            raise self.note_error
        self.notes.append((peer, text))


class FakeManager:
    def __init__(self, runtimes: Sequence[FakeRuntime]) -> None:
        self.runtimes_by_id = {runtime.agent_id: runtime for runtime in runtimes}
        self.start_calls: list[UUID] = []
        self.start_failures: set[UUID] = set()

    async def get_runtime(self, agent_id: UUID) -> FakeRuntime:
        runtime = self.runtimes_by_id.get(agent_id)
        if runtime is None:
            raise LookupError(f"Нет рантайма {agent_id}")
        return runtime

    async def start_agent(self, agent_id: UUID) -> None:
        self.start_calls.append(agent_id)
        if agent_id in self.start_failures:
            raise RuntimeError("Telegram не пускает")
        self.runtimes_by_id[agent_id].state = AgentRuntimeState.RUNNING

    def runtimes(self) -> list[FakeRuntime]:
        return list(self.runtimes_by_id.values())


class FakeActivity:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def record(
        self,
        *,
        agent_id: UUID,
        event_type: str,
        status: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(
            {
                "agent_id": agent_id,
                "event_type": event_type,
                "status": status,
                "payload": payload or {},
            }
        )

    def types(self) -> list[str]:
        return [event["event_type"] for event in self.events]


class FakeRepo(FakeAttackGate):
    """Поверхность репозитория атак на памяти: хватает для жизненного цикла сервиса."""

    def __init__(self) -> None:
        super().__init__()
        self.claims: list[tuple[UUID, UUID]] = []
        self.settlements: list[tuple[SlotClaim, SendOutcome, datetime, datetime]] = []
        self.targets: list[tuple[UUID, int | None, int | None, int | None]] = []
        self.cleared_media: list[tuple[UUID, int]] = []

    async def create(
        self,
        owner_id: UUID,
        config: AttackConfig,
        agent_ids: Sequence[UUID],
        now: datetime,
    ) -> AttackView:
        for other in self.attacks.values():
            for participation in other.participations:
                if participation.agent_id in agent_ids and participation.status in LIVE:
                    self._exit(other, participation, ExitReason.MOVED)
                    self._cancel_if_empty(other, now)
        return await super().create(owner_id, config, list(agent_ids), now)

    async def claim(
        self, attack_id: UUID, agent_id: UUID, now: datetime, rng: random.Random
    ) -> SlotClaim | None:
        self.claims.append((attack_id, agent_id))
        return await super().claim(attack_id, agent_id, now, rng)

    async def settle(
        self,
        claim: SlotClaim,
        outcome: SendOutcome,
        now: datetime,
        next_at: datetime,
    ) -> Settlement:
        self.settlements.append((claim, outcome, now, next_at))
        return await super().settle(claim, outcome, now, next_at)

    async def live_participation(self, agent_id: UUID) -> ParticipationView | None:
        for attack in self.attacks.values():
            for participation in reversed(attack.participations):
                if participation.agent_id == agent_id and participation.status in LIVE:
                    return self._participation_view(participation)
        return None

    async def load_running(self) -> list[AttackView]:
        return [
            self._view(attack)
            for attack in self.attacks.values()
            if attack.status is AttackStatus.RUNNING
        ]

    async def list_attacks(self, owner_id: UUID) -> list[AttackView]:
        return [
            self._view(attack) for attack in self.attacks.values() if attack.owner_id == owner_id
        ]

    async def agent_availability(self, owner_id: UUID) -> list[AgentAvailability]:
        return []

    async def cancel(self, attack_id: UUID, reason: AttackEndReason, now: datetime) -> AttackView:
        attack = self._attack(attack_id)
        if attack.status in CLOSED:
            return self._view(attack)
        for participation in attack.participations:
            if participation.status in LIVE:
                self._exit(attack, participation, ExitReason.ATTACK_CANCELLED)
        attack.status = AttackStatus.CANCELLED
        attack.finished_at = now
        attack.end_reason = reason
        return self._view(attack)

    async def finish(self, attack_id: UUID, reason: AttackEndReason, now: datetime) -> AttackView:
        attack = self._attack(attack_id)
        if attack.status in CLOSED:
            return self._view(attack)
        if attack.claimed_count != attack.sent_count:
            return self._view(attack)
        attack.status = AttackStatus.FINISHED
        attack.finished_at = now
        attack.end_reason = reason
        for participation in attack.participations:
            if participation.status in LIVE:
                self._exit(attack, participation, ExitReason.ATTACK_FINISHED)
        return self._view(attack)

    async def assign(
        self, attack_id: UUID, agent_id: UUID, owner_id: UUID, now: datetime
    ) -> ParticipationView:
        attack = self._attack(attack_id)
        if attack.owner_id != owner_id:
            raise AttackNotFoundError(f"Атака {attack_id} не найдена у владельца")
        for other in self.attacks.values():
            for participation in other.participations:
                if participation.agent_id == agent_id and participation.status in LIVE:
                    self._exit(other, participation, ExitReason.MOVED)
                    self._cancel_if_empty(other, now)
        participation = _FakeParticipation(
            id=uuid4(),
            attack_id=attack.id,
            agent_id=agent_id,
            status=(
                AttackAgentStatus.ACTIVE
                if attack.status is AttackStatus.RUNNING
                else AttackAgentStatus.ASSIGNED
            ),
        )
        attack.participations.append(participation)
        return self._participation_view(participation)

    async def pause(
        self, attack_id: UUID, agent_id: UUID, owner_id: UUID, now: datetime
    ) -> ParticipationView:
        attack = self._attack(attack_id)
        if attack.owner_id != owner_id:
            raise AttackNotFoundError(f"Атака {attack_id} не найдена у владельца")
        live = next(
            (
                participation
                for participation in reversed(attack.participations)
                if participation.agent_id == agent_id and participation.status in LIVE
            ),
            None,
        )
        if live is None:
            raise AttackNotFoundError(f"Мимик {agent_id} не участвует в атаке {attack_id}")
        self._exit(attack, live, ExitReason.PAUSED)
        self._cancel_if_empty(attack, now)
        return self._participation_view(live)

    async def update(self, attack_id: UUID, patch: AttackPatch, now: datetime) -> AttackView:
        attack = self._attack(attack_id)
        attack.config = replace(
            attack.config,
            title=patch.title,
            texts=patch.texts,
            media_paths=patch.media_paths,
            limit=patch.limit,
        )
        if isinstance(patch.limit, MinutesLimit) and attack.started_at is not None:
            attack.deadline_at = attack.started_at + timedelta(minutes=patch.limit.minutes)
        else:
            attack.deadline_at = None
        return self._view(attack)

    async def repeat(self, attack_id: UUID, now: datetime) -> AttackView:
        old = self._attack(attack_id)
        if old.status not in CLOSED:
            raise AttackStateError("Повторить можно только закрытую атаку")
        repeated = _FakeAttack(id=uuid4(), owner_id=old.owner_id, config=old.config)
        for participation in old.participations:
            repeated.participations.append(
                _FakeParticipation(
                    id=uuid4(),
                    attack_id=repeated.id,
                    agent_id=participation.agent_id,
                    status=AttackAgentStatus.ASSIGNED,
                )
            )
        self.attacks[repeated.id] = repeated
        return self._view(repeated)

    async def set_target(
        self,
        attack_id: UUID,
        channel_id: int | None,
        anchor_id: int | None,
        slowmode_seconds: int | None,
        now: datetime,
    ) -> None:
        self.targets.append((attack_id, channel_id, anchor_id, slowmode_seconds))

    async def clear_media(self, attack_id: UUID, participation_id: UUID, random_id: int) -> bool:
        attack = self._attack(attack_id)
        participation = next(
            (row for row in attack.participations if row.id == participation_id), None
        )
        if participation is None or participation.pending_random_id != random_id:
            return False
        participation.pending_media = ()
        self.cleared_media.append((participation_id, random_id))
        return True

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
                self._cancel_if_empty(
                    attack,
                    now,
                    end_reason=(
                        AttackEndReason.TARGET_UNAVAILABLE
                        if reason is ExitReason.TARGET_UNAVAILABLE
                        else AttackEndReason.NO_AGENTS
                    ),
                )
                return

    def _cancel_if_empty(
        self,
        attack: _FakeAttack,
        now: datetime,
        *,
        end_reason: AttackEndReason = AttackEndReason.NO_AGENTS,
    ) -> None:
        if attack.status is not AttackStatus.RUNNING:
            return
        if any(row.status is not AttackAgentStatus.EXITED for row in attack.participations):
            return
        attack.status = AttackStatus.CANCELLED
        attack.finished_at = now
        attack.end_reason = end_reason


ServiceFactory = Callable[..., tuple[AttackService, FakeManager, FakeActivity, Clock]]


@pytest.fixture
async def service_factory() -> AsyncIterator[ServiceFactory]:
    created: list[AttackService] = []

    def build(
        repo: FakeRepo,
        runtimes: Sequence[FakeRuntime],
        *,
        clock: Clock | None = None,
        activity: FakeActivity | None = None,
    ) -> tuple[AttackService, FakeManager, FakeActivity, Clock]:
        chosen_clock = clock or Clock()
        chosen_activity = activity or FakeActivity()
        manager = FakeManager(runtimes)
        service = AttackService(
            manager,
            repo,
            chosen_activity,
            clock=chosen_clock,
            rng=random.Random(7),
            sleep=chosen_clock.sleep,
        )
        created.append(service)
        return service, manager, chosen_activity, chosen_clock

    yield build
    for service in created:
        await service.close()


async def _wait_for(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("условие не наступило за отведённое время")
        await asyncio.sleep(0.001)


def _stored(repo: FakeRepo, attack_id: UUID) -> _FakeAttack:
    return repo.attacks[attack_id]


def _participation(attack: _FakeAttack, agent_id: UUID) -> _FakeParticipation:
    return next(row for row in attack.participations if row.agent_id == agent_id)


def _events(activity: FakeActivity) -> list[str]:
    return activity.types()


async def test_start_requires_an_assigned_agent(service_factory: ServiceFactory) -> None:
    repo = FakeRepo()
    attack = await repo.create(uuid4(), _config(), [], NOW)
    service, manager, _, _ = service_factory(repo, [])

    with pytest.raises(AttackStateError):
        await service.start_attack(attack.id)

    assert manager.start_calls == []
    assert _stored(repo, attack.id).status is AttackStatus.DRAFT
    assert service.attack_of(uuid4()) is None


async def test_start_starts_a_stopped_runtime_and_enters_the_attack(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id, state=AgentRuntimeState.STOPPED)
    runtime.block = asyncio.Event()
    service, manager, activity, _ = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(), [agent_id], NOW)

    view = await service.start_attack(attack.id)

    assert view.status is AttackStatus.RUNNING
    assert manager.start_calls == [agent_id]
    assert runtime.state is AgentRuntimeState.RUNNING
    assert runtime.attack_id == attack.id
    assert service.attack_of(agent_id) == attack.id
    assert _events(activity) == ["attack.started"]


async def test_a_mimic_that_cannot_start_leaves_and_the_attack_cancels(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id, state=AgentRuntimeState.STOPPED)
    service, manager, activity, _ = service_factory(repo, [runtime])
    manager.start_failures.add(agent_id)
    attack = await repo.create(uuid4(), _config(), [agent_id], NOW)

    view = await service.start_attack(attack.id)

    assert view.status is AttackStatus.CANCELLED
    assert view.end_reason is AttackEndReason.NO_AGENTS
    participation = view.participations[0]
    assert participation.status is AttackAgentStatus.EXITED
    assert participation.exit_reason is ExitReason.START_FAILED
    assert runtime.notes and "не удалось запустить" in runtime.notes[0][1]
    assert runtime.attack_id is None
    assert "attack.agent_left" in _events(activity)


async def test_pausing_the_last_mimic_cancels_the_attack_and_keeps_a_note(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.block = asyncio.Event()
    service, _, activity, _ = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(), [agent_id], NOW)
    await service.start_attack(attack.id)

    participation = await service.pause_agent(attack.id, agent_id)

    assert participation.status is AttackAgentStatus.EXITED
    assert participation.exit_reason is ExitReason.PAUSED
    stored = _stored(repo, attack.id)
    assert stored.status is AttackStatus.CANCELLED
    assert stored.end_reason is AttackEndReason.NO_AGENTS
    assert runtime.notes and "пауза" in runtime.notes[0][1]
    assert runtime.attack_id is None
    assert service.attack_of(agent_id) is None
    assert {"attack.agent_left", "attack.cancelled"} <= set(_events(activity))


async def test_assigning_a_mimic_moves_it_out_of_the_previous_attack(
    service_factory: ServiceFactory,
    resolver: Resolver,
) -> None:
    repo = FakeRepo()
    owner_id = uuid4()
    moved_agent = uuid4()
    staying_agent = uuid4()
    moved = FakeRuntime(moved_agent)
    moved.block = asyncio.Event()
    staying = FakeRuntime(staying_agent)
    staying.block = asyncio.Event()
    service, _, _, _ = service_factory(repo, [moved, staying])
    first = await repo.create(owner_id, _config(), [moved_agent, staying_agent], NOW)
    await service.start_attack(first.id)
    await _wait_for(lambda: bool(resolver.calls) and bool(moved.calls))
    second = await repo.create(owner_id, _config(), [], NOW)

    participation = await service.assign_agent(second.id, moved_agent)

    assert participation.status is AttackAgentStatus.ASSIGNED
    first_view = await repo.load(first.id)
    assert first_view is not None
    assert first_view.status is AttackStatus.RUNNING
    old = _participation(_stored(repo, first.id), moved_agent)
    assert old.status is AttackAgentStatus.EXITED
    assert old.exit_reason is ExitReason.MOVED
    assert moved.notes and "перенос" in moved.notes[0][1]
    assert moved.attack_id is None
    assert staying.attack_id == first.id
    assert service.attack_of(moved_agent) is None

    moved.block = None
    before = len(resolver.calls)
    await service.start_attack(second.id)

    await _wait_for(lambda: len(resolver.calls) > before)
    assert len(resolver.calls) == before + 1


async def test_assigning_to_a_running_attack_starts_the_sender(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    first_agent = uuid4()
    second_agent = uuid4()
    first_runtime = FakeRuntime(first_agent)
    first_runtime.block = asyncio.Event()
    second_runtime = FakeRuntime(second_agent)
    second_runtime.block = asyncio.Event()
    service, _, activity, _ = service_factory(repo, [first_runtime, second_runtime])
    attack = await repo.create(uuid4(), _config(), [first_agent], NOW)
    await service.start_attack(attack.id)

    participation = await service.assign_agent(attack.id, second_agent)

    assert participation.status is AttackAgentStatus.ACTIVE
    assert second_runtime.attack_id == attack.id
    assert service.attack_of(second_agent) == attack.id
    assert "attack.started" in _events(activity)


async def test_stopping_a_mimic_removes_it_and_writes_the_note(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    first_agent = uuid4()
    second_agent = uuid4()
    first = FakeRuntime(first_agent)
    first.block = asyncio.Event()
    second = FakeRuntime(second_agent)
    second.block = asyncio.Event()
    service, _, _, _ = service_factory(repo, [first, second])
    attack = await repo.create(uuid4(), _config(), [first_agent, second_agent], NOW)
    await service.start_attack(attack.id)

    await service.on_agent_stopped(first_agent)

    stored = _stored(repo, attack.id)
    assert stored.status is AttackStatus.RUNNING
    stopped = _participation(stored, first_agent)
    assert stopped.status is AttackAgentStatus.EXITED
    assert stopped.exit_reason is ExitReason.AGENT_STOPPED
    assert first.notes and "агент остановлен" in first.notes[0][1]
    assert first.attack_id is None
    assert service.attack_of(first_agent) is None
    assert service.attack_of(second_agent) == attack.id


async def test_removing_the_last_mimic_cancels_the_attack(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.block = asyncio.Event()
    service, _, _, _ = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(), [agent_id], NOW)
    await service.start_attack(attack.id)

    await service.on_agent_removed(agent_id)

    stored = _stored(repo, attack.id)
    assert stored.status is AttackStatus.CANCELLED
    assert stored.end_reason is AttackEndReason.NO_AGENTS
    participation = _participation(stored, agent_id)
    assert participation.exit_reason is ExitReason.AGENT_REMOVED
    assert runtime.notes
    assert runtime.attack_id is None


async def test_cancel_stops_the_senders_and_writes_every_note(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agents = [uuid4(), uuid4()]
    runtimes = [FakeRuntime(agent_id) for agent_id in agents]
    for runtime in runtimes:
        runtime.block = asyncio.Event()
    service, _, activity, _ = service_factory(repo, runtimes)
    attack = await repo.create(uuid4(), _config(), agents, NOW)
    await service.start_attack(attack.id)

    view = await service.cancel_attack(attack.id, AttackEndReason.CANCELLED_BY_USER)

    assert view.status is AttackStatus.CANCELLED
    assert view.end_reason is AttackEndReason.CANCELLED_BY_USER
    assert all(
        row.status is AttackAgentStatus.EXITED and row.exit_reason is ExitReason.ATTACK_CANCELLED
        for row in view.participations
    )
    assert all(runtime.notes for runtime in runtimes)
    assert all(runtime.attack_id is None for runtime in runtimes)
    assert _events(activity).count("attack.cancelled") == 2
    assert _events(activity).count("attack.agent_left") == 2
    assert service._runs == {}


async def test_repeat_creates_a_draft_without_a_run(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.script = [601]
    service, _, _, _ = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(limit=MessagesLimit(1)), [agent_id], NOW)
    await service.start_attack(attack.id)
    await _wait_for(lambda: _stored(repo, attack.id).status is AttackStatus.FINISHED)

    repeated = await service.repeat_attack(attack.id)

    assert repeated.status is AttackStatus.DRAFT
    assert repeated.config.limit == attack.config.limit
    assert repeated.participations[0].status is AttackAgentStatus.ASSIGNED
    assert service.attack_of(agent_id) is None


async def test_a_successful_send_at_the_limit_finishes_the_attack(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.script = [701]
    service, _, activity, _ = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(limit=MessagesLimit(1)), [agent_id], NOW)

    await service.start_attack(attack.id)
    await _wait_for(
        lambda: (
            _stored(repo, attack.id).status is AttackStatus.FINISHED
            and _stored(repo, attack.id).participations[0].note_written_at is not None
        )
    )

    stored = _stored(repo, attack.id)
    assert stored.end_reason is AttackEndReason.LIMIT_REACHED
    participation = stored.participations[0]
    assert participation.status is AttackAgentStatus.EXITED
    assert participation.exit_reason is ExitReason.ATTACK_FINISHED
    assert participation.sent_count == 1
    assert runtime.attack_id is None
    assert runtime.notes
    assert "attack.comment_sent" in _events(activity)
    assert repo.targets[0][1:] == (CHANNEL_ID, ROOT_REPLY_ID, None)


async def test_the_first_comment_waits_for_the_accounts_slow_mode_window(
    service_factory: ServiceFactory,
    resolver: Resolver,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.script = [706]
    service, _, _, clock = service_factory(repo, [runtime])
    open_at = NOW + timedelta(minutes=4)
    resolver.target = replace(
        resolver.target,
        slowmode_seconds=300,
        slowmode_next_send_at=open_at,
    )
    attack = await repo.create(uuid4(), _config(limit=MessagesLimit(1)), [agent_id], NOW)

    await service.start_attack(attack.id)
    await _wait_for(lambda: bool(repo.settlements))

    sent_at = repo.settlements[0][2]
    assert sent_at >= open_at
    assert clock.now >= open_at


async def test_a_slow_mode_error_uses_the_current_interval_from_telegram(
    service_factory: ServiceFactory,
    resolver: Resolver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.script = [errors.SlowModeWaitError(None, 30), 707]
    service, _, _, _ = service_factory(repo, [runtime])
    resolver.target = replace(resolver.target, slowmode_seconds=300)

    async def refresh(client: Any, current: AttackTarget) -> AttackTarget:
        return replace(current, slowmode_seconds=600)

    monkeypatch.setattr(attack_service_module, "refresh_slow_mode", refresh)
    attack = await repo.create(uuid4(), _config(limit=MessagesLimit(1)), [agent_id], NOW)

    await service.start_attack(attack.id)
    await _wait_for(lambda: bool(repo.settlements))

    _, outcome, failed_at, retry_at = repo.settlements[0]
    assert outcome.failure is SendFailure.SLOW_MODE
    assert (retry_at - failed_at).total_seconds() >= 600 * 1.15


async def test_a_partially_delivered_album_sends_the_rest_in_the_next_chunk(
    service_factory: ServiceFactory,
    resolver: Resolver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.script = [errors.SlowModeWaitError(None, 300)]
    service, _, activity, _ = service_factory(repo, [runtime])
    resolver.target = replace(resolver.target, slowmode_seconds=300)
    media = tuple(f"attacks/owner/{index}.jpg" for index in range(10))

    async def recent(client: Any, target: AttackTarget, since: datetime) -> list[int]:
        return list(range(101, 109))

    monkeypatch.setattr(attack_service_module, "recent_comment_messages", recent)
    attack = await repo.create(
        uuid4(),
        _config(limit=MinutesLimit(1), media_paths=media),
        [agent_id],
        NOW,
    )

    await service.start_attack(attack.id)
    await _wait_for(lambda: _stored(repo, attack.id).status is AttackStatus.FINISHED)

    first_claim, first_outcome, failed_at, retry_at = repo.settlements[0]
    second_claim, second_outcome, _, _ = repo.settlements[1]
    assert first_claim.message_count == 10
    assert first_outcome.kind == "sent"
    assert first_outcome.delivered == 8
    assert retry_at > failed_at
    rest = first_claim.media[8:]
    assert second_claim.message_count == 2
    assert second_claim.media == rest
    assert second_claim.text == ""
    assert second_claim.random_id == first_claim.random_id + 8
    assert second_outcome.kind == "sent"
    assert len(runtime.calls) == 2
    assert runtime.calls[1]["media"] == rest
    assert runtime.calls[1]["random_id"] == first_claim.random_id + 8
    stored = _stored(repo, attack.id)
    assert stored.sent_count == 10
    assert stored.claimed_count == 10
    assert stored.participations[0].last_error is None
    assert "attack.comment_failed" not in _events(activity)
    assert _events(activity).count("attack.comment_sent") == 2


async def test_the_limit_counts_each_album_image_as_a_message(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.script = [711]
    media = tuple(f"attacks/owner/{index}.jpg" for index in range(10))
    service, _, _, _ = service_factory(repo, [runtime])
    attack = await repo.create(
        uuid4(),
        _config(limit=MessagesLimit(3), media_paths=media),
        [agent_id],
        NOW,
    )

    await service.start_attack(attack.id)
    await _wait_for(
        lambda: (
            _stored(repo, attack.id).status is AttackStatus.FINISHED
            and _stored(repo, attack.id).participations[0].note_written_at is not None
        )
    )

    stored = _stored(repo, attack.id)
    assert stored.sent_count == 3
    assert stored.end_reason is AttackEndReason.LIMIT_REACHED
    assert stored.participations[0].sent_count == 3
    assert len(runtime.calls[0]["media"]) == 3


async def test_the_deadline_finishes_the_attack_after_the_reservation_settles(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.block = asyncio.Event()
    runtime.script = [702]
    service, _, _, clock = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(limit=MinutesLimit(1)), [agent_id], NOW)
    await service.start_attack(attack.id)
    await _wait_for(lambda: bool(runtime.calls))

    clock.now = NOW + timedelta(minutes=2)
    runtime.block.set()

    await _wait_for(lambda: _stored(repo, attack.id).status is AttackStatus.FINISHED)
    stored = _stored(repo, attack.id)
    assert stored.end_reason is AttackEndReason.DEADLINE


async def test_a_transient_failure_backs_off_and_retries_the_same_random_id(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.script = [OSError("обрыв"), 703]
    service, _, _, _ = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(limit=MessagesLimit(1)), [agent_id], NOW)

    await service.start_attack(attack.id)
    await _wait_for(lambda: _stored(repo, attack.id).status is AttackStatus.FINISHED)

    assert len(runtime.calls) == 2
    assert runtime.calls[0]["random_id"] == runtime.calls[1]["random_id"]
    first_claim, first_outcome, first_now, first_next = repo.settlements[0]
    assert first_outcome.kind == "unknown"
    delay = (first_next - first_now).total_seconds()
    assert 5.0 <= delay <= 60.0
    assert _stored(repo, attack.id).sent_count == 1


async def test_flood_wait_waits_the_requested_time_and_releases_the_slot(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.script = [errors.FloodWaitError(None, 30), 705]
    service, _, _, _ = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(limit=MessagesLimit(1)), [agent_id], NOW)

    await service.start_attack(attack.id)
    await _wait_for(lambda: _stored(repo, attack.id).status is AttackStatus.FINISHED)

    claim, outcome, failed_at, retry_at = repo.settlements[0]
    assert outcome.kind == "not_sent"
    assert outcome.failure is SendFailure.FLOOD_WAIT
    assert (retry_at - failed_at).total_seconds() >= 30
    assert len(runtime.calls) == 2
    assert runtime.calls[0]["random_id"] != runtime.calls[1]["random_id"]


async def test_six_unknown_attempts_end_the_participation(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.script = [OSError("обрыв")] * 6
    service, _, activity, _ = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(), [agent_id], NOW)

    await service.start_attack(attack.id)
    await _wait_for(
        lambda: (
            _stored(repo, attack.id).status is AttackStatus.CANCELLED
            and _stored(repo, attack.id).participations[0].exit_reason is ExitReason.SEND_FAILED
        )
    )

    stored = _stored(repo, attack.id)
    participation = stored.participations[0]
    assert participation.sent_count == 0
    assert stored.claimed_count == stored.sent_count == 0
    assert len(runtime.calls) == 6
    assert _events(activity).count("attack.comment_failed") == 6


async def test_peer_flood_exits_the_mimic_and_cancels_the_empty_attack(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.script = [errors.PeerFloodError(None)]
    service, _, activity, _ = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(), [agent_id], NOW)

    await service.start_attack(attack.id)
    await _wait_for(
        lambda: (
            _stored(repo, attack.id).status is AttackStatus.CANCELLED
            and _stored(repo, attack.id).participations[0].note_written_at is not None
        )
    )

    stored = _stored(repo, attack.id)
    participation = stored.participations[0]
    assert participation.exit_reason is ExitReason.PEER_FLOOD
    assert participation.last_error == "peer_flood"
    assert runtime.notes
    assert runtime.attack_id is None
    assert {"attack.comment_failed", "attack.agent_left", "attack.cancelled"} <= set(
        _events(activity)
    )


async def test_an_unavailable_target_cancels_the_whole_attack(
    service_factory: ServiceFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def missing(client: Any, ref: TargetRef) -> AttackTarget:
        raise PostNotFoundError("поста нет")

    monkeypatch.setattr(attack_service_module, "resolve_target", missing)
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    service, _, _, _ = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(), [agent_id], NOW)

    await service.start_attack(attack.id)
    await _wait_for(
        lambda: (
            _stored(repo, attack.id).status is AttackStatus.CANCELLED
            and _stored(repo, attack.id).participations[0].note_written_at is not None
        )
    )

    stored = _stored(repo, attack.id)
    assert stored.end_reason is AttackEndReason.TARGET_UNAVAILABLE
    participation = stored.participations[0]
    assert participation.exit_reason is ExitReason.TARGET_UNAVAILABLE
    assert "недоступны" in (runtime.notes[0][1] if runtime.notes else "")


async def test_missing_media_falls_back_to_text_with_the_same_random_id(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.script = [CommentMediaUnavailable("файла нет"), 704]
    service, _, _, _ = service_factory(repo, [runtime])
    attack = await repo.create(
        uuid4(),
        _config(limit=MessagesLimit(1), media_paths=("attacks/owner/a.jpg",)),
        [agent_id],
        NOW,
    )

    await service.start_attack(attack.id)
    await _wait_for(lambda: _stored(repo, attack.id).status is AttackStatus.FINISHED)

    assert len(runtime.calls) == 2
    assert runtime.calls[0]["media"] == ("attacks/owner/a.jpg",)
    assert runtime.calls[1]["media"] == ()
    assert runtime.calls[0]["random_id"] == runtime.calls[1]["random_id"]
    assert repo.cleared_media == [
        (_stored(repo, attack.id).participations[0].id, runtime.calls[0]["random_id"])
    ]


async def test_creating_a_new_attack_moves_the_mimic_out_of_the_old_one(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    owner_id = uuid4()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.block = asyncio.Event()
    service, _, _, _ = service_factory(repo, [runtime])
    first = await repo.create(owner_id, _config(), [agent_id], NOW)
    await service.start_attack(first.id)

    second = await service.create_attack(owner_id, _config(), [agent_id])

    stored = _stored(repo, first.id)
    assert stored.status is AttackStatus.CANCELLED
    assert stored.end_reason is AttackEndReason.NO_AGENTS
    old = _participation(stored, agent_id)
    assert old.status is AttackAgentStatus.EXITED
    assert old.exit_reason is ExitReason.MOVED
    assert runtime.notes and "перенос" in runtime.notes[0][1]
    assert runtime.attack_id is None
    assert second.status is AttackStatus.DRAFT
    assert service.attack_of(agent_id) is None


async def test_reconcile_resumes_a_running_attack_after_restart(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.block = asyncio.Event()
    attack = await repo.create(uuid4(), _config(), [agent_id], NOW)
    await repo.start(attack.id, NOW)
    service, _, activity, _ = service_factory(repo, [runtime])

    await service.reconcile()

    assert runtime.attack_id == attack.id
    assert service.attack_of(agent_id) == attack.id
    run = service._runs[attack.id]
    first_task = run.senders[agent_id]
    assert "attack.started" in _events(activity)

    await service.reconcile()

    assert service._runs[attack.id] is run
    assert run.senders[agent_id] is first_task
    assert len(run.senders) == 1


async def test_runtime_change_clears_the_target_cache_and_keeps_the_sender(
    service_factory: ServiceFactory,
    resolver: Resolver,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.block = asyncio.Event()
    service, manager, _, _ = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(), [agent_id], NOW)
    await service.start_attack(attack.id)
    await _wait_for(lambda: bool(resolver.calls))
    task = service._runs[attack.id].senders[agent_id]

    replacement = FakeRuntime(agent_id)
    replacement.block = asyncio.Event()
    manager.runtimes_by_id[agent_id] = replacement
    await service.on_runtime_changed(agent_id)
    runtime.block.set()

    await _wait_for(lambda: len(resolver.calls) >= 2 and len(replacement.calls) >= 1)
    assert replacement.attack_id == attack.id
    assert service._runs[attack.id].senders[agent_id] is task


async def test_a_failed_note_is_written_once_by_reconcile(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.script = [errors.PeerFloodError(None)]
    runtime.note_error = RuntimeError("Mem0 недоступен")
    service, _, _, _ = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(), [agent_id], NOW)

    await service.start_attack(attack.id)
    await _wait_for(
        lambda: (
            _stored(repo, attack.id).status is AttackStatus.CANCELLED
            and runtime.note_calls >= 1
            and _stored(repo, attack.id).participations[0].note_written_at is None
        )
    )
    assert runtime.notes == []
    assert _stored(repo, attack.id).participations[0].note_written_at is None

    runtime.note_error = None
    await service.reconcile()
    await service.reconcile()

    assert len(runtime.notes) == 1
    assert runtime.note_calls == 2
    assert _stored(repo, attack.id).participations[0].note_written_at is not None


async def test_close_settles_the_in_flight_reservation_as_interrupted(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    runtime.block = asyncio.Event()
    service, _, _, _ = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(), [agent_id], NOW)
    await service.start_attack(attack.id)
    await _wait_for(lambda: bool(runtime.calls))

    await service.close()

    stored = _stored(repo, attack.id)
    assert stored.status is AttackStatus.RUNNING
    assert stored.sent_count == 0
    assert stored.claimed_count == 0
    assert stored.participations[0].status is AttackAgentStatus.ACTIVE
    assert "неизвестен" in (stored.participations[0].last_error or "")
    assert runtime.attack_id is None
    assert any(outcome.kind == "interrupted" for _, outcome, _, _ in repo.settlements)


async def test_lowering_the_limit_finishes_the_running_attack(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    attack = await repo.create(uuid4(), _config(), [agent_id], NOW)
    await repo.start(attack.id, NOW)
    stored = _stored(repo, attack.id)
    stored.sent_count = 1
    stored.claimed_count = 1
    stored.participations[0].sent_count = 1
    service, _, _, _ = service_factory(repo, [runtime])

    view = await service.update_attack(
        attack.id,
        AttackPatch(
            version=1,
            title="Розыгрыш",
            texts=("Участвую!",),
            media_paths=(),
            limit=MessagesLimit(1),
        ),
    )

    assert view.status is AttackStatus.FINISHED
    assert view.end_reason is AttackEndReason.LIMIT_REACHED
    assert runtime.notes


async def test_reading_a_missing_attack_raises_not_found(
    service_factory: ServiceFactory,
) -> None:
    repo = FakeRepo()
    service, _, _, _ = service_factory(repo, [])
    missing = uuid4()

    with pytest.raises(AttackNotFoundError):
        await service.start_attack(missing)
    with pytest.raises(AttackNotFoundError):
        await service.cancel_attack(missing, AttackEndReason.CANCELLED_BY_USER)


async def test_comments_disabled_counts_as_target_unavailable(
    service_factory: ServiceFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def disabled(client: Any, ref: TargetRef) -> AttackTarget:
        raise CommentsDisabledError("обсуждение закрыто")

    monkeypatch.setattr(attack_service_module, "resolve_target", disabled)
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    service, _, _, _ = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(), [agent_id], NOW)

    await service.start_attack(attack.id)
    await _wait_for(lambda: _stored(repo, attack.id).status is AttackStatus.CANCELLED)

    stored = _stored(repo, attack.id)
    assert stored.end_reason is AttackEndReason.TARGET_UNAVAILABLE
    assert stored.participations[0].exit_reason is ExitReason.TARGET_UNAVAILABLE


async def test_a_private_target_is_unavailable_rather_than_join_blocked(
    service_factory: ServiceFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def private(client: Any, ref: TargetRef) -> AttackTarget:
        raise errors.ChannelPrivateError(None)

    monkeypatch.setattr(attack_service_module, "resolve_target", private)
    repo = FakeRepo()
    agent_id = uuid4()
    runtime = FakeRuntime(agent_id)
    service, _, _, _ = service_factory(repo, [runtime])
    attack = await repo.create(uuid4(), _config(), [agent_id], NOW)

    await service.start_attack(attack.id)
    await _wait_for(lambda: _stored(repo, attack.id).status is AttackStatus.CANCELLED)

    stored = _stored(repo, attack.id)
    assert stored.end_reason is AttackEndReason.TARGET_UNAVAILABLE
    assert stored.participations[0].exit_reason is ExitReason.TARGET_UNAVAILABLE
