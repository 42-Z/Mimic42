"""Вступление мимика в группу обсуждения перед комментариями.

Вступление — единственная запись в группу отсюда. Осмотр после него только
читает последние сообщения: бот-верификатор встречает новичка за секунду-две,
и писать, не увидев его кнопок, значит получить отказ уже на комментарии.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from telethon import errors, functions

from mimic42.core.attack_target import AttackTarget

JOIN_SETTLE_SECONDS = 2.0

_JOIN_INSPECTION_MESSAGES = 8
_JOIN_INSPECTION_WINDOW = timedelta(seconds=30)

_JOIN_BLOCKERS = (
    errors.InviteRequestSentError,
    errors.ChatWriteForbiddenError,
    errors.UserBannedInChannelError,
    errors.ChannelPrivateError,
    errors.ChatAdminRequiredError,
)


class JoinBlockedError(RuntimeError):
    """Группа не даёт писать: капча, заявка на вступление или закрытый чат."""


async def join_if_needed(client: Any, target: AttackTarget) -> None:
    """Вступить в группу, если без этого писать нельзя, и проверить капчу."""
    group = target.group
    if not getattr(group, "left", False):
        return
    if getattr(group, "join_to_send", None) is False:
        return

    joined_at = datetime.now(UTC)
    try:
        await client(functions.channels.JoinChannelRequest(channel=group))
    except errors.UserAlreadyParticipantError:
        return
    except _JOIN_BLOCKERS as exc:
        raise JoinBlockedError("Telegram не пускает в группу обсуждения.") from exc

    if JOIN_SETTLE_SECONDS > 0:
        await asyncio.sleep(JOIN_SETTLE_SECONDS)

    try:
        recent = await client.get_messages(group, limit=_JOIN_INSPECTION_MESSAGES)
    except _JOIN_BLOCKERS as exc:
        raise JoinBlockedError("После вступления группа обсуждения недоступна.") from exc

    if any(_is_recent_verification(message, joined_at) for message in _messages(recent)):
        raise JoinBlockedError("После вступления группа требует пройти проверку.")


def _is_recent_verification(message: Any, joined_at: datetime) -> bool:
    if not getattr(getattr(message, "reply_markup", None), "rows", None):
        return False
    date = getattr(message, "date", None)
    if date is None:
        return False
    if date.tzinfo is None:
        date = date.replace(tzinfo=UTC)
    return date >= joined_at - _JOIN_INSPECTION_WINDOW


def _messages(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
