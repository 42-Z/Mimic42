"""Какие чаты доступны агенту (settings.disabled_chats).

Чат доступен, пока его ID нет в списке отключённых: новые чаты и каналы
включаются сами. Исключение — комментарии: группа обсуждения доступна, если
включён её канал. Нечитаемое значение не должно ни ронять агента, ни отключать
чаты случайно, поэтому разбор терпимый.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("mimic42.chat_access")

# Marked ID каналов и супергрупп — «-100» и ID канала: всё левее порога — Channel.
# Группой обсуждения может быть только супергруппа, остальным поиск связи не нужен.
_MIN_PLAIN_CHAT_ID = -1_000_000_000_000

DiscussionLookup = Callable[[int], Awaitable[int | None]]


class ChatDisabledError(Exception):
    """Инструмент или таймер обратились к чату, отключённому в настройках агента."""

    def __init__(self, chat_id: int | None = None) -> None:
        super().__init__("Чат недоступен: он отключён в настройках агента.")
        self.chat_id = chat_id


def parse_disabled_chats(raw: Any) -> frozenset[int]:
    """Разобрать ``settings.disabled_chats``: только целые, остальное отбрасывается."""
    if raw is None:
        return frozenset()
    if not isinstance(raw, (list, tuple)):
        logger.warning(
            "disabled_chats has unexpected type %s; no chats disabled", type(raw).__name__
        )
        return frozenset()
    return frozenset(item for item in raw if isinstance(item, int) and not isinstance(item, bool))


def link_hint(entity: Any) -> bool | None:
    """Признак ``Channel.has_link`` у сущности: связана ли она с обсуждением или каналом.

    Настоящий ``bool`` приходит у разобранных сущностей Telegram; у остальных
    (InputPeer, заглушки) признак неизвестен, и вызывающему придётся спросить.
    """
    value = getattr(entity, "has_link", None)
    return value if isinstance(value, bool) else None


class ChatAccess:
    """Правило доступа по ID чата. Создаётся только при непустом списке отключённых."""

    def __init__(self, disabled: frozenset[int], discussion_of: DiscussionLookup) -> None:
        self._disabled = disabled
        self._discussion_of = discussion_of

    @property
    def disabled(self) -> frozenset[int]:
        return self._disabled

    async def allows(self, chat_id: int, *, has_link: bool | None = None) -> bool:
        """Доступен ли чат агенту.

        ``has_link=False`` — сущность уже в руках и связи с каналом у неё нет:
        запрос не нужен. Сбой поиска считается «не связана».
        """
        if chat_id not in self._disabled:
            return True
        if chat_id > _MIN_PLAIN_CHAT_ID or has_link is False:
            return False
        try:
            channel_id = await self._discussion_of(chat_id)
        except Exception:
            logger.warning(
                "Failed to find the channel of discussion group %s", chat_id, exc_info=True
            )
            return False
        return channel_id is not None and channel_id not in self._disabled
