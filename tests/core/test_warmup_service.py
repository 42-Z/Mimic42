from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from mimic42.core.agent_runtime import AgentRuntimeState, MimicAgentRuntime, OpenerResult
from mimic42.core.warmup import (
    EVENT_RECOVERED,
    EVENT_RECOVERY_STARTED,
    EVENT_RESTRICTED,
    MAX_OPENERS_PER_DAY,
    SPAMBOT_CHECK_INTERVAL,
    DialogTracker,
    WarmupSettings,
    daily_slots,
)
from mimic42.core.warmup_service import (
    WarmupService,
    pair_policy_for,
    same_owner_only,
)


class StubRuntime:
    def __init__(
        self,
        *,
        user_id: int,
        username: str | None = None,
        enabled: bool = True,
        state: AgentRuntimeState = AgentRuntimeState.RUNNING,
        result: OpenerResult = OpenerResult.SENT,
        owner_id: UUID | None = None,
        restricted: bool = False,
        recovery: bool = False,
        spambot: bool | None = None,
    ) -> None:
        self.config = SimpleNamespace(
            agent_id=uuid4(),
            owner_id=owner_id or uuid4(),
            name=f"agent-{user_id}",
            warmup=WarmupSettings(enabled=enabled),
        )
        self.state = state
        self.telegram_user_id: int | None = user_id
        self.telegram_username: str | None = username if username is not None else f"user{user_id}"
        self.result = result
        self.openers: list[dict[str, Any]] = []
        self.warmup_restricted_at: datetime | None = (
            datetime(2026, 10, 1, tzinfo=UTC) if restricted else None
        )
        self.warmup_recovery = recovery
        self.spambot = spambot
        self.spambot_checks = 0

    async def send_warmup_opener(self, **kwargs: Any) -> OpenerResult:
        self.openers.append(kwargs)
        return self.result

    async def check_spambot(self) -> bool | None:
        self.spambot_checks += 1
        return self.spambot


class MemoryHistory:
    def __init__(self) -> None:
        self.attempts: list[datetime] = []
        self.received: list[datetime] = []
        self.openers: list[str] = []
        self.partners: list[UUID] = []

    async def attempt_times_since(self, agent_id: UUID, since: datetime) -> list[datetime]:
        return [t for t in self.attempts if t >= since]

    async def received_times_since(self, agent_id: UUID, since: datetime) -> list[datetime]:
        return [t for t in self.received if t >= since]

    async def used_openers(self, agent_id: UUID) -> list[str]:
        return self.openers

    async def recent_partners(self, agent_id: UUID) -> list[UUID]:
        return self.partners


class MemoryStateStore:
    def __init__(self) -> None:
        self.events: list[tuple[UUID, str]] = []

    async def record(
        self, agent_id: UUID, event_type: str, payload: dict[str, Any] | None = None
    ) -> None:
        self.events.append((agent_id, event_type))


def make_service(
    runtimes: list[StubRuntime],
    history: MemoryHistory,
    now: datetime,
    *,
    store: MemoryStateStore | None = None,
    policy: Any = None,
) -> tuple[WarmupService, DialogTracker]:
    tracker = DialogTracker()
    kwargs: dict[str, Any] = {"pair_policy": policy} if policy is not None else {}
    service = WarmupService(
        lambda: cast("list[MimicAgentRuntime]", runtimes),
        history,
        state_store=store,
        tracker=tracker,
        now=lambda: now,
        rng=random.Random(1),
        **kwargs,
    )
    return service, tracker


def _today() -> Any:
    return datetime(2026, 10, 2, 12, 0, tzinfo=UTC).astimezone(ZoneInfo("Europe/Moscow")).date()


def due_moment(runtime: StubRuntime, *, recovery: bool = False) -> datetime:
    """Момент сразу после первого слота агента на «сегодня»."""
    slots = daily_slots(runtime.config.agent_id, _today(), recovery=recovery)
    return slots[0] + timedelta(minutes=5)


@pytest.mark.asyncio
async def test_agent_starts_dialog_with_another_mimic_at_its_slot() -> None:
    a, b = StubRuntime(user_id=1), StubRuntime(user_id=2)
    history = MemoryHistory()
    service, tracker = make_service([a, b], history, due_moment(a))

    await service.tick()

    assert len(a.openers) == 1
    opener = a.openers[0]
    assert opener["username"] == "user2"
    assert opener["user_id"] == 2
    assert opener["partner_agent_id"] == b.config.agent_id
    assert opener["text"]
    assert tracker.is_active(a.config.agent_id, b.config.agent_id, now=due_moment(a))


