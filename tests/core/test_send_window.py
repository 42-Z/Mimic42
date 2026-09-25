from __future__ import annotations

from datetime import UTC, datetime, timedelta

from telethon import errors
from telethon.tl import types

from mimic42.core.send_window import SendWindow, SendWindowTracker, window_from_chat

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)


def channel(**kwargs: object) -> types.Channel:
    """Супергруппа с минимально заполненными обязательными полями."""
    defaults: dict[str, object] = {
        "id": 777,
        "title": "Тестовая супергруппа",
        "photo": types.ChatPhotoEmpty(),
        "date": NOW,
        "megagroup": True,
    }
    defaults.update(kwargs)
    return types.Channel(**defaults)  # ty: ignore[invalid-argument-type]


def banned(**kwargs: object) -> types.ChatBannedRights:
    defaults: dict[str, object] = {"until_date": None}
    defaults.update(kwargs)
    return types.ChatBannedRights(**defaults)  # ty: ignore[invalid-argument-type]


def test_plain_supergroup_is_open() -> None:
    assert window_from_chat(channel(), NOW).is_open(NOW)


def test_user_is_always_open() -> None:
    user = types.User(id=42)
    assert window_from_chat(user, NOW).is_open(NOW)


def test_slowmode_needs_seconds_from_full_chat() -> None:
    window = window_from_chat(channel(slowmode_enabled=True), NOW)
    assert window.reason == "slowmode"
    assert window.needs_slowmode is True


def test_personal_restriction_closes_until_date() -> None:
    until = NOW + timedelta(minutes=10)
    window = window_from_chat(
        channel(banned_rights=banned(until_date=until, send_messages=True)), NOW
    )
    assert window.reason == "restricted"
    assert window.forever is False
    assert window.open_at == until
    assert window.is_open(NOW) is False
    assert window.is_open(until) is True
    assert window.retry_after(NOW) == 600


def test_restriction_without_until_date_is_forever() -> None:
    window = window_from_chat(channel(banned_rights=banned(send_messages=True)), NOW)
    assert window.forever is True
    assert window.retry_after(NOW) is None


def test_restriction_longer_than_366_days_is_forever() -> None:
    until = NOW + timedelta(days=400)
    window = window_from_chat(
        channel(banned_rights=banned(until_date=until, send_messages=True)), NOW
    )
    assert window.forever is True


def test_default_banned_rights_close_the_window() -> None:
    window = window_from_chat(channel(default_banned_rights=banned(send_messages=True)), NOW)
    assert window.reason == "restricted"


def test_send_plain_restriction_also_closes_the_window() -> None:
    window = window_from_chat(channel(default_banned_rights=banned(send_plain=True)), NOW)
    assert window.reason == "restricted"


def test_admin_bypasses_slowmode_and_default_rights() -> None:
    admin = channel(
        slowmode_enabled=True,
        default_banned_rights=banned(send_messages=True),
        admin_rights=types.ChatAdminRights(post_messages=True),
    )
    assert window_from_chat(admin, NOW).is_open(NOW)


def test_min_channel_asks_for_a_full_entity() -> None:
    window = window_from_chat(channel(min=True), NOW)
    assert window.needs_entity is True


def test_left_channel_is_forever_closed() -> None:
    window = window_from_chat(channel(left=True), NOW)
    assert window.reason == "restricted"
    assert window.forever is True


def test_broadcast_without_admin_rights_is_closed() -> None:
    window = window_from_chat(channel(megagroup=None, broadcast=True), NOW)
    assert window.reason == "restricted"


def test_gigagroup_without_admin_rights_is_closed() -> None:
    window = window_from_chat(channel(gigagroup=True), NOW)
    assert window.reason == "restricted"


def test_basic_group_uses_default_rights_only() -> None:
    chat = types.Chat(
        id=5,
        title="Обычная группа",
        photo=types.ChatPhotoEmpty(),
        participants_count=3,
        date=NOW,
        version=1,
        default_banned_rights=banned(send_messages=True),
    )
    assert window_from_chat(chat, NOW).reason == "restricted"


