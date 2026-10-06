from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from mimic42.core.warmup import (
    ACTIVE_FROM_HOUR,
    ACTIVE_TO_HOUR,
    DEFAULT_TIMEZONE,
    DIALOG_IDLE_TIMEOUT,
    DIALOG_LENGTH_RANGE,
    MAX_OPENERS_PER_DAY,
    MIN_OPENER_INTERVAL,
    MIN_SLOT_GAP,
    DialogTracker,
    WarmupSettings,
    classify_spambot_reply,
    daily_slots,
    dialog_length,
    due_slot,
    merge_attempts,
    parse_warmup,
    pick_opener,
    pick_partner,
    reply_delay,
    sender_may_open,
)
from mimic42.core.warmup_messages import OPENERS

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def test_daily_slots_are_deterministic_and_in_waking_hours() -> None:
    agent_id = uuid4()
    for offset in range(60):
        day = date(2026, 10, 1) + timedelta(days=offset)
        slots = daily_slots(agent_id, day)
        assert slots == daily_slots(agent_id, day)
        assert 1 <= len(slots) <= 3
        for slot in slots:
            local = slot.astimezone(MSK)
            assert local.date() == day
            assert ACTIVE_FROM_HOUR <= local.hour < ACTIVE_TO_HOUR
        for earlier, later in zip(slots, slots[1:], strict=False):
            assert later - earlier >= MIN_SLOT_GAP


def test_daily_slots_differ_between_agents_and_days() -> None:
    day = date(2026, 10, 2)
    assert daily_slots(uuid4(), day) != daily_slots(uuid4(), day)
    agent_id = uuid4()
    assert daily_slots(agent_id, day) != daily_slots(agent_id, day + timedelta(days=1))


def test_due_slot_waits_then_fires_once_and_skips_stale() -> None:
    slots = [NOW + timedelta(hours=1), NOW + timedelta(hours=4)]
    first_done = [NOW + timedelta(hours=1, minutes=1)]
    assert due_slot(slots, now=NOW, attempts=[]) is None
    assert due_slot(slots, now=NOW + timedelta(hours=1, minutes=5), attempts=[]) == slots[0]
    assert due_slot(slots, now=NOW + timedelta(hours=1, minutes=5), attempts=first_done) is None
    # Сервер был выключен: слот просрочен больше чем на час — пропускаем.
    assert due_slot(slots, now=NOW + timedelta(hours=3), attempts=[]) is None
    both_done = [*first_done, NOW + timedelta(hours=4, minutes=1)]
    assert due_slot(slots, now=NOW + timedelta(hours=4), attempts=both_done) is None


def test_skipped_early_slot_does_not_make_the_late_slot_fire_twice() -> None:
    """Ранний слот пропущен, поздний отработан: следующий тик ничего не отправляет."""
    early, late = NOW, NOW + timedelta(hours=3)
    slots = [early, late]
    now = late + timedelta(minutes=5)

    assert due_slot(slots, now=now, attempts=[]) == late
    attempts = [now]
    assert due_slot(slots, now=now + timedelta(minutes=1), attempts=attempts) is None
    assert due_slot(slots, now=now + timedelta(minutes=30), attempts=attempts) is None


def test_failed_attempt_also_takes_its_slot() -> None:
    slots = [NOW]
    attempts = [NOW + timedelta(minutes=2)]
    assert due_slot(slots, now=NOW + timedelta(minutes=3), attempts=attempts) is None


def test_each_attempt_takes_one_slot_in_order() -> None:
    slots = [NOW, NOW + timedelta(minutes=30), NOW + timedelta(minutes=60)]
    now = NOW + timedelta(minutes=61)
    attempts = [NOW + timedelta(minutes=1)]
    assert due_slot(slots, now=now, attempts=attempts) == slots[1]
    attempts.append(NOW + timedelta(minutes=31))
    assert due_slot(slots, now=now, attempts=attempts) == slots[2]
    attempts.append(NOW + timedelta(minutes=61))
    assert due_slot(slots, now=now, attempts=attempts) is None


def test_reserved_attempt_is_not_counted_twice_once_it_reaches_the_journal() -> None:
    stored = [NOW + timedelta(seconds=40)]
    reserved = [NOW]
    assert merge_attempts(stored, reserved) == stored
    assert merge_attempts([], reserved) == reserved
    far = NOW + timedelta(hours=3)
    assert merge_attempts(stored, [far]) == [*stored, far]


def test_sender_budget_limits_per_day_and_spaces_openers() -> None:
    assert sender_may_open([], now=NOW)
    assert not sender_may_open([NOW - timedelta(minutes=10)], now=NOW)
    assert sender_may_open([NOW - MIN_OPENER_INTERVAL], now=NOW)
    many = [NOW - timedelta(hours=h) for h in range(1, MAX_OPENERS_PER_DAY + 1)]
    assert not sender_may_open(many, now=NOW)


def test_pick_partner_none_without_candidates() -> None:
    assert pick_partner([], [], random.Random(1)) is None


