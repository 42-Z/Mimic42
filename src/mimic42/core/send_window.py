"""Окно отправки: когда агенту снова можно писать в чат.

Медленный режим и отобранное право писать — одно состояние: отправка закрыта
до момента T. Для кд T — момент открытия слота, для ограничения прав — until_date
(возможно, бесконечность).

Фактура взята из документации Telegram, а не из исходников Telethon:

- until_date считается вечным при длительности меньше 30 секунд или больше
  366 дней (core.telegram.org/constructor/chatBannedRights);
- у min-версии Channel поверх локальной копии разрешено применять только
  перечисленный набор полей, и banned_rights с admin_rights в него не входят —
  значит личные права у такой сущности недостоверны
  (core.telegram.org/constructor/channel);
- slowmode_seconds и slowmode_next_send_date живут в ChannelFull и оба
  опциональны (core.telegram.org/constructor/channelFull).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

Reason = Literal["open", "slowmode", "restricted"]

# «Вечным считается любое значение меньше 30 секунд или больше 366 дней.»
_FOREVER_BELOW = timedelta(seconds=30)
_FOREVER_ABOVE = timedelta(days=366)


@dataclass(frozen=True)
class SendWindow:
    """Состояние отправки в один чат."""

    reason: Reason = "open"
    open_at: datetime | None = None
    forever: bool = False
    slowmode_seconds: int | None = None
    needs_entity: bool = False
    """Сущность пришла в min-виде: права недостоверны, нужна полная."""
    needs_slowmode: bool = False
    """Медленный режим включён, но длина слота ещё неизвестна."""

    def is_open(self, now: datetime) -> bool:
        if self.reason == "open":
            return True
        if self.forever:
            return False
        return self.open_at is not None and self.open_at <= now

    def retry_after(self, now: datetime) -> int | None:
        """Сколько секунд ждать. None — ждать бессмысленно."""
        if self.is_open(now):
            return 0
        if self.forever or self.open_at is None:
            return None
        return max(0, int((self.open_at - now).total_seconds()))


OPEN = SendWindow()
_FOREVER_CLOSED = SendWindow(reason="restricted", forever=True)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _is_forever(until_date: datetime | None, now: datetime) -> bool:
    until = _as_utc(until_date)
    if until is None:
        return True
    duration = until - now
    return duration < _FOREVER_BELOW or duration > _FOREVER_ABOVE


def _from_banned_rights(rights: Any, now: datetime) -> SendWindow | None:
    """Окно по ChatBannedRights или None, если писать они не мешают.

    send_messages запрещает сообщения целиком, send_plain — только текст;
    для агента, который отвечает текстом, оба означают «писать нельзя».
    """
    if rights is None:
        return None
    blocked = bool(getattr(rights, "send_messages", False)) or bool(
        getattr(rights, "send_plain", False)
    )
    if not blocked:
        return None
    until = getattr(rights, "until_date", None)
    if _is_forever(until, now):
        return _FOREVER_CLOSED
    return SendWindow(reason="restricted", open_at=_as_utc(until))


def window_from_chat(chat: Any, now: datetime) -> SendWindow:
    """Окно по сущности чата. Сетевых запросов не делает."""
    from telethon.tl import types

    if chat is None or isinstance(chat, types.User):
        return OPEN

    if isinstance(chat, types.Chat):
        if getattr(chat, "left", False) or getattr(chat, "deactivated", False):
            return _FOREVER_CLOSED
        if getattr(chat, "creator", False) or getattr(chat, "admin_rights", None) is not None:
            return OPEN
        return _from_banned_rights(getattr(chat, "default_banned_rights", None), now) or OPEN

    if not isinstance(chat, types.Channel):
        return OPEN

    if getattr(chat, "left", False):
        return _FOREVER_CLOSED

    if getattr(chat, "min", False):
        # Админство и личные ограничения у min-сущности применять нельзя —
        # решение без них было бы враньём, поэтому просим полную сущность.
        return SendWindow(needs_entity=True)

    if getattr(chat, "creator", False) or getattr(chat, "admin_rights", None) is not None:
        return OPEN

    own = _from_banned_rights(getattr(chat, "banned_rights", None), now)
    if own is not None:
        return own

    default = _from_banned_rights(getattr(chat, "default_banned_rights", None), now)
    if default is not None:
        return default

    if getattr(chat, "broadcast", False) or getattr(chat, "gigagroup", False):
        # В канал и в гигагруппу пишут только админы, а админом мы здесь уже не являемся.
        return _FOREVER_CLOSED

    if getattr(chat, "slowmode_enabled", False):
        return SendWindow(reason="slowmode", needs_slowmode=True)

    return OPEN