def test_open_window_reports_zero_retry() -> None:
    assert SendWindow().retry_after(NOW) == 0


class FakeClock:
    def __init__(self, start: datetime = NOW) -> None:
        self.value = start

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value = self.value + timedelta(seconds=seconds)


class FakeClient:
    """Отдаёт сущность на get_entity и ChannelFull на GetFullChannelRequest."""

    def __init__(self, entity: object, slowmode_seconds: int | None = None) -> None:
        self.entity = entity
        self.slowmode_seconds = slowmode_seconds
        self.entity_calls = 0
        self.full_calls = 0

    async def get_entity(self, peer: object) -> object:
        self.entity_calls += 1
        return self.entity

    async def __call__(self, request: object) -> object:
        self.full_calls += 1
        full_chat = types.ChannelFull.__new__(types.ChannelFull)
        full_chat.slowmode_seconds = self.slowmode_seconds
        full_chat.slowmode_next_send_date = None
        result = types.messages.ChatFull.__new__(types.messages.ChatFull)
        result.full_chat = full_chat
        return result


def tracker_for(client: FakeClient, clock: FakeClock) -> SendWindowTracker:
    return SendWindowTracker(client, now=clock.now)


async def test_check_uses_the_passed_chat_without_network() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel())
    window = await tracker_for(client, clock).check("-100777", chat=channel())
    assert window.is_open(clock.now())
    assert client.entity_calls == 0


async def test_check_fetches_the_entity_when_none_is_given() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel())
    await tracker_for(client, clock).check("-100777")
    assert client.entity_calls == 1


async def test_entity_is_cached_until_ttl_expires() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel())
    tracker = SendWindowTracker(client, entity_ttl=300.0, now=clock.now)
    await tracker.check("-100777")
    await tracker.check("-100777")
    assert client.entity_calls == 1
    clock.advance(301)
    await tracker.check("-100777")
    assert client.entity_calls == 2


async def test_min_entity_triggers_a_refetch() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel())
    window = await tracker_for(client, clock).check("-100777", chat=channel(min=True))
    assert client.entity_calls == 1
    assert window.is_open(clock.now())


async def test_slowmode_seconds_come_from_the_full_chat() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel(slowmode_enabled=True), slowmode_seconds=30)
    window = await tracker_for(client, clock).check("-100777")
    assert window.slowmode_seconds == 30
    # Слот ещё не израсходован, поэтому писать можно прямо сейчас.
    assert window.is_open(clock.now())
    assert client.full_calls == 1


async def test_hot_path_does_not_refetch_slowmode_on_every_message() -> None:
    """Обработчик входящих передаёт chat на каждое сообщение — ChannelFull не на каждое."""
    clock = FakeClock()
    slow_chat = channel(slowmode_enabled=True)
    client = FakeClient(entity=slow_chat, slowmode_seconds=30)
    tracker = tracker_for(client, clock)
    for _ in range(5):
        await tracker.check("-100777", chat=slow_chat)
    assert client.full_calls == 1


async def test_sending_consumes_the_slot() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel(slowmode_enabled=True), slowmode_seconds=30)
    tracker = tracker_for(client, clock)
    await tracker.check("-100777")
    tracker.note_sent("-100777")

    window = await tracker.check("-100777")
    assert window.is_open(clock.now()) is False
    assert window.retry_after(clock.now()) == 30

    clock.advance(30)
    assert (await tracker.check("-100777")).is_open(clock.now())


async def test_slow_mode_error_overrides_the_local_estimate() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel(slowmode_enabled=True), slowmode_seconds=30)
    tracker = tracker_for(client, clock)
    await tracker.check("-100777")
    tracker.note_error("-100777", errors.SlowModeWaitError(request=None, capture=55))

    window = await tracker.check("-100777")
    assert window.retry_after(clock.now()) == 55