@pytest.mark.asyncio
async def test_nothing_happens_before_slot_or_after_quota_is_used() -> None:
    a, b = StubRuntime(user_id=1), StubRuntime(user_id=2)
    history = MemoryHistory()
    before_slot = due_moment(a) - timedelta(hours=1, minutes=10)
    service, _ = make_service([a, b], history, before_slot)
    await service.tick()
    assert a.openers == []

    # У b слот мог выпасть на то же время: второй проход проверяем с чистого листа.
    a.openers.clear()
    b.openers.clear()
    history.attempts = [due_moment(a) - timedelta(minutes=1)] * 3
    service, _ = make_service([a, b], history, due_moment(a))
    await service.tick()
    assert a.openers == [] and b.openers == []


@pytest.mark.asyncio
async def test_agents_without_warmup_are_not_partners_and_do_not_start_dialogs() -> None:
    a = StubRuntime(user_id=1)
    off = StubRuntime(user_id=2, enabled=False)
    stopped = StubRuntime(user_id=3, state=AgentRuntimeState.STOPPED)
    nameless = StubRuntime(user_id=4)
    nameless.telegram_username = None
    service, _ = make_service([a, off, stopped, nameless], MemoryHistory(), due_moment(a))

    await service.tick()

    # Писать некому: ни один из остальных не может быть собеседником.
    assert a.openers == []
    # Агент с выключенным прогревом сам диалогов не начинает.
    assert off.openers == []


@pytest.mark.asyncio
async def test_failed_opener_does_not_leave_dialog_open() -> None:
    # У b свой слот тоже может выпасть на это время, поэтому у него отправка тоже падает.
    a = StubRuntime(user_id=1, result=OpenerResult.FAILED)
    b = StubRuntime(user_id=2, result=OpenerResult.FAILED)
    service, tracker = make_service([a, b], MemoryHistory(), due_moment(a))

    await service.tick()

    assert len(a.openers) == 1
    assert not tracker.is_active(a.config.agent_id, b.config.agent_id, now=due_moment(a))


@pytest.mark.asyncio
async def test_opener_avoids_texts_already_used() -> None:
    a, b = StubRuntime(user_id=1), StubRuntime(user_id=2)
    history = MemoryHistory()
    service, _ = make_service([a, b], history, due_moment(a))
    await service.tick()
    first = a.openers[0]["text"]

    history.openers = [first]
    service, _ = make_service([a, b], history, due_moment(a))
    await service.tick()

    assert a.openers[1]["text"] != first


@pytest.mark.asyncio
async def test_gate_tells_mimics_from_strangers_and_limits_dialog() -> None:
    a, b = StubRuntime(user_id=1), StubRuntime(user_id=2)
    service, tracker = make_service([a, b], MemoryHistory(), due_moment(a))
    now = due_moment(a)

    assert service.claim_reply(a.config.agent_id, 12345) is None  # обычный человек
    assert service.claim_reply(b.config.agent_id, 1) is False  # диалог не начат

    tracker.start(a.config.agent_id, b.config.agent_id, length=3, now=now)
    assert service.claim_reply(b.config.agent_id, 1) is True
    assert service.claim_reply(a.config.agent_id, 2) is True
    assert service.claim_reply(b.config.agent_id, 1) is False


@pytest.mark.asyncio
async def test_service_hands_runtimes_the_reply_delay() -> None:
    a = StubRuntime(user_id=1)
    service = WarmupService(
        lambda: cast("list[MimicAgentRuntime]", [a]),
        MemoryHistory(),
        delay=lambda: 42.0,
    )
    assert service.reply_delay_seconds() == 42.0
    default = WarmupService(lambda: [], MemoryHistory(), rng=random.Random(1))
    assert 15 <= default.reply_delay_seconds() <= 50 * 60


