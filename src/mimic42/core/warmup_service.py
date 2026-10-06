"""Сервис прогрева: раз в минуту решает, кому из мимиков пора начать диалог.

Живёт рядом с менеджером агентов и видит все его запущенные рантаймы. Что именно
написать и когда — решает ``core.warmup``; здесь только обход агентов, подбор пары,
отправка и режим восстановления ограниченных аккаунтов.

Режим восстановления. Аккаунт, которому Telegram запретил писать незнакомым
(PeerFloodError), сам диалогов не начинает: до ответа пользователя («восстановить»
или «удалить») он ничего не делает. Если выбрано восстановление, другие агенты
сами пишут ему чаще и дольше обычного, а он отвечает: Telegram прямо разрешает
ограниченному аккаунту отвечать тем, кто написал первым. Раз в несколько часов
@SpamBot спрашивают, снято ли ограничение. Насколько это ускоряет снятие, неизвестно:
Telegram досрочного снятия не обещает.

Состояние ограничения хранится в колонках ``agents`` (см. ``integrations.database_warmup``),
а не в настройках агента: форма настроек перезаписывает их целиком.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, time
from typing import Any, Literal, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from mimic42.core.agent_runtime import AgentRuntimeState, MimicAgentRuntime, OpenerResult
from mimic42.core.warmup import (
    EVENT_RECOVERED,
    EVENT_RECOVERY_STARTED,
    EVENT_RESTRICTED,
    SPAMBOT_CHECK_INTERVAL,
    DialogTracker,
    daily_slots,
    dialog_length,
    due_slot,
    merge_attempts,
    pick_opener,
    pick_partner,
    reply_delay,
    sender_may_open,
)

logger = logging.getLogger("mimic42.warmup")

TICK_SECONDS = 60.0
RESERVATION_KEEP_SECONDS = 2 * 24 * 3600

PairPolicy = Callable[[MimicAgentRuntime, MimicAgentRuntime], bool]
AttemptKind = Literal["sent", "received"]


def allow_everyone(_a: MimicAgentRuntime, _b: MimicAgentRuntime) -> bool:
    """Мимики общаются между всеми агентами платформы."""
    return True


def same_owner_only(a: MimicAgentRuntime, b: MimicAgentRuntime) -> bool:
    """Мимики общаются только с агентами того же владельца."""
    return a.config.owner_id == b.config.owner_id


def pair_policy_for(scope: str) -> PairPolicy:
    """Правило пар по настройке WARMUP_PARTNERS: ``own`` — только свои, иначе все."""
    return same_owner_only if scope == "own" else allow_everyone


class WarmupHistory(Protocol):
    """Что агент уже делал для прогрева: хранится вне процесса, переживает рестарт."""

    async def attempt_times_since(self, agent_id: UUID, since: datetime) -> list[datetime]:
        """Когда агент начинал диалоги с ``since`` (включая неудавшиеся)."""
        ...

    async def received_times_since(self, agent_id: UUID, since: datetime) -> list[datetime]:
        """Когда другие агенты начинали диалоги с этим агентом с ``since``."""
        ...

    async def used_openers(self, agent_id: UUID) -> list[str]:
        """Отправленные зачины, от старых к новым."""
        ...

    async def recent_partners(self, agent_id: UUID) -> list[UUID]:
        """С кем агент начинал диалоги, от старых к новым."""
        ...


class WarmupStateStore(Protocol):
    """Запись переходов состояния ограничения (ошибка записи не глотается, повтор безвреден)."""

    async def record(
        self, agent_id: UUID, event_type: str, payload: dict[str, Any] | None = None
    ) -> None: ...


class WarmupService:
    def __init__(
        self,
        runtimes: Callable[[], Iterable[MimicAgentRuntime]],
        history: WarmupHistory,
        *,
        state_store: WarmupStateStore | None = None,
        pair_policy: PairPolicy = allow_everyone,
        tracker: DialogTracker | None = None,
        now: Callable[[], datetime] | None = None,
        rng: random.Random | None = None,
        delay: Callable[[], float] | None = None,
    ) -> None:
        self._runtimes = runtimes
        self._history = history
        self._state_store = state_store
        self._pair_policy = pair_policy
        self._tracker = tracker or DialogTracker()
        self._now = now or (lambda: datetime.now(UTC))
        self._rng = rng or random.Random()
        self._delay = delay or (lambda: reply_delay(self._rng))
        self._last_spambot_check: dict[UUID, datetime] = {}
        # Попытка резервируется до отправки: запись в журнал приходит позже и может
        # не дойти, а до этого та же попытка не должна выглядеть «ещё не начатой».
        self._reserved: dict[tuple[AttemptKind, UUID], list[datetime]] = {}
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Warmup tick failed")
            await asyncio.sleep(TICK_SECONDS)

    # ── WarmupGate для рантаймов ──────────────────────────────────────────────

    def claim_reply(self, receiver_id: UUID, sender_telegram_id: int) -> bool | None:
        """None — обычная переписка, False — диалог окончен, True — ответить (и засчитать)."""
        pair = self._warmup_pair(receiver_id, sender_telegram_id)
        if pair is None:
            return None
        sender = pair[1]
        return self._tracker.claim_reply(receiver_id, sender.config.agent_id, now=self._now())

    def confirm_reply(self, receiver_id: UUID, sender_telegram_id: int) -> bool:
        """Не отменён ли разрешённый ответ, пока агент «был занят»: диалог идёт, оба в прогреве.

        Квоту не расходует (её уже занял ``claim_reply``). Отменённый ответ отбрасывается,
        а не превращается в обычную переписку без ограничителя длины.
        """
        pair = self._warmup_pair(receiver_id, sender_telegram_id)
        if pair is None:
            return False
        return self._tracker.is_active(receiver_id, pair[1].config.agent_id, now=self._now())

    def reply_delay_seconds(self) -> float:
        return self._delay()

    async def report_peer_flood(self, agent_id: UUID) -> None:
        """Telegram ответил PeerFloodError на любую отправку агента, не только на зачин."""
        runtime = self._agent_by_id(agent_id)
        if runtime is not None:
            await self._mark_restricted(runtime)

    def _warmup_pair(
        self, receiver_id: UUID, sender_telegram_id: int
    ) -> tuple[MimicAgentRuntime, MimicAgentRuntime] | None:
        """(получатель, отправитель), если это прогрев двух мимиков; иначе обычная переписка."""
        sender = self._agent_by_telegram_id(sender_telegram_id)
        receiver = self._agent_by_id(receiver_id)
        if sender is None or receiver is None:
            return None
        # Прогрев выключен хоть у одного: это обычная переписка, и ограничивать её нельзя.
        if not (receiver.config.warmup.enabled and sender.config.warmup.enabled):
            return None
        return receiver, sender

    def _agent_by_id(self, agent_id: UUID) -> MimicAgentRuntime | None:
        for runtime in self._runtimes():
            if runtime.config.agent_id == agent_id:
                return runtime
        return None

    def _agent_by_telegram_id(self, telegram_id: int) -> MimicAgentRuntime | None:
        for runtime in self._runtimes():
            if runtime.telegram_user_id == telegram_id:
                return runtime
        return None

    # ── Обход агентов ─────────────────────────────────────────────────────────

    async def tick(self) -> None:
        online = [r for r in self._runtimes() if self._is_reachable(r)]
        for runtime in online:
            try:
                if runtime.warmup_restricted_at is not None:
                    # Пользователь выбрал судьбу ограниченного аккаунта сам, поэтому
                    # режим восстановления не зависит от переключателя обычного прогрева.
                    await self._tend_restricted(runtime, online)
                elif runtime.config.warmup.enabled:
                    await self._maybe_start_dialog(runtime, online)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Warmup failed for agent %s", runtime.config.agent_id)

    @staticmethod
    def _is_reachable(runtime: MimicAgentRuntime) -> bool:
        """Запущен и известен по @username: ему можно написать и от него можно ждать ответа."""
        return (
            runtime.state is AgentRuntimeState.RUNNING
            and runtime.telegram_user_id is not None
            and bool(runtime.telegram_username)
        )

    def _day_start(self, runtime: MimicAgentRuntime) -> tuple[datetime, datetime, ZoneInfo]:
        now = self._now()
        zone = ZoneInfo(runtime.config.warmup.timezone)
        today = now.astimezone(zone).date()
        return now, datetime.combine(today, time(0), tzinfo=zone).astimezone(UTC), zone

    async def _attempt_times(
        self, kind: AttemptKind, agent_id: UUID, since: datetime
    ) -> list[datetime]:
        """Попытки из журнала плюс резервы текущего процесса."""
        if kind == "sent":
            stored = await self._history.attempt_times_since(agent_id, since)
        else:
            stored = await self._history.received_times_since(agent_id, since)
        reserved = [m for m in self._reserved.get((kind, agent_id), []) if m >= since]
        return merge_attempts(stored, reserved)

    def _reserve(self, kind: AttemptKind, agent_id: UUID, moment: datetime) -> None:
        kept = [
            m
            for m in self._reserved.get((kind, agent_id), [])
            if (moment - m).total_seconds() < RESERVATION_KEEP_SECONDS
        ]
        kept.append(moment)
        self._reserved[(kind, agent_id)] = kept

    async def _sender_may_open(self, runtime: MimicAgentRuntime) -> bool:
        """Бюджет исходящих зачинов отправителя: один на обычный прогрев и на помощь другим."""
        now, day_start, _ = self._day_start(runtime)
        attempts = await self._attempt_times("sent", runtime.config.agent_id, day_start)
        return sender_may_open(attempts, now=now)

    async def _maybe_start_dialog(
        self, runtime: MimicAgentRuntime, participants: list[MimicAgentRuntime]
    ) -> None:
        agent_id = runtime.config.agent_id
        now, day_start, zone = self._day_start(runtime)
        slots = daily_slots(agent_id, day_start.astimezone(zone).date(), zone.key)
        attempts = await self._attempt_times("sent", agent_id, day_start)
        if due_slot(slots, now=now, attempts=attempts) is None:
            return
        await self.start_dialog(runtime, participants)

    async def start_dialog(
        self,
        runtime: MimicAgentRuntime,
        participants: list[MimicAgentRuntime],
        *,
        target: MimicAgentRuntime | None = None,
        recovery: bool = False,
    ) -> bool:
        """Начать диалог сейчас, не глядя на расписание. True — зачин ушёл.

        ``target`` задан в режиме восстановления: собеседник известен заранее. Бюджет
        отправителя проверяется всегда: исчерпанный бюджет ничего не расходует.
        """
        agent_id = runtime.config.agent_id
        now = self._now()
        if not await self._sender_may_open(runtime):
            return False
        if target is None:
            candidates = [
                other
                for other in participants
                if other.config.agent_id != agent_id
                and other.config.warmup.enabled
                and other.warmup_restricted_at is None
                and self._pair_policy(runtime, other)
                and not self._tracker.is_active(agent_id, other.config.agent_id, now=now)
            ]
            by_id = {other.config.agent_id: other for other in candidates}
            recent = await self._history.recent_partners(agent_id)
            partner_id = pick_partner(list(by_id), recent, self._rng)
            if partner_id is None:
                return False
            partner = by_id[partner_id]
        else:
            partner = target
            partner_id = target.config.agent_id
        username = partner.telegram_username
        user_id = partner.telegram_user_id
        if username is None or user_id is None:
            return False

        text = pick_opener(await self._history.used_openers(agent_id), self._rng)
        length = dialog_length(self._rng, recovery=recovery)
        # Диалог и попытка резервируются до отправки: ответ может прийти раньше, чем
        # отправка вернётся, а запись в журнал может не дойти (отмена, сбой базы).
        self._tracker.start(agent_id, partner_id, length=length, now=now)
        self._reserve("sent", agent_id, now)
        self._reserve("received", partner_id, now)
        result = await runtime.send_warmup_opener(
            username=username,
            user_id=user_id,
            partner_agent_id=partner_id,
            partner_name=partner.config.name,
            text=text,
            dialog_length=length,
        )
        if result is not OpenerResult.SENT:
            self._tracker.drop(agent_id, partner_id)
        if result is OpenerResult.RESTRICTED:
            await self._mark_restricted(runtime)
        return result is OpenerResult.SENT

    # ── Ограниченные аккаунты ─────────────────────────────────────────────────

    async def _record_transition(self, runtime: MimicAgentRuntime, event_type: str) -> None:
        if self._state_store is None:
            return
        try:
            await self._state_store.record(runtime.config.agent_id, event_type)
        except Exception:
            logger.exception("Failed to record %s for %s", event_type, runtime.config.agent_id)

    async def _mark_restricted(self, runtime: MimicAgentRuntime) -> None:
        """Аккаунт ограничен: сам диалогов не начинает, пока пользователь не выберет."""
        if runtime.warmup_restricted_at is not None:
            return
        runtime.warmup_restricted_at = self._now()
        runtime.warmup_recovery = False
        await self._record_transition(runtime, EVENT_RESTRICTED)
        # Сразу проверим, а не через шесть часов: статус и дата в ответе бота уточняют картину.
        self._last_spambot_check.pop(runtime.config.agent_id, None)

    async def start_recovery(self, agent_id: UUID) -> bool:
        """Пользователь выбрал восстановление. False — агент не ограничен или не найден."""
        runtime = self._agent_by_id(agent_id)
        if runtime is None or runtime.warmup_restricted_at is None:
            return False
        if not runtime.warmup_recovery:
            runtime.warmup_recovery = True
            await self._record_transition(runtime, EVENT_RECOVERY_STARTED)
        return True

    async def _tend_restricted(
        self, runtime: MimicAgentRuntime, participants: list[MimicAgentRuntime]
    ) -> None:
        if await self._release_if_free(runtime):
            return
        if runtime.warmup_recovery:
            await self._maybe_start_recovery_dialog(runtime, participants)

    async def _release_if_free(self, runtime: MimicAgentRuntime) -> bool:
        """Спросить @SpamBot (не чаще раза в SPAMBOT_CHECK_INTERVAL); True — ограничение снято."""
        agent_id = runtime.config.agent_id
        now = self._now()
        last = self._last_spambot_check.get(agent_id)
        if last is not None and now - last < SPAMBOT_CHECK_INTERVAL:
            return False
        self._last_spambot_check[agent_id] = now
        free = await runtime.check_spambot()
        if free is not True:
            return False
        runtime.warmup_restricted_at = None
        runtime.warmup_recovery = False
        await self._record_transition(runtime, EVENT_RECOVERED)
        logger.info("Warmup: restriction lifted for agent %s", agent_id)
        return True

    async def _maybe_start_recovery_dialog(
        self, runtime: MimicAgentRuntime, participants: list[MimicAgentRuntime]
    ) -> None:
        """Восстановление: подходящий агент пишет ограниченному по его усиленному расписанию."""
        agent_id = runtime.config.agent_id
        now, day_start, zone = self._day_start(runtime)
        slots = daily_slots(agent_id, day_start.astimezone(zone).date(), zone.key, recovery=True)
        received = await self._attempt_times("received", agent_id, day_start)
        if due_slot(slots, now=now, attempts=received) is None:
            return
        helpers = [
            other
            for other in participants
            if other.config.agent_id != agent_id
            and other.config.warmup.enabled
            and other.warmup_restricted_at is None
            and self._pair_policy(other, runtime)
            and not self._tracker.is_active(agent_id, other.config.agent_id, now=now)
            and await self._sender_may_open(other)
        ]
        if not helpers:
            return
        helper = self._rng.choice(helpers)
        await self.start_dialog(helper, participants, target=runtime, recovery=True)