async def test_forbidden_error_closes_the_window() -> None:
    clock = FakeClock()
    tracker = tracker_for(FakeClient(entity=channel()), clock)
    await tracker.check("-100777")
    tracker.note_error("-100777", errors.ChatWriteForbiddenError(request=None))

    window = await tracker.check("-100777")
    assert window.reason == "restricted"
    assert window.forever is True
    assert window.retry_after(clock.now()) is None


async def test_forbidden_error_beats_a_stale_entity_from_the_event() -> None:
    """Сущность в событии могла устареть: слово Telegram весомее её прав."""
    clock = FakeClock()
    tracker = tracker_for(FakeClient(entity=channel()), clock)
    tracker.note_error("-100777", errors.ChatWriteForbiddenError(request=None))
    window = await tracker.check("-100777", chat=channel())
    assert window.reason == "restricted"


async def test_forbidden_error_expires_and_rights_are_reread() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel())
    tracker = SendWindowTracker(client, entity_ttl=300.0, now=clock.now)
    tracker.note_error("-100777", errors.ChatWriteForbiddenError(request=None))
    clock.advance(301)
    assert (await tracker.check("-100777")).is_open(clock.now())
    assert client.entity_calls == 1


async def test_unrelated_error_leaves_the_window_alone() -> None:
    clock = FakeClock()
    tracker = tracker_for(FakeClient(entity=channel()), clock)
    tracker.note_error("-100777", ValueError("что-то другое"))
    assert (await tracker.check("-100777")).is_open(clock.now())


async def test_announce_reports_each_state_once() -> None:
    tracker = SendWindowTracker(FakeClient(entity=channel()), now=FakeClock().now)
    assert tracker.announce("-100777", "restricted") is True
    assert tracker.announce("-100777", "restricted") is False
    assert tracker.announce("-100777", "open") is True
    assert tracker.announce("-100777", "restricted") is True


async def test_entity_failure_leaves_the_window_open_and_is_not_cached() -> None:
    """Не смогли узнать права — не наказываем агента молчанием и не запоминаем провал."""

    class BrokenClient(FakeClient):
        async def get_entity(self, peer: object) -> object:
            self.entity_calls += 1
            raise errors.ChannelPrivateError(request=None)

    clock = FakeClock()
    client = BrokenClient(entity=None)
    tracker = tracker_for(client, clock)
    assert (await tracker.check("-100777")).is_open(clock.now())
    assert (await tracker.check("-100777")).is_open(clock.now())
    assert client.entity_calls == 2


async def test_min_entity_from_an_event_reuses_a_fresh_cache() -> None:
    """Сущность из события чаще всего min: ходить за полной на каждое сообщение нельзя."""
    clock = FakeClock()
    client = FakeClient(entity=channel())
    tracker = tracker_for(client, clock)
    await tracker.check("-100777", chat=channel())
    for _ in range(3):
        await tracker.check("-100777", chat=channel(min=True))
    assert client.entity_calls == 0


async def test_min_entity_refetches_once_the_cache_is_stale() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel())
    tracker = SendWindowTracker(client, entity_ttl=300.0, now=clock.now)
    await tracker.check("-100777", chat=channel())
    clock.advance(301)
    await tracker.check("-100777", chat=channel(min=True))
    assert client.entity_calls == 1


async def test_closed_window_is_rechecked_sooner_than_an_open_one() -> None:
    """Запрет снимают руками: ждать пять минут, пока агент это заметит, незачем."""
    clock = FakeClock()
    closed = channel(default_banned_rights=banned(send_messages=True))
    client = FakeClient(entity=channel())
    tracker = SendWindowTracker(client, entity_ttl=300.0, restricted_ttl=60.0, now=clock.now)

    assert (await tracker.check("-100777", chat=closed)).reason == "restricted"
    clock.advance(30)
    await tracker.check("-100777")
    assert client.entity_calls == 0

    clock.advance(31)
    window = await tracker.check("-100777")
    assert client.entity_calls == 1
    assert window.is_open(clock.now())