@pytest.mark.asyncio
async def test_own_only_policy_keeps_dialogs_inside_one_owner() -> None:
    owner = uuid4()
    mine = StubRuntime(user_id=1, owner_id=owner)
    stranger = StubRuntime(user_id=2)
    service, _ = make_service(
        [mine, stranger], MemoryHistory(), due_moment(mine), policy=same_owner_only
    )
    await service.tick()
    assert mine.openers == []

    colleague = StubRuntime(user_id=3, owner_id=owner)
    service, _ = make_service(
        [mine, stranger, colleague], MemoryHistory(), due_moment(mine), policy=same_owner_only
    )
    await service.tick()
    assert [o["partner_agent_id"] for o in mine.openers] == [colleague.config.agent_id]


def test_pair_policy_follows_the_setting() -> None:
    a, b = StubRuntime(user_id=1), StubRuntime(user_id=2)
    pair = cast("tuple[MimicAgentRuntime, MimicAgentRuntime]", (a, b))
    assert pair_policy_for("all")(*pair) is True
    assert pair_policy_for("own")(*pair) is False
    assert pair_policy_for("что-то странное")(*pair) is True


# ── Режим восстановления ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_peer_flood_marks_agent_restricted_and_saves_it() -> None:
    a = StubRuntime(user_id=1, result=OpenerResult.RESTRICTED)
    b = StubRuntime(user_id=2, result=OpenerResult.RESTRICTED)
    store = MemoryStateStore()
    service, tracker = make_service([a, b], MemoryHistory(), due_moment(a), store=store)

    await service.tick()

    assert a.warmup_restricted_at is not None
    assert a.warmup_recovery is False
    assert (a.config.agent_id, EVENT_RESTRICTED) in store.events
    assert not tracker.is_active(a.config.agent_id, b.config.agent_id, now=due_moment(a))


@pytest.mark.asyncio
async def test_restricted_agent_waits_for_the_users_choice() -> None:
    limited = StubRuntime(user_id=1, restricted=True, recovery=False)
    helper = StubRuntime(user_id=2)
    history = MemoryHistory()
    service, _ = make_service([limited, helper], history, due_moment(limited, recovery=True))

    await service.tick()

    assert limited.openers == []  # сам диалогов не начинает
    assert [o for o in helper.openers if o["partner_agent_id"] == limited.config.agent_id] == []


@pytest.mark.asyncio
async def test_recovery_makes_a_healthy_agent_write_to_the_limited_one() -> None:
    limited = StubRuntime(user_id=1, restricted=True, recovery=True)
    helper = StubRuntime(user_id=2)
    helper.config.warmup = WarmupSettings(enabled=True)
    service, tracker = make_service(
        [limited, helper], MemoryHistory(), due_moment(limited, recovery=True)
    )

    await service.tick()

    sent = [o for o in helper.openers if o["partner_agent_id"] == limited.config.agent_id]
    assert len(sent) == 1
    assert sent[0]["dialog_length"] >= 7  # диалоги восстановления длиннее обычных
    assert limited.openers == []
    assert tracker.is_active(
        limited.config.agent_id, helper.config.agent_id, now=due_moment(limited, recovery=True)
    )


@pytest.mark.asyncio
async def test_recovery_ignores_restricted_helpers_and_used_quota() -> None:
    limited = StubRuntime(user_id=1, restricted=True, recovery=True)
    also_limited = StubRuntime(user_id=2, restricted=True, recovery=True)
    service, _ = make_service(
        [limited, also_limited], MemoryHistory(), due_moment(limited, recovery=True)
    )
    await service.tick()
    assert limited.openers == [] and also_limited.openers == []

    helper = StubRuntime(user_id=3)
    history = MemoryHistory()
    history.received = [due_moment(limited, recovery=True) - timedelta(minutes=1)] * 99
    service, _ = make_service([limited, helper], history, due_moment(limited, recovery=True))
    await service.tick()
    assert [o for o in helper.openers if o["partner_agent_id"] == limited.config.agent_id] == []


@pytest.mark.asyncio
async def test_spambot_all_clear_lifts_restriction_and_resumes_warmup() -> None:
    limited = StubRuntime(user_id=1, restricted=True, recovery=True, spambot=True)
    store = MemoryStateStore()
    service, _ = make_service([limited], MemoryHistory(), due_moment(limited), store=store)

    await service.tick()

    assert limited.warmup_restricted_at is None
    assert limited.warmup_recovery is False
    assert store.events[-1] == (limited.config.agent_id, EVENT_RECOVERED)