def test_pick_partner_prefers_familiar_but_not_always() -> None:
    familiar, stranger = uuid4(), uuid4()
    rng = random.Random(7)
    picks = [pick_partner([familiar, stranger], [familiar], rng) for _ in range(400)]
    share = picks.count(familiar) / len(picks)
    assert 0.5 < share < 0.75
    assert stranger in picks


def test_pick_partner_falls_back_when_only_one_group_exists() -> None:
    only = uuid4()
    assert pick_partner([only], [uuid4()], random.Random(1)) == only
    assert pick_partner([only], [only], random.Random(1)) == only


def test_pick_opener_does_not_repeat() -> None:
    rng = random.Random(3)
    used: list[str] = []
    for _ in range(300):
        used.append(pick_opener(used, rng))
    assert len(set(used)) == len(used)


def test_pick_opener_reuses_oldest_when_exhausted() -> None:
    rng = random.Random(3)
    # Комбинации и вариации «забиты» целиком, поэтому остаётся только повтор.
    assert pick_opener(["заглушка"], rng)
    used = list(OPENERS)
    assert pick_opener(used, random.Random(0))


def test_dialog_length_within_range() -> None:
    rng = random.Random(5)
    low, high = DIALOG_LENGTH_RANGE
    assert all(low <= dialog_length(rng) <= high for _ in range(200))


def test_dialog_ends_after_agreed_length_for_both_sides() -> None:
    a, b = uuid4(), uuid4()
    tracker = DialogTracker()
    tracker.start(a, b, length=4, now=NOW)
    # Зачин уже первое сообщение: остаётся три реплики, они чередуются.
    assert tracker.claim_reply(b, a, now=NOW)
    assert tracker.claim_reply(a, b, now=NOW)
    assert tracker.claim_reply(b, a, now=NOW)
    assert not tracker.claim_reply(a, b, now=NOW)
    assert not tracker.claim_reply(b, a, now=NOW)


def test_unknown_or_expired_dialog_gets_no_reply() -> None:
    a, b = uuid4(), uuid4()
    tracker = DialogTracker()
    assert not tracker.claim_reply(b, a, now=NOW)
    tracker.start(a, b, length=8, now=NOW)
    later = NOW + DIALOG_IDLE_TIMEOUT + timedelta(minutes=1)
    assert not tracker.claim_reply(b, a, now=later)


def test_recent_partners_remember_both_sides() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    tracker = DialogTracker()
    tracker.start(a, b, length=4, now=NOW)
    tracker.start(a, c, length=4, now=NOW)
    assert tracker.recent_partners(a) == [b, c]
    assert tracker.recent_partners(b) == [a]


def test_reply_delay_is_human_not_instant_and_mostly_short() -> None:
    rng = random.Random(11)
    delays = [reply_delay(rng) for _ in range(2000)]
    assert all(15 <= d <= 50 * 60 for d in delays)
    assert 0.55 < sum(d <= 180 for d in delays) / len(delays) < 0.75
    assert any(d > 15 * 60 for d in delays)
    assert max(delays) < DIALOG_IDLE_TIMEOUT.total_seconds()


def test_warmup_is_off_by_default_and_for_unrecognised_settings() -> None:
    assert WarmupSettings().enabled is False
    for raw in (None, {}, "on", 5, [], {"enabled": "yes"}, {"enabled": 1}):
        assert parse_warmup(raw).enabled is False


def test_parse_warmup_reads_only_what_the_user_owns() -> None:
    parsed = parse_warmup(
        {
            "enabled": True,
            "timezone": "Asia/Yekaterinburg",
            # Чужое для формы: состояние ограничения ведёт сервер и из настроек не читается.
            "restricted_at": "2026-10-02T10:00:00+00:00",
            "recovery": True,
        }
    )
    assert parsed == WarmupSettings(enabled=True, timezone="Asia/Yekaterinburg")


def test_parse_warmup_falls_back_for_bad_values() -> None:
    parsed = parse_warmup({"enabled": True, "timezone": "Mars/Base"})
    assert parsed.timezone == DEFAULT_TIMEZONE


def test_recovery_has_more_and_longer_dialogs_than_ordinary_warmup() -> None:
    agent_id = uuid4()
    ordinary = recovery = 0
    for offset in range(40):
        day = date(2026, 10, 1) + timedelta(days=offset)
        ordinary += len(daily_slots(agent_id, day))
        slots = daily_slots(agent_id, day, recovery=True)
        recovery += len(slots)
        for slot in slots:
            assert ACTIVE_FROM_HOUR <= slot.astimezone(MSK).hour < ACTIVE_TO_HOUR
    assert recovery > ordinary * 1.8
    rng = random.Random(2)
    assert min(dialog_length(rng, recovery=True) for _ in range(200)) >= 7


def test_spambot_replies_are_told_apart() -> None:
    assert (
        classify_spambot_reply("Good news, no limits are currently applied to your account.")
        is True
    )
    assert classify_spambot_reply("Ваш аккаунт свободен от каких-либо ограничений.") is True
    assert classify_spambot_reply("Unfortunately, some phone numbers may be limited.") is False
    assert classify_spambot_reply("Ваш аккаунт ограничен до 3 октября 2026.") is False
    assert classify_spambot_reply("привет") is None
    assert classify_spambot_reply(None) is None
