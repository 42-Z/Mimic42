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

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

logger = logging.getLogger("mimic42.send_window")

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


_FLOOD_ERRORS = ("SlowModeWaitError", "FloodWaitError", "FloodPremiumWaitError")
_FORBIDDEN_ERRORS = (
    "ChatWriteForbiddenError",
    "UserBannedInChannelError",
    "ChatRestrictedError",
    "ChatSendPlainForbiddenError",
    "ChatSendMediaForbiddenError",
    "ChatSendStickersForbiddenError",
    "ChatSendGifsForbiddenError",
    "ChatSendPhotosForbiddenError",
    "ChatSendVideosForbiddenError",
    "ChatSendVoicesForbiddenError",
    "ChatSendPollForbiddenError",
    "ChatAdminRequiredError",
    "ChannelPrivateError",
)


def _peer_argument(peer: str) -> str | int:
    """Числовой peer Telethon ждёт числом, иначе резолв идёт как по юзернейму."""
    stripped = peer.strip()
    if stripped.lstrip("-").isdigit():
        return int(stripped)
    return stripped


class SendWindowTracker:
    """Состояние окна отправки по чатам одного агента.

    Права стоят сетевого запроса: get_entity, по документации, всегда ходит в
    API за свежей версией сущности. Поэтому результат кэшируется на entity_ttl.
    Ошибка Telegram точнее любого локального расчёта: она закрывает окно на тот
    же срок поверх любой сущности, а по истечении права перечитываются заново.
    """

    def __init__(
        self,
        client: Any,
        *,
        entity_ttl: float = 300.0,
        restricted_ttl: float = 60.0,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._ttl = timedelta(seconds=entity_ttl)
        # Закрытое окно перепроверяем чаще: запрет снимают руками, а обратная цена
        # низкая — проверка происходит только когда в чат приходит сообщение.
        self._restricted_ttl = timedelta(seconds=restricted_ttl)
        self._now = now if now is not None else lambda: datetime.now(UTC)
        self._base: dict[str, tuple[SendWindow, datetime]] = {}
        self._blocked_until: dict[str, datetime] = {}
        self._forced_closed_until: dict[str, datetime] = {}
        self._announced: dict[str, str] = {}

    async def check(self, peer: str, chat: Any = None) -> SendWindow:
        now = self._now()

        forced = self._forced_closed_until.get(peer)
        if forced is not None:
            if forced > now:
                return _FOREVER_CLOSED
            self._forced_closed_until.pop(peer, None)

        base = await self._base_window(peer, chat, now)
        if base.reason == "restricted":
            return base

        blocked = self._blocked_until.get(peer)
        if blocked is not None:
            if blocked > now:
                return SendWindow(
                    reason="slowmode", open_at=blocked, slowmode_seconds=base.slowmode_seconds
                )
            self._blocked_until.pop(peer, None)
        # Окно открыто, но длину слота агенту знать полезно: он платит ею за ответ.
        return SendWindow(slowmode_seconds=base.slowmode_seconds)

    def note_sent(self, peer: str) -> None:
        cached = self._base.get(peer)
        seconds = cached[0].slowmode_seconds if cached is not None else None
        if seconds:
            self._blocked_until[peer] = self._now() + timedelta(seconds=seconds)

    def note_error(self, peer: str, exc: BaseException) -> None:
        name = type(exc).__name__
        if name in _FLOOD_ERRORS:
            seconds = getattr(exc, "seconds", None)
            if isinstance(seconds, int):
                self._blocked_until[peer] = self._now() + timedelta(seconds=seconds)
        elif name in _FORBIDDEN_ERRORS:
            self._forced_closed_until[peer] = self._now() + self._ttl
            self._blocked_until.pop(peer, None)

    def announce(self, peer: str, reason: str) -> bool:
        """True, если про это состояние чата ещё не сообщали агенту."""
        if self._announced.get(peer) == reason:
            return False
        self._announced[peer] = reason
        return True

    def forget(self, peer: str) -> None:
        for store in (self._base, self._blocked_until, self._forced_closed_until, self._announced):
            store.pop(peer, None)

    async def _base_window(self, peer: str, chat: Any, now: datetime) -> SendWindow:
        cached = self._base.get(peer)
        fresh = cached is not None and cached[1] > now
        if chat is None and cached is not None and fresh:
            return cached[0]

        window = window_from_chat(chat, now) if chat is not None else SendWindow(needs_entity=True)
        if window.needs_entity:
            if chat is not None and fresh and cached is not None:
                # Сущность из события почти всегда min: ходить за полной на каждое
                # сообщение группы незачем, пока кэш свежий.
                return cached[0]
            entity = await self._fetch_entity(peer)
            if entity is None:
                # Права выяснить не удалось: не молчим и не запоминаем провал.
                return OPEN
            window = window_from_chat(entity, now)
        if window.needs_slowmode:
            known = cached[0].slowmode_seconds if cached is not None and fresh else None
            window = (
                SendWindow(slowmode_seconds=known) if known else await self._fill_slowmode(peer)
            )

        ttl = self._restricted_ttl if window.reason == "restricted" else self._ttl
        self._base[peer] = (window, now + ttl)
        return window

    async def _fetch_entity(self, peer: str) -> Any:
        get_entity = getattr(self._client, "get_entity", None)
        if not callable(get_entity):
            return None
        try:
            return await get_entity(_peer_argument(peer))
        except Exception:
            logger.warning("Не удалось получить сущность чата %s", peer, exc_info=True)
            return None

    async def _fill_slowmode(self, peer: str) -> SendWindow:
        from telethon import functions

        try:
            # Документация запроса: подойдёт всё entity-like, Telethon резолвит сам.
            channel = cast(Any, _peer_argument(peer))
            result = await self._client(functions.channels.GetFullChannelRequest(channel=channel))
        except Exception:
            logger.warning("Не удалось получить ChannelFull для %s", peer, exc_info=True)
            return OPEN

        full_chat = getattr(result, "full_chat", None)
        seconds = getattr(full_chat, "slowmode_seconds", None)
        next_send = _as_utc(getattr(full_chat, "slowmode_next_send_date", None))
        if next_send is not None:
            self._blocked_until[peer] = next_send
        if not isinstance(seconds, int) or seconds <= 0:
            return OPEN
        return SendWindow(slowmode_seconds=seconds)