@pytest.mark.asyncio
async def test_spambot_is_asked_rarely_and_unknown_answer_changes_nothing() -> None:
    limited = StubRuntime(user_id=1, restricted=True, recovery=True, spambot=None)
    start = due_moment(limited)
    service, _ = make_service([limited], MemoryHistory(), start)
    await service.tick()
    await service.tick()
    assert limited.spambot_checks == 1
    assert limited.warmup_restricted_at is not None

    later = start + SPAMBOT_CHECK_INTERVAL + timedelta(minutes=1)
    service._now = lambda: later  # noqa: SLF001
    await service.tick()
    assert limited.spambot_checks == 2


@pytest.mark.asyncio
async def test_messages_between_mimics_are_left_alone_when_warmup_is_off() -> None:
    a, b = StubRuntime(user_id=1), StubRuntime(user_id=2, enabled=False)
    service, tracker = make_service([a, b], MemoryHistory(), due_moment(a))

    # Диалога нет, но у b прогрев выключен: обычная переписка, никаких ограничений.
    assert service.claim_reply(b.config.agent_id, 1) is None
    assert service.claim_reply(a.config.agent_id, 2) is None

    b.config.warmup = WarmupSettings(enabled=True)
    assert service.claim_reply(b.config.agent_id, 1) is False
    tracker.start(a.config.agent_id, b.config.agent_id, length=4, now=due_moment(a))
    assert service.claim_reply(b.config.agent_id, 1) is True


def _agent_with_slots(count: int, *, recovery: bool = False) -> StubRuntime:
    while True:
        runtime = StubRuntime(user_id=1)
        if len(daily_slots(runtime.config.agent_id, _today(), recovery=recovery)) >= count:
            return runtime


@pytest.mark.asyncio
async def test_late_slot_is_used_once_even_if_the_early_one_was_skipped() -> None:
    a = _agent_with_slots(2)
    b = StubRuntime(user_id=2)
    slots = daily_slots(a.config.agent_id, _today())
    now = slots[1] + timedelta(minutes=5)
    history = MemoryHistory()
    service, _ = make_service([a, b], history, now)

    await service.tick()
    assert len(a.openers) == 1

    # Журнал ещё ничего не знает (запись не дошла), но резерв процесса помнит попытку.
    service._now = lambda: now + timedelta(minutes=1)  # noqa: SLF001
    await service.tick()
    assert len(a.openers) == 1

    # И когда запись дошла, слот тоже считается занятым.
    history.attempts = [now + timedelta(seconds=30)]
    service._now = lambda: now + timedelta(minutes=2)  # noqa: SLF001
    await service.tick()
    assert len(a.openers) == 1


@pytest.mark.asyncio
async def test_late_recovery_slot_is_used_once_even_if_early_ones_were_skipped() -> None:
    limited = _agent_with_slots(3, recovery=True)
    limited.warmup_restricted_at = datetime(2026, 10, 1, tzinfo=UTC)
    limited.warmup_recovery = True
    helper = StubRuntime(user_id=2)
    slots = daily_slots(limited.config.agent_id, _today(), recovery=True)
    now = slots[2] + timedelta(minutes=5)
    service, _ = make_service([limited, helper], MemoryHistory(), now)

    await service.tick()
    assert len(helper.openers) == 1

    # Отправитель отдыхал бы и без этого, поэтому интервал берём заведомо большим.
    service._now = lambda: now + timedelta(minutes=45)  # noqa: SLF001
    await service.tick()
    assert len(helper.openers) == 1


@pytest.mark.asyncio
async def test_helper_without_budget_is_not_used_and_does_not_burn_the_recipients_slot() -> None:
    limited = StubRuntime(user_id=1, restricted=True, recovery=True)
    helper = StubRuntime(user_id=2)
    now = due_moment(limited, recovery=True)
    history = MemoryHistory()
    history.attempts = [now - timedelta(minutes=10)]
    service, _ = make_service([limited, helper], history, now)

    await service.tick()
    assert helper.openers == []
    assert limited.warmup_restricted_at is not None

    # Пауза прошла, слот получателя на месте: помощник пишет.
    history.attempts = [now - timedelta(hours=1)]
    service, _ = make_service([limited, helper], history, now)
    await service.tick()
    assert len(helper.openers) == 1


