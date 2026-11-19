"""Сервис атаки: жизненный цикл кампании, задачи-отправители и восстановление.

Живёт рядом с менеджером агентов, как прогрев. Здесь всё, что происходит между
нажатием «Запустить» и последним комментарием: ростер, общий лимит, темп,
резервы, заметки и продолжение после рестарта. Отправку делает задача на каждое
активное участие; она берёт актуальный рантайм на каждой итерации, поэтому
перезагрузка агента не рвёт цикл. Счётчик пишет только репозиторий в транзакции
claim/settle, а гейт сериализует эти пары внутри процесса: сеть под замком не
идёт, а база остаётся границей durability.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, Protocol
from uuid import UUID

from telethon import errors

from mimic42.core.agent_runtime import (
    AgentLifecycleChangedError,
    AgentRuntimeState,
    CommentMediaUnavailable,
    TelegramAuthorizationRequired,
)
from mimic42.core.attack import (
    AttackAgentStatus,
    AttackConfig,
    AttackEndReason,
    AttackNotFoundError,
    AttackPatch,
    AttackStatus,
    AttackView,
    ExitReason,
    ParticipationView,
    SendFailure,
    SendOutcome,
    Settlement,
    SlotClaim,
    attack_end_reason,
    classify_outcome,
    classify_send_error,
    failure_text,
    next_send_at,
    note_text,
)
from mimic42.core.attack_join import JoinBlockedError, join_if_needed
from mimic42.core.attack_target import (
    AttackTarget,
    AttackTargetError,
    TargetNotWritableError,
    recent_comment_messages,
    refresh_slow_mode,
    resolve_target,
)
from mimic42.core.memory import settle_persistence

logger = logging.getLogger("mimic42.attack")

UNKNOWN_ATTEMPTS = 6
BACKOFF_MIN_SECONDS = 5.0
BACKOFF_MAX_SECONDS = 60.0
DUPLICATE_RETRY_SECONDS = 2.0
NO_SLOT_RETRY_SECONDS = 5.0
RECONCILE_INTERVAL_SECONDS = 12.0
SWEEP_TASK_NAME = "attack:reconcile"


class AttackRuntimePort(Protocol):
    """Что сервису нужно от рантайма: флаг режима, клиент и две операции."""

    @property
    def state(self) -> AgentRuntimeState: ...

    @property
    def attack_id(self) -> UUID | None: ...

    def enter_attack(self, attack_id: UUID) -> None: ...

    def exit_attack(self) -> None: ...

    def leased_telegram_client(self) -> AbstractAsyncContextManager[Any]: ...

    async def send_humanized_comment(
        self,
        client: Any,
        *,
        entity: Any,
        text: str,
        media: Sequence[str],
        reply_to: int | None = None,
        random_id: int,
    ) -> Any: ...

    async def remember_note(self, peer: str, text: str) -> None: ...


class AttackManagerPort(Protocol):
    """Менеджер агентов: рантайм по id, запуск и список живых рантаймов."""

    async def get_runtime(self, agent_id: UUID) -> AttackRuntimePort: ...

    async def start_agent(self, agent_id: UUID) -> None: ...

    def runtimes(self) -> Iterable[AttackRuntimePort]: ...


class AttackActivityPort(Protocol):
    """Телеметрия атаки; событие не источник правды и не роняет отправку."""

    async def record(
        self,
        *,
        agent_id: UUID,
        event_type: str,
        status: str,
        payload: dict[str, Any] | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class AgentAvailability:
    """Мимик и всё, что мешает или позволяет добавить его в атаку."""

    agent_id: UUID
    name: str
    state: AgentRuntimeState
    telegram_authorized: bool
    warmup_restricted_at: datetime | None
    active_attack_id: UUID | None


class AttackRepositoryPort(Protocol):
    """Транзакции кампании, резерва и заметок, на которые опирается сервис."""

    async def create(
        self,
        owner_id: UUID,
        config: AttackConfig,
        agent_ids: Sequence[UUID],
        now: datetime,
    ) -> AttackView: ...

    async def update(self, attack_id: UUID, patch: AttackPatch, now: datetime) -> AttackView: ...

    async def start(self, attack_id: UUID, now: datetime) -> AttackView: ...

    async def cancel(
        self, attack_id: UUID, reason: AttackEndReason, now: datetime
    ) -> AttackView: ...

    async def repeat(self, attack_id: UUID, now: datetime) -> AttackView: ...

    async def assign(
        self, attack_id: UUID, agent_id: UUID, owner_id: UUID, now: datetime
    ) -> ParticipationView: ...

    async def pause(
        self, attack_id: UUID, agent_id: UUID, owner_id: UUID, now: datetime
    ) -> ParticipationView: ...

    async def claim(
        self, attack_id: UUID, agent_id: UUID, now: datetime, rng: random.Random
    ) -> SlotClaim | None: ...

    async def settle(
        self,
        claim: SlotClaim,
        outcome: SendOutcome,
        now: datetime,
        next_at: datetime,
    ) -> Settlement: ...

    async def exit_participation(
        self, participation_id: UUID, reason: ExitReason, now: datetime
    ) -> None: ...

    async def mark_note_written(self, participation_id: UUID, now: datetime) -> bool: ...

    async def load(self, attack_id: UUID) -> AttackView | None: ...

    async def list_attacks(self, owner_id: UUID) -> list[AttackView]: ...

    async def agent_availability(self, owner_id: UUID) -> list[AgentAvailability]: ...

    async def load_running(self) -> list[AttackView]: ...

    async def pending_notes(self) -> list[ParticipationView]: ...

    async def live_participation(self, agent_id: UUID) -> ParticipationView | None: ...

    async def finish(
        self, attack_id: UUID, reason: AttackEndReason, now: datetime
    ) -> AttackView: ...

    async def set_target(
        self,
        attack_id: UUID,
        channel_id: int | None,
        anchor_id: int | None,
        slowmode_seconds: int | None,
        now: datetime,
    ) -> None: ...

    async def clear_media(
        self, attack_id: UUID, participation_id: UUID, random_id: int
    ) -> bool: ...


@dataclass
class _AttackRun:
    """Задачи-отправители и живой ростер одной идущей атаки."""

    attack_id: UUID
    senders: dict[UUID, asyncio.Task[None]] = field(default_factory=dict)
    agents: set[UUID] = field(default_factory=set)


class AttackGate:
    """Одна пара claim/settle на атаку, по замку на кампанию.

    Замок держит только транзакцию резерва: отправитель отпускает его до сети.
    Авторитет конкуренции — этот процесс, а не база: один uvicorn без workers.
    """

    def __init__(
        self,
        repo: AttackRepositoryPort,
        *,
        clock: Callable[[], datetime],
        rng: random.Random,
    ) -> None:
        self._repo = repo
        self._clock = clock
        self._rng = rng
        self._locks: dict[UUID, asyncio.Lock] = {}

    def _lock(self, attack_id: UUID) -> asyncio.Lock:
        return self._locks.setdefault(attack_id, asyncio.Lock())

    async def claim(self, attack_id: UUID, agent_id: UUID) -> SlotClaim | None:
        async with self._lock(attack_id):
            return await self._repo.claim(attack_id, agent_id, self._clock(), self._rng)

    async def settle(self, claim: SlotClaim, outcome: SendOutcome, next_at: datetime) -> Settlement:
        async with self._lock(claim.attack_id):
            return await self._repo.settle(claim, outcome, self._clock(), next_at)

    @asynccontextmanager
    async def guard(self, attack_id: UUID) -> AsyncIterator[None]:
        """Не дать финалу обогнать claim: лимит и статус проверяются под одним замком."""
        async with self._lock(attack_id):
            yield


_TERMINAL_EXITS: dict[SendFailure, ExitReason] = {
    SendFailure.PEER_FLOOD: ExitReason.PEER_FLOOD,
    SendFailure.BANNED_IN_CHANNEL: ExitReason.BANNED_IN_CHANNEL,
    SendFailure.JOIN_BLOCKED: ExitReason.JOIN_BLOCKED,
    SendFailure.SESSION_REVOKED: ExitReason.SESSION_REVOKED,
    SendFailure.TARGET_UNAVAILABLE: ExitReason.TARGET_UNAVAILABLE,
    SendFailure.SEND_FAILED: ExitReason.SEND_FAILED,
}


class AttackService:
    def __init__(
        self,
        manager: AttackManagerPort,
        repo: AttackRepositoryPort,
        activity: AttackActivityPort,
        *,
        clock: Callable[[], datetime] | None = None,
        rng: random.Random | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._manager = manager
        self._repo = repo
        self._activity = activity
        self._clock = clock or (lambda: datetime.now(UTC))
        self._rng = rng or random.Random()
        self._sleep = sleep or asyncio.sleep
        self._gate = AttackGate(repo, clock=self._clock, rng=self._rng)
        self._runs: dict[UUID, _AttackRun] = {}
        self._targets: dict[UUID, AttackTarget] = {}
        self._targets_recorded: set[tuple[UUID, UUID]] = set()
        self._noting: set[UUID] = set()
        self._recorded_exits: set[UUID] = set()
        self._announced_closed: set[UUID] = set()
        self._closing: set[UUID] = set()
        self._closed = False
        self._sweep: asyncio.Task[None] | None = None

    def _now(self) -> datetime:
        return self._clock()

    async def create_attack(
        self, owner_id: UUID, config: AttackConfig, agent_ids: Sequence[UUID]
    ) -> AttackView:
        previous = await self._previous_attacks(agent_ids)
        view = await self._repo.create(owner_id, config, tuple(agent_ids), self._now())
        for attack_id in previous:
            await self._refresh_attack(attack_id)
        return view

    async def update_attack(self, attack_id: UUID, patch: AttackPatch) -> AttackView:
        view = await self._repo.update(attack_id, patch, self._now())
        if view.status is AttackStatus.RUNNING:
            return await self._finish_if_reached(view)
        return view

    async def start_attack(self, attack_id: UUID) -> AttackView:
        current = await self._repo.load(attack_id)
        if current is None:
            raise AttackNotFoundError(f"Атака {attack_id} не найдена")
        if current.status is AttackStatus.RUNNING:
            await self._ensure_run(current)
            return await self._repo.load(attack_id) or current

        started = await self._repo.start(attack_id, self._now())
        run = self._run_for(attack_id)
        live = [row for row in started.participations if row.status is AttackAgentStatus.ACTIVE]
        for participation in live:
            if self._runs.get(attack_id) is not run:
                break
            if not await self._ensure_sender(attack_id, participation):
                continue
            await self._record(
                participation.agent_id,
                "attack.started",
                attack_id=attack_id,
            )

        if not any(run.senders) and live:
            fresh = await self._repo.load(attack_id)
            if fresh is not None and fresh.status is AttackStatus.RUNNING:
                fresh = await self._repo.cancel(attack_id, AttackEndReason.NO_AGENTS, self._now())
            await self._refresh_attack(attack_id)
        return await self._repo.load(attack_id) or started

    async def cancel_attack(self, attack_id: UUID, reason: AttackEndReason) -> AttackView:
        current = await self._repo.load(attack_id)
        if current is None:
            raise AttackNotFoundError(f"Атака {attack_id} не найдена")
        view = await self._repo.cancel(attack_id, reason, self._now())
        if view.status is not AttackStatus.RUNNING:
            await self._close_run(attack_id)
        return await self._repo.load(attack_id) or view

    async def repeat_attack(self, attack_id: UUID) -> AttackView:
        return await self._repo.repeat(attack_id, self._now())

    async def assign_agent(self, attack_id: UUID, agent_id: UUID) -> ParticipationView:
        attack = await self._repo.load(attack_id)
        if attack is None:
            raise AttackNotFoundError(f"Атака {attack_id} не найдена")
        previous = await self._repo.live_participation(agent_id)
        participation = await self._repo.assign(attack_id, agent_id, attack.owner_id, self._now())
        if previous is not None and previous.attack_id != attack_id:
            await self._refresh_attack(previous.attack_id)
        if participation.status is AttackAgentStatus.ACTIVE:
            self._run_for(attack_id)
            if await self._ensure_sender(attack_id, participation):
                await self._record(agent_id, "attack.started", attack_id=attack_id)
        return await self._latest_participation(attack_id, agent_id) or participation

    async def pause_agent(self, attack_id: UUID, agent_id: UUID) -> ParticipationView:
        attack = await self._repo.load(attack_id)
        if attack is None:
            raise AttackNotFoundError(f"Атака {attack_id} не найдена")
        live = await self._repo.live_participation(agent_id)
        run = self._runs.get(attack_id)
        if run is not None and live is not None and live.attack_id == attack_id:
            await self._stop_sender(run, agent_id)
        participation = await self._repo.pause(attack_id, agent_id, attack.owner_id, self._now())
        await self._refresh_attack(attack_id)
        return participation

    def attack_of(self, agent_id: UUID) -> UUID | None:
        for attack_id, run in self._runs.items():
            if agent_id in run.agents:
                return attack_id
        return None

    async def list(self, owner_id: UUID) -> Sequence[AttackView]:
        return await self._repo.list_attacks(owner_id)

    async def get(self, attack_id: UUID) -> AttackView | None:
        return await self._repo.load(attack_id)

    async def agent_availability(self, owner_id: UUID) -> Sequence[AgentAvailability]:
        return await self._repo.agent_availability(owner_id)

    async def on_runtime_ready(self, agent_id: UUID) -> None:
        if self._closed:
            return
        attack_id = self.attack_of(agent_id)
        if attack_id is None:
            return
        view = await self._repo.load(attack_id)
        if view is None or view.status is not AttackStatus.RUNNING:
            await self._refresh_attack(attack_id)
            return
        participation = _active_participation(view, agent_id)
        if participation is None:
            await self._refresh_attack(attack_id)
            return
        runtime = await self._manager.get_runtime(agent_id)
        runtime.enter_attack(attack_id)
        self._start_sender(attack_id, participation)

    async def on_runtime_changed(self, agent_id: UUID) -> None:
        self._targets.pop(agent_id, None)
        self._targets_recorded = {key for key in self._targets_recorded if key[1] != agent_id}
        attack_id = self.attack_of(agent_id)
        if attack_id is None:
            return
        runtime = await self._manager.get_runtime(agent_id)
        if runtime.attack_id != attack_id:
            runtime.enter_attack(attack_id)

    async def on_agent_stopped(self, agent_id: UUID) -> None:
        await self._agent_left(agent_id, ExitReason.AGENT_STOPPED)

    async def on_agent_removed(self, agent_id: UUID) -> None:
        await self._agent_left(agent_id, ExitReason.AGENT_REMOVED)

    async def start(self) -> None:
        """Поднять идущие атаки и сверять их с базой, пока живёт процесс.

        Первая сверка ждётся, чтобы после рестарта отправители встали до
        приёма запросов. Дальше ``reconcile`` повторяется по таймеру; он
        идемпотентен, поэтому пропущенный тик ничего не ломает.
        """
        if self._closed or self._sweep is not None:
            return
        try:
            await self.reconcile()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Первичная сверка атак не удалась")
        if self._closed or self._sweep is not None:
            return
        self._sweep = asyncio.create_task(self._reconcile_loop(), name=SWEEP_TASK_NAME)

    async def _reconcile_loop(self) -> None:
        while not self._closed:
            await self._sleep(RECONCILE_INTERVAL_SECONDS)
            if self._closed:
                return
            try:
                await self.reconcile()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Сверка атак не удалась")

    async def reconcile(self) -> None:
        """Свести память сервиса с базой: поднять задачи, финал, заметки.

        Повторный вызов ничего не создаёт заново: задача на участие уже лежит в
        ``run.senders``, заметка отмечена в строке, закрытая атака не попадает в
        ``load_running``.
        """
        for view in await self._repo.load_running():
            if self._closed:
                break
            if not _live_participations(view):
                await self._repo.cancel(view.id, AttackEndReason.NO_AGENTS, self._now())
                await self._close_run(view.id)
                continue
            reason = attack_end_reason(
                view.config.limit_type,
                view.config.limit_value,
                view.deadline_at,
                view.sent_count,
                view.claimed_count,
                self._now(),
            )
            if reason is not None:
                await self._finish_if_reached(view)
                continue

            run = self._run_for(view.id)
            for participation in view.participations:
                if participation.status is not AttackAgentStatus.ACTIVE:
                    continue
                if participation.agent_id in run.senders:
                    continue
                if not await self._ensure_sender(view.id, participation):
                    continue
                await self._record(
                    participation.agent_id,
                    "attack.started",
                    attack_id=view.id,
                )

        for pending in await self._repo.pending_notes():
            view = await self._repo.load(pending.attack_id)
            if view is not None:
                await self._write_note(view, pending)

    async def close(self) -> None:
        """Остановить отправителей, записав прерванные исходы.

        Строки атак остаются ``running``: следующий процесс поднимет их через
        ``reconcile`` и продолжит с сохранённого резерва.
        """
        sweep, self._sweep = self._sweep, None
        if sweep is not None and sweep is not asyncio.current_task():
            sweep.cancel()
            await asyncio.gather(sweep, return_exceptions=True)
        if self._closed and not self._runs:
            return
        self._closed = True
        for run in list(self._runs.values()):
            await self._stop_all(run)
        self._runs.clear()
        self._targets.clear()
        for runtime in self._manager.runtimes():
            if runtime.attack_id is not None:
                runtime.exit_attack()

    async def _ensure_runtime(self, agent_id: UUID, attack_id: UUID) -> AttackRuntimePort:
        runtime = await self._manager.get_runtime(agent_id)
        if runtime.state is not AgentRuntimeState.RUNNING:
            await self._manager.start_agent(agent_id)
            runtime = await self._manager.get_runtime(agent_id)
        if runtime.attack_id != attack_id:
            runtime.enter_attack(attack_id)
        return runtime

    async def _ensure_run(self, view: AttackView) -> None:
        run = self._run_for(view.id)
        for participation in view.participations:
            if participation.status is not AttackAgentStatus.ACTIVE:
                continue
            if participation.agent_id in run.senders:
                continue
            if await self._ensure_sender(view.id, participation):
                await self._record(
                    participation.agent_id,
                    "attack.started",
                    attack_id=view.id,
                )

    async def _ensure_sender(self, attack_id: UUID, participation: ParticipationView) -> bool:
        run = self._runs.get(attack_id)
        if run is None or self._closed:
            return False
        run.agents.add(participation.agent_id)
        try:
            await self._ensure_runtime(participation.agent_id, attack_id)
        except asyncio.CancelledError:
            run.agents.discard(participation.agent_id)
            raise
        except Exception:
            run.agents.discard(participation.agent_id)
            logger.warning(
                "Атака %s: мимик %s не запустился", attack_id, participation.agent_id, exc_info=True
            )
            await self._repo.exit_participation(
                participation.id, ExitReason.START_FAILED, self._now()
            )
            await self._refresh_attack(attack_id)
            return False
        return self._start_sender(attack_id, participation)

    def _run_for(self, attack_id: UUID) -> _AttackRun:
        run = self._runs.get(attack_id)
        if run is None:
            run = _AttackRun(attack_id=attack_id)
            self._runs[attack_id] = run
        return run

    def _start_sender(self, attack_id: UUID, participation: ParticipationView) -> bool:
        run = self._runs.get(attack_id)
        if run is None or self._closed:
            return False
        run.agents.add(participation.agent_id)
        if participation.agent_id in run.senders:
            return True
        task = asyncio.create_task(
            _Sender(self, attack_id, participation.agent_id, participation.id).run(),
            name=f"attack:{attack_id}:{participation.agent_id}",
        )
        run.senders[participation.agent_id] = task
        task.add_done_callback(partial(self._sender_done, run, participation.agent_id))
        return True

    def _sender_done(self, run: _AttackRun, agent_id: UUID, task: asyncio.Task[None]) -> None:
        if run.senders.get(agent_id) is task:
            run.senders.pop(agent_id, None)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Задача отправителя атаки упала", exc_info=error)

    async def _stop_sender(self, run: _AttackRun, agent_id: UUID) -> None:
        task = run.senders.get(agent_id)
        run.agents.discard(agent_id)
        self._targets.pop(agent_id, None)
        if task is None:
            return
        if task is asyncio.current_task():
            run.senders.pop(agent_id, None)
            return
        run.senders.pop(agent_id, None)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await self._clear_attack_flag(agent_id, run.attack_id)

    async def _stop_all(self, run: _AttackRun) -> None:
        current = asyncio.current_task()
        tasks: dict[UUID, asyncio.Task[None]] = {}
        for agent_id, task in list(run.senders.items()):
            run.senders.pop(agent_id, None)
            self._targets.pop(agent_id, None)
            if task is current:
                await self._clear_attack_flag(agent_id, run.attack_id)
                continue
            task.cancel()
            tasks[agent_id] = task
        run.agents.clear()
        if tasks:
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            for agent_id in tasks:
                await self._clear_attack_flag(agent_id, run.attack_id)

    async def _clear_attack_flag(self, agent_id: UUID, attack_id: UUID) -> None:
        """Снять флаг режима, даже если задача ещё не успела взять рантайм."""
        try:
            runtime = await self._manager.get_runtime(agent_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            return
        if runtime.attack_id == attack_id:
            runtime.exit_attack()

    async def _target_for(self, client: Any, attack_id: UUID, agent_id: UUID) -> AttackTarget:
        target = self._targets.get(agent_id)
        if target is not None:
            return target
        view = await self._repo.load(attack_id)
        if view is None:
            raise AttackNotFoundError(f"Атака {attack_id} не найдена")
        target = await resolve_target(client, view.config.target)
        await join_if_needed(client, target)
        self._targets[agent_id] = target
        key = (attack_id, agent_id)
        if key not in self._targets_recorded:
            try:
                await self._repo.set_target(
                    attack_id,
                    target.channel_id,
                    target.root_reply_id,
                    target.slowmode_seconds,
                    self._now(),
                )
            except Exception:
                logger.warning(
                    "Атака %s: не удалось сохранить цель мимика %s",
                    attack_id,
                    agent_id,
                    exc_info=True,
                )
            else:
                self._targets_recorded.add(key)
        return target

    async def _drop_media(self, claim: SlotClaim) -> None:
        await self._repo.clear_media(claim.attack_id, claim.participation_id, claim.random_id)

    async def _agent_left(self, agent_id: UUID, reason: ExitReason) -> None:
        live = await self._repo.live_participation(agent_id)
        if live is None:
            return
        attack_id = live.attack_id
        run = self._runs.get(attack_id)
        if run is not None:
            await self._stop_sender(run, agent_id)
        await self._repo.exit_participation(live.id, reason, self._now())
        await self._refresh_attack(attack_id)

    async def _write_note(self, view: AttackView, participation: ParticipationView) -> None:
        if participation.status is not AttackAgentStatus.EXITED:
            return
        if participation.note_written_at is not None or participation.id in self._noting:
            return
        self._noting.add(participation.id)
        try:
            runtime = await self._manager.get_runtime(participation.agent_id)
            await runtime.remember_note(
                peer=view.config.target.channel,
                text=note_text(view, participation),
            )
            await self._repo.mark_note_written(participation.id, self._now())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Атака %s: заметка мимика %s не записана",
                view.id,
                participation.agent_id,
                exc_info=True,
            )
        finally:
            self._noting.discard(participation.id)

    async def _refresh_attack(self, attack_id: UUID) -> AttackView | None:
        """Свести задачу с базой: снять выбывших, дописать заметки, закрыть атаку."""
        view = await self._repo.load(attack_id)
        if view is None:
            run = self._runs.pop(attack_id, None)
            if run is not None:
                await self._stop_all(run)
            return None
        run = self._runs.get(attack_id)
        if run is not None:
            active = {
                row.agent_id
                for row in view.participations
                if row.status is AttackAgentStatus.ACTIVE
            }
            for agent_id in list(run.senders):
                if agent_id not in active:
                    await self._stop_sender(run, agent_id)
            for agent_id in list(run.agents):
                if agent_id not in active:
                    run.agents.discard(agent_id)
                    self._targets.pop(agent_id, None)
        if view.status in (AttackStatus.FINISHED, AttackStatus.CANCELLED):
            await self._close_run(attack_id)
            return await self._repo.load(attack_id) or view
        for participation in view.participations:
            if participation.status is AttackAgentStatus.EXITED:
                await self._record_exit(view, participation)
                await self._write_note(view, participation)
        return view

    async def _close_run(self, attack_id: UUID) -> None:
        if attack_id in self._closing:
            return
        self._closing.add(attack_id)
        try:
            run = self._runs.pop(attack_id, None)
            if run is not None:
                await self._stop_all(run)
            view = await self._repo.load(attack_id)
            if view is None:
                return
            for participation in view.participations:
                if participation.status is not AttackAgentStatus.EXITED:
                    continue
                self._targets.pop(participation.agent_id, None)
                await self._record_exit(view, participation)
                await self._write_note(view, participation)
            await self._record_closed(view)
        finally:
            self._closing.discard(attack_id)

    async def _finish_if_reached(self, view: AttackView) -> AttackView:
        reason = attack_end_reason(
            view.config.limit_type,
            view.config.limit_value,
            view.deadline_at,
            view.sent_count,
            view.claimed_count,
            self._now(),
        )
        if reason is None:
            return view
        async with self._gate.guard(view.id):
            finished = await self._repo.finish(view.id, reason, self._now())
        if finished.status is not AttackStatus.RUNNING:
            await self._close_run(view.id)
            return await self._repo.load(view.id) or finished
        return finished

    async def _handle_no_slot(self, attack_id: UUID, participation_id: UUID) -> None:
        view = await self._repo.load(attack_id)
        if view is None:
            await self._refresh_attack(attack_id)
            return
        participation = _participation_by_id(view, participation_id)
        if (
            view.status in (AttackStatus.FINISHED, AttackStatus.CANCELLED)
            or participation is None
            or participation.status is not AttackAgentStatus.ACTIVE
        ):
            await self._refresh_attack(attack_id)
            return
        finished = await self._finish_if_reached(view)
        if finished.status is not AttackStatus.RUNNING:
            return
        await self._sleep(NO_SLOT_RETRY_SECONDS)

    async def _latest_participation(
        self, attack_id: UUID, agent_id: UUID
    ) -> ParticipationView | None:
        view = await self._repo.load(attack_id)
        if view is None:
            return None
        rows = [row for row in view.participations if row.agent_id == agent_id]
        return rows[-1] if rows else None

    async def _previous_attacks(self, agent_ids: Sequence[UUID]) -> set[UUID]:
        previous: set[UUID] = set()
        for agent_id in agent_ids:
            participation = await self._repo.live_participation(agent_id)
            if participation is not None:
                previous.add(participation.attack_id)
        return previous

    async def _record(self, agent_id: UUID, event_type: str, **payload: Any) -> None:
        if event_type == "attack.comment_failed":
            status = "failed"
        elif event_type == "attack.cancelled":
            status = "cancelled"
        else:
            status = "succeeded"
        try:
            await self._activity.record(
                agent_id=agent_id,
                event_type=event_type,
                status=status,
                payload={
                    key: str(value) if isinstance(value, UUID) else value
                    for key, value in payload.items()
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Событие %s не записано", event_type, exc_info=True)

    async def _record_exit(self, view: AttackView, participation: ParticipationView) -> None:
        if participation.id in self._recorded_exits:
            return
        self._recorded_exits.add(participation.id)
        await self._record(
            participation.agent_id,
            "attack.agent_left",
            attack_id=view.id,
            exit_reason=participation.exit_reason.value
            if participation.exit_reason is not None
            else None,
            sent_count=participation.sent_count,
        )

    async def _record_closed(self, view: AttackView) -> None:
        if view.id in self._announced_closed:
            return
        self._announced_closed.add(view.id)
        event_type = (
            "attack.finished" if view.status is AttackStatus.FINISHED else "attack.cancelled"
        )
        for participation in view.participations:
            if participation.status is not AttackAgentStatus.EXITED:
                continue
            await self._record_exit(view, participation)
            await self._record(
                participation.agent_id,
                event_type,
                attack_id=view.id,
                end_reason=view.end_reason.value if view.end_reason is not None else None,
            )


class _Sender:
    """Одна задача на участие: ждать темп, взять резерв, отправить, осесть.

    Рантайм перечитывается на каждом шаге: ``reload_agent`` заменяет объект, а
    задача продолжает работать с новым. Резерв и его исход живут в базе, поэтому
    смерть процесса между claim и settle сходится повтором с тем же ``random_id``.
    """

    def __init__(
        self,
        service: AttackService,
        attack_id: UUID,
        agent_id: UUID,
        participation_id: UUID,
    ) -> None:
        self._service = service
        self._attack_id = attack_id
        self._agent_id = agent_id
        self._participation_id = participation_id
        self._runtime: AttackRuntimePort | None = None
        self._unknown_rid: int | None = None
        self._unknown_attempts = 0
        self._settled_claim = False

    async def run(self) -> None:
        try:
            while True:
                try:
                    if not await self._step():
                        return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Атака %s: сбой отправителя мимика %s",
                        self._attack_id,
                        self._agent_id,
                    )
                    await self._service._sleep(self._backoff())
        finally:
            run = self._service._runs.get(self._attack_id)
            if run is not None and run.senders.get(self._agent_id) is asyncio.current_task():
                run.senders.pop(self._agent_id, None)
                run.agents.discard(self._agent_id)
            runtime = self._runtime
            if runtime is not None and runtime.attack_id == self._attack_id:
                runtime.exit_attack()

    async def _step(self) -> bool:
        view = await self._service._repo.load(self._attack_id)
        if view is None:
            return False
        if view.status is not AttackStatus.RUNNING:
            await self._service._refresh_attack(self._attack_id)
            return False
        participation = _participation_by_id(view, self._participation_id)
        if participation is None or participation.status is not AttackAgentStatus.ACTIVE:
            await self._service._refresh_attack(self._attack_id)
            return False

        now = self._service._now()
        if participation.next_at is not None and participation.next_at > now:
            await self._service._sleep((participation.next_at - now).total_seconds())
            return True
        target = self._service._targets.get(self._agent_id)
        if target is not None and target.slowmode_next_send_at is not None:
            open_at = target.slowmode_next_send_at
            if open_at > now:
                await self._service._sleep((open_at - now).total_seconds())
                return True

        try:
            runtime = await self._service._ensure_runtime(self._agent_id, self._attack_id)
        except TelegramAuthorizationRequired:
            return await self._abort(ExitReason.SESSION_REVOKED)
        except AgentLifecycleChangedError:
            await self._service._sleep(self._backoff())
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Атака %s: мимик %s не запустился",
                self._attack_id,
                self._agent_id,
                exc_info=True,
            )
            return await self._abort(ExitReason.START_FAILED)
        self._runtime = runtime

        claim: SlotClaim | None = None
        self._settled_claim = False
        try:
            async with runtime.leased_telegram_client() as client:
                try:
                    target = await self._service._target_for(
                        client, self._attack_id, self._agent_id
                    )
                except JoinBlockedError:
                    return await self._abort(ExitReason.JOIN_BLOCKED)
                except TargetNotWritableError:
                    return await self._abort(ExitReason.BANNED_IN_CHANNEL)
                except AttackTargetError:
                    return await self._abort_target()
                except errors.ChannelPrivateError:
                    return await self._abort_target()
                except TelegramAuthorizationRequired:
                    return await self._abort(ExitReason.SESSION_REVOKED)
                except asyncio.CancelledError:
                    raise
                except AttackNotFoundError:
                    await self._service._refresh_attack(self._attack_id)
                    return False
                except Exception as exc:
                    failure = classify_send_error(exc)
                    exit_reason = _TERMINAL_EXITS.get(failure)
                    if exit_reason is ExitReason.TARGET_UNAVAILABLE:
                        return await self._abort_target()
                    if exit_reason is not None:
                        return await self._abort(exit_reason)
                    await self._service._sleep(self._backoff())
                    return True

                open_at = target.slowmode_next_send_at
                if open_at is not None and open_at > self._service._now():
                    # Ждать снаружи аренды: она держит жизненный цикл агента.
                    return True

                try:
                    claim = await self._service._gate.claim(self._attack_id, self._agent_id)
                    if claim is None:
                        await self._service._handle_no_slot(self._attack_id, self._participation_id)
                        return True
                    return await self._deliver(runtime, client, target, claim)
                except asyncio.CancelledError:
                    if claim is not None and not self._settled_claim:
                        await settle_persistence(self._settle_interrupted(claim))
                    raise
        except asyncio.CancelledError:
            raise
        except TelegramAuthorizationRequired:
            return await self._abort(ExitReason.SESSION_REVOKED)
        except AgentLifecycleChangedError:
            await self._service._sleep(self._backoff())
        except Exception:
            # Отказ соединения до или после отправки: резерв уже осел либо его
            # нет, поэтому повтор идёт обычным путём, а не вторым комментарием.
            logger.warning(
                "Атака %s: соединение мимика %s сорвалось",
                self._attack_id,
                self._agent_id,
                exc_info=True,
            )
            await self._service._sleep(self._backoff())
        return True

    async def _deliver(
        self,
        runtime: AttackRuntimePort,
        client: Any,
        target: AttackTarget,
        claim: SlotClaim,
    ) -> bool:
        message: Any = None
        media = claim.media
        started_at = self._service._now()
        try:
            message = await runtime.send_humanized_comment(
                client,
                entity=target.group,
                text=claim.text,
                media=media,
                reply_to=target.root_reply_id,
                random_id=claim.random_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if media and (
                isinstance(exc, CommentMediaUnavailable)
                or classify_send_error(exc) is SendFailure.MEDIA_STALE
            ):
                await self._service._drop_media(claim)
                claim = replace(claim, media=())
                try:
                    message = await runtime.send_humanized_comment(
                        client,
                        entity=target.group,
                        text=claim.text,
                        media=(),
                        reply_to=target.root_reply_id,
                        random_id=claim.random_id,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as fallback_exc:
                    return await self._settle_failure(claim, fallback_exc, target, client)
            else:
                delivered = await self._partial_delivery(client, target, claim, started_at)
                if delivered is not None:
                    return await self._settle_partial(claim, target, delivered)
                return await self._settle_failure(claim, exc, target, client)

        message_id = _sent_message_id(message)
        settlement = await self._settle(
            claim,
            SendOutcome.sent(message_id),
            self._next_success_at(target),
        )
        self._unknown_rid = None
        self._unknown_attempts = 0
        await self._service._record(
            self._agent_id,
            "attack.comment_sent",
            attack_id=self._attack_id,
            random_id=claim.random_id,
            message_id=message_id,
        )
        if settlement.finished:
            await self._service._refresh_attack(self._attack_id)
        return True

    async def _partial_delivery(
        self,
        client: Any,
        target: AttackTarget,
        claim: SlotClaim,
        started_at: datetime,
    ) -> list[int] | None:
        """Сколько сообщений альбома успело дойти до ошибки отправки.

        Telegram принимает префикс альбома, а остаток отклоняет по slow mode.
        Без этой проверки отправленные сообщения не считались, а повтор с новым
        random_id дублировал уже доставленные картинки.
        """
        if not claim.media:
            return None
        try:
            ids = await recent_comment_messages(client, target, started_at - timedelta(seconds=5))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Атака %s: не удалось проверить доставленные сообщения",
                self._attack_id,
                exc_info=True,
            )
            return None
        if not ids:
            return None
        return ids[-claim.message_count :]

    async def _settle_partial(
        self,
        claim: SlotClaim,
        target: AttackTarget,
        delivered_ids: list[int],
    ) -> bool:
        delivered = min(len(delivered_ids), claim.message_count)
        message_id = min(delivered_ids)
        settlement = await self._settle(
            claim,
            SendOutcome.sent(message_id, delivered=delivered),
            self._next_success_at(target),
        )
        self._unknown_rid = None
        self._unknown_attempts = 0
        await self._service._record(
            self._agent_id,
            "attack.comment_sent",
            attack_id=self._attack_id,
            random_id=claim.random_id,
            message_id=message_id,
            delivered=delivered,
            expected=claim.message_count,
        )
        logger.warning(
            "Атака %s: мимик %s доставил %s из %s сообщений комментария",
            self._attack_id,
            self._agent_id,
            delivered,
            claim.message_count,
        )
        if settlement.finished:
            await self._service._refresh_attack(self._attack_id)
        return True

    async def _settle_failure(
        self,
        claim: SlotClaim,
        exc: BaseException,
        target: AttackTarget,
        client: Any,
    ) -> bool:
        failure = classify_send_error(exc)
        outcome = classify_outcome(exc)
        now = self._service._now()
        retry_after = _retry_after(exc)
        if failure is SendFailure.SLOW_MODE:
            target = await self._current_target(client, target)
            if retry_after is not None:
                target = replace(
                    target,
                    slowmode_seconds=max(retry_after, target.slowmode_seconds or 0),
                )
            self._service._targets[self._agent_id] = target
        if outcome.kind == "unknown":
            next_at = now + timedelta(
                seconds=(
                    DUPLICATE_RETRY_SECONDS if failure is SendFailure.DUPLICATE else self._backoff()
                )
            )
        else:
            next_at = next_send_at(
                now,
                target.slowmode_seconds,
                self._service._rng,
                failure,
                retry_after=retry_after,
            )
        await self._settle(claim, outcome, next_at)
        await self._service._record(
            self._agent_id,
            "attack.comment_failed",
            attack_id=self._attack_id,
            random_id=claim.random_id,
            failure=failure.value,
            error=failure_text(failure),
        )

        if outcome.kind == "unknown":
            self._bump_unknown(claim.random_id)
            if self._unknown_attempts >= UNKNOWN_ATTEMPTS:
                await self._settle(
                    claim,
                    SendOutcome.not_sent(SendFailure.SEND_FAILED),
                    now + timedelta(seconds=self._backoff()),
                )
                return await self._abort(ExitReason.SEND_FAILED)
            return True

        self._unknown_rid = None
        self._unknown_attempts = 0
        if failure in (SendFailure.FLOOD_WAIT, SendFailure.SLOW_MODE):
            return True

        exit_reason = _TERMINAL_EXITS.get(failure)
        if exit_reason is None:
            exit_reason = ExitReason.SEND_FAILED
        if exit_reason is ExitReason.TARGET_UNAVAILABLE:
            return await self._abort_target()
        return await self._abort(exit_reason)

    async def _current_target(self, client: Any, target: AttackTarget) -> AttackTarget:
        """Текущее окно из Telegram: кэш мог отстать от смены slow mode."""
        try:
            return await refresh_slow_mode(client, target)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Атака %s: не удалось перечитать slow mode",
                self._attack_id,
                exc_info=True,
            )
            return target

    async def _settle_interrupted(self, claim: SlotClaim) -> None:
        await self._service._gate.settle(claim, SendOutcome.interrupted(), self._service._now())

    async def _settle(
        self, claim: SlotClaim, outcome: SendOutcome, next_at: datetime
    ) -> Settlement:
        self._settled_claim = True
        try:
            return await self._service._gate.settle(claim, outcome, next_at)
        except BaseException:
            self._settled_claim = False
            raise

    def _next_success_at(self, target: AttackTarget) -> datetime:
        return next_send_at(
            self._service._now(),
            target.slowmode_seconds,
            self._service._rng,
        )

    def _backoff(self) -> float:
        return self._service._rng.uniform(BACKOFF_MIN_SECONDS, BACKOFF_MAX_SECONDS)

    def _bump_unknown(self, random_id: int) -> None:
        if self._unknown_rid == random_id:
            self._unknown_attempts += 1
        else:
            self._unknown_rid = random_id
            self._unknown_attempts = 1

    async def _abort(self, reason: ExitReason) -> bool:
        await self._service._repo.exit_participation(
            self._participation_id, reason, self._service._now()
        )
        await self._service._refresh_attack(self._attack_id)
        return False

    async def _abort_target(self) -> bool:
        await self._service._repo.exit_participation(
            self._participation_id, ExitReason.TARGET_UNAVAILABLE, self._service._now()
        )
        await self._service._repo.cancel(
            self._attack_id, AttackEndReason.TARGET_UNAVAILABLE, self._service._now()
        )
        await self._service._refresh_attack(self._attack_id)
        return False


def _active_participation(view: AttackView, agent_id: UUID) -> ParticipationView | None:
    rows = [
        row
        for row in view.participations
        if row.agent_id == agent_id and row.status is AttackAgentStatus.ACTIVE
    ]
    return rows[-1] if rows else None


def _participation_by_id(view: AttackView, participation_id: UUID) -> ParticipationView | None:
    return next((row for row in view.participations if row.id == participation_id), None)


def _live_participations(view: AttackView) -> list[ParticipationView]:
    return [
        row
        for row in view.participations
        if row.status in (AttackAgentStatus.ASSIGNED, AttackAgentStatus.ACTIVE)
    ]


def _retry_after(exc: BaseException) -> int | None:
    seconds = getattr(exc, "seconds", None)
    return seconds if isinstance(seconds, int) and seconds > 0 else None


def _sent_message_id(message: Any) -> int:
    direct = getattr(message, "id", None)
    if isinstance(direct, int):
        return direct
    for update in getattr(message, "updates", None) or ():
        candidate = getattr(update, "id", None)
        if isinstance(candidate, int) and hasattr(update, "random_id"):
            return candidate
    return 0
