"""Сервис прогрева: раз в минуту решает, кому из мимиков пора начать диалог.

Живёт рядом с менеджером агентов и видит все его запущенные рантаймы. Что именно
написать и когда — решает ``core.warmup``; здесь только обход агентов, подбор пары,
отправка и режим восстановления ограниченных аккаунтов.

Режим восстановления. Аккаунт, которому Telegram запретил писать незнакомым
(PeerFloodError), сам диалогов не начинает: до ответа пользователя («восстановить»
или «удалить») он ничего не делает. Если выбрано восстановление, другие агенты
сами пишут ему чаще и дольше обычного, а он отвечает — Telegram прямо разрешает
ограниченному аккаунту отвечать тем, кто написал первым. Раз в несколько часов
@SpamBot спрашивают, снято ли ограничение. Насколько это ускоряет снятие, неизвестно:
Telegram досрочного снятия не обещает.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, time
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from mimic42.core.agent_runtime import AgentRuntimeState, MimicAgentRuntime, OpenerResult
from mimic42.core.warmup import (
    EVENT_RECOVERED,
    SPAMBOT_CHECK_INTERVAL,
    DialogTracker,
    daily_slots,
    dialog_length,
    due_slot,
    pick_opener,
    pick_partner,
    reply_delay,
)

logger = logging.getLogger("mimic42.warmup")

TICK_SECONDS = 60.0

PairPolicy = Callable[[MimicAgentRuntime, MimicAgentRuntime], bool]


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

    async def attempts_since(self, agent_id: UUID, since: datetime) -> int:
        """Сколько диалогов агент начал с ``since`` (включая неудавшиеся)."""
        ...

    async def received_since(self, agent_id: UUID, since: datetime) -> int:
        """Сколько диалогов другие агенты начали с этим агентом с ``since``."""
        ...

    async def used_openers(self, agent_id: UUID) -> list[str]:
        """Отправленные зачины, от старых к новым."""
        ...

    async def recent_partners(self, agent_id: UUID) -> list[UUID]:
        """С кем агент начинал диалоги, от старых к новым."""
        ...


class WarmupStateStore(Protocol):
    """Сохранение состояния ограничения в настройках агента."""

    async def save_state(
        self, agent_id: UUID, *, restricted_at: datetime | None, recovery: bool
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
        sender = self._agent_by_telegram_id(sender_telegram_id)
        if sender is None:
            return None
        receiver = self._agent_by_id(receiver_id)
        # Прогрев выключен хоть у одного: это обычная переписка, и ограничивать её нельзя.
        if receiver is None or not (
            receiver.config.warmup.enabled and sender.config.warmup.enabled
        ):
            return None
        return self._tracker.claim_reply(receiver_id, sender.config.agent_id, now=self._now())

    def reply_delay_seconds(self) -> float:
        return self._delay()

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
            if not runtime.config.warmup.enabled:
                continue
            try:
                if runtime.warmup_restricted_at is not None:
                    await self._tend_restricted(runtime, online)
                else:
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

    def _day_bounds(self, runtime: MimicAgentRuntime) -> tuple[datetime, datetime]:
        now = self._now()
        zone = ZoneInfo(runtime.config.warmup.timezone)
        today = now.astimezone(zone).date()
        return now, datetime.combine(today, time(0), tzinfo=zone).astimezone(UTC)

    async def _maybe_start_dialog(
        self, runtime: MimicAgentRuntime, participants: list[MimicAgentRuntime]
    ) -> None:
        agent_id = runtime.config.agent_id
        now, day_start = self._day_bounds(runtime)
        today = day_start.astimezone(ZoneInfo(runtime.config.warmup.timezone)).date()
        slots = daily_slots(agent_id, today, runtime.config.warmup.timezone)
        done = await self._history.attempts_since(agent_id, day_start)
        if due_slot(slots, now=now, done_today=done) is None:
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

        ``target`` задан в режиме восстановления: собеседник известен заранее.
        """
        agent_id = runtime.config.agent_id
        now = self._now()
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
        # Диалог открывается до отправки: ответ может прийти раньше, чем отправка вернётся.
        self._tracker.start(agent_id, partner_id, length=length, now=now)
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

    async def _mark_restricted(self, runtime: MimicAgentRuntime) -> None:
        """Аккаунт ограничен: сам диалогов не начинает, пока пользователь не выберет."""
        runtime.warmup_restricted_at = self._now()
        runtime.warmup_recovery = False
        await self._persist(runtime)
        # Сразу проверим, а не через шесть часов: статус и дата в ответе бота уточняют картину.
        self._last_spambot_check.pop(runtime.config.agent_id, None)

    async def _persist(self, runtime: MimicAgentRuntime) -> None:
        if self._state_store is None:
            return
        try:
            await self._state_store.save_state(
                runtime.config.agent_id,
                restricted_at=runtime.warmup_restricted_at,
                recovery=runtime.warmup_recovery,
            )
        except Exception:
            logger.exception("Failed to save warmup state of %s", runtime.config.agent_id)

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
        await self._persist(runtime)
        await runtime.note_warmup_event(EVENT_RECOVERED)
        logger.info("Warmup: restriction lifted for agent %s", agent_id)
        return True

    async def _maybe_start_recovery_dialog(
        self, runtime: MimicAgentRuntime, participants: list[MimicAgentRuntime]
    ) -> None:
        """Восстановление: подходящий агент пишет ограниченному по его усиленному расписанию."""
        agent_id = runtime.config.agent_id
        now, day_start = self._day_bounds(runtime)
        zone = ZoneInfo(runtime.config.warmup.timezone)
        slots = daily_slots(agent_id, day_start.astimezone(zone).date(), zone.key, recovery=True)
        done = await self._history.received_since(agent_id, day_start)
        if due_slot(slots, now=now, done_today=done) is None:
            return
        helpers = [
            other
            for other in participants
            if other.config.agent_id != agent_id
            and other.config.warmup.enabled
            and other.warmup_restricted_at is None
            and self._pair_policy(other, runtime)
            and not self._tracker.is_active(agent_id, other.config.agent_id, now=now)
        ]
        if not helpers:
            return
        helper = self._rng.choice(helpers)
        await self.start_dialog(helper, participants, target=runtime, recovery=True)