@pytest.mark.asyncio
async def test_helper_that_spent_the_daily_budget_stays_silent() -> None:
    limited = StubRuntime(user_id=1, restricted=True, recovery=True)
    helper = StubRuntime(user_id=2)
    now = due_moment(limited, recovery=True)
    history = MemoryHistory()
    history.attempts = [now - timedelta(hours=1 + i) for i in range(MAX_OPENERS_PER_DAY)]
    service, _ = make_service([limited, helper], history, now)

    await service.tick()

    assert helper.openers == []


@pytest.mark.asyncio
async def test_one_helper_does_not_write_to_every_limited_account_in_one_tick() -> None:
    first = StubRuntime(user_id=1, restricted=True, recovery=True)
    second = StubRuntime(user_id=2, restricted=True, recovery=True)
    helper = StubRuntime(user_id=3)
    now = max(due_moment(first, recovery=True), due_moment(second, recovery=True))
    service, _ = make_service([first, second, helper], MemoryHistory(), now)

    await service.tick()

    assert len(helper.openers) <= 1


@pytest.mark.asyncio
async def test_peer_flood_from_any_send_restricts_the_agent_once() -> None:
    a = StubRuntime(user_id=1)
    store = MemoryStateStore()
    service, _ = make_service([a], MemoryHistory(), due_moment(a), store=store)

    await service.report_peer_flood(a.config.agent_id)
    await service.report_peer_flood(a.config.agent_id)
    await service.report_peer_flood(uuid4())

    assert a.warmup_restricted_at is not None
    assert store.events == [(a.config.agent_id, EVENT_RESTRICTED)]


@pytest.mark.asyncio
async def test_recovery_can_only_be_started_for_a_restricted_agent_and_only_once() -> None:
    healthy = StubRuntime(user_id=1)
    limited = StubRuntime(user_id=2, restricted=True)
    store = MemoryStateStore()
    service, _ = make_service([healthy, limited], MemoryHistory(), due_moment(healthy), store=store)

    assert await service.start_recovery(healthy.config.agent_id) is False
    assert await service.start_recovery(uuid4()) is False
    assert await service.start_recovery(limited.config.agent_id) is True
    assert await service.start_recovery(limited.config.agent_id) is True

    assert limited.warmup_recovery is True
    assert store.events == [(limited.config.agent_id, EVENT_RECOVERY_STARTED)]


@pytest.mark.asyncio
async def test_recovery_runs_even_if_the_ordinary_warmup_switch_is_off() -> None:
    limited = StubRuntime(user_id=1, enabled=False, restricted=True, recovery=True)
    helper = StubRuntime(user_id=2)
    service, _ = make_service(
        [limited, helper], MemoryHistory(), due_moment(limited, recovery=True)
    )

    await service.tick()

    assert [o["partner_agent_id"] for o in helper.openers] == [limited.config.agent_id]


@pytest.mark.asyncio
async def test_delayed_reply_is_confirmed_only_while_the_warmup_dialog_stands() -> None:
    a, b = StubRuntime(user_id=1), StubRuntime(user_id=2)
    service, tracker = make_service([a, b], MemoryHistory(), due_moment(a))
    now = due_moment(a)

    assert service.confirm_reply(b.config.agent_id, 1) is False  # диалога нет
    tracker.start(a.config.agent_id, b.config.agent_id, length=6, now=now)
    assert service.claim_reply(b.config.agent_id, 1) is True
    assert service.confirm_reply(b.config.agent_id, 1) is True

    a.config.warmup = WarmupSettings(enabled=False)  # пока b «был занят», прогрев у a выключили
    assert service.confirm_reply(b.config.agent_id, 1) is False
    assert service.confirm_reply(b.config.agent_id, 99999) is False  # не мимик


@pytest.mark.asyncio
async def test_confirming_a_reply_does_not_spend_the_dialog_quota() -> None:
    a, b = StubRuntime(user_id=1), StubRuntime(user_id=2)
    service, tracker = make_service([a, b], MemoryHistory(), due_moment(a))
    tracker.start(a.config.agent_id, b.config.agent_id, length=3, now=due_moment(a))

    assert service.claim_reply(b.config.agent_id, 1) is True
    for _ in range(5):
        assert service.confirm_reply(b.config.agent_id, 1) is True
    assert service.claim_reply(a.config.agent_id, 2) is True
    assert service.claim_reply(b.config.agent_id, 1) is False
