"""Диалоги аккаунта для настройки доступных агенту чатов."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

ChatKind = Literal["channel", "group", "private"]


class ChatItem(BaseModel):
    """Диалог аккаунта: то, что пользователь включает и выключает в настройках."""

    model_config = ConfigDict(frozen=True)

    id: int
    title: str
    username: str | None = None
    kind: ChatKind
    # Marked ID канала, если это группа обсуждения (комментарии) его постов.
    discussion_of: int | None = None


class ChatDirectory(Protocol):
    async def list_chats(self) -> list[ChatItem]: ...

    async def discussion_of(self, chat_id: int) -> int | None:
        """Marked ID канала, чья группа обсуждения — ``chat_id``; ``None`` — не она."""
        ...
