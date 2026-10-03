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
        self.events: list[str] = []

    async def send_warmup_opener(self, **kwargs: Any) -> OpenerResult:
        self.openers.append(kwargs)
        return self.result

    async def check_spambot(self) -> bool | None:
        self.spambot_checks += 1
        return self.spambot

    async def note_warmup_event(self, event_type: str, **_: Any) -> None:
        self.events.append(event_type)


class MemoryHistory:
    def __init__(self) -> None:
        self.attempts = 0
        self.received = 0
        self.openers: list[str] = []
        self.partners: list[UUID] = []

    async def attempts_since(self, agent_id: UUID, since: datetime) -> int:
        return self.attempts

    async def received_since(self, agent_id: UUID, since: datetime) -> int:
        return self.received

    async def used_openers(self, agent_id: UUID) -> list[str]:
        return self.openers

    async def recent_partners(self, agent_id: UUID) -> list[UUID]:
        return self.partners


class MemoryStateStore:
    def __init__(self) -> None:
        self.saved: list[tuple[UUID, datetime | None, bool]] = []

    async def save_state(
        self, agent_id: UUID, *, restricted_at: datetime | None, recovery: bool
    ) -> None:
        self.saved.append((agent_id, restricted_at, recovery))


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
    history.attempts = 3
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
    assert any(saved[0] == a.config.agent_id and saved[1] is not None for saved in store.saved)
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
    history.received = 99
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
    assert limited.events == [EVENT_RECOVERED]
    assert store.saved[-1] == (limited.config.agent_id, None, False)


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
