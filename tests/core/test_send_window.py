from __future__ import annotations

from datetime import UTC, datetime, timedelta

from telethon.tl import types

from mimic42.core.send_window import SendWindow, window_from_chat

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
