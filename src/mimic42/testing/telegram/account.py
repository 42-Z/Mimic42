"""Одно состояние поддельного телеграм-аккаунта на весь сценарий:
вход, отправленное, входящее, отметки о прочтении."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SentMessage:
    chat_id: str
    text: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    # Порядковый номер в общем потоке аккаунта: по нему история диалога
    # склеивается в хронологии, а не «входящие, потом исходящие».
    order: int = 0


@dataclass
class IncomingMessage:
    chat_id: int
    message_id: int
    text: str
    sender_id: int
    reply_to_msg_id: int | None = None
    grouped_id: int | None = None
    order: int = 0


class _FakeReplyTo:
    def __init__(self, reply_to_msg_id: int) -> None:
        self.reply_to_msg_id = reply_to_msg_id


class _FakeMessage:
    """Форма telethon.tl.types.Message, на которую опирается рантайм:
    не сам текст, а объект, у которого есть .reply_to/.post_author/.date."""

    def __init__(self, reply_to_msg_id: int | None) -> None:
        self.reply_to = _FakeReplyTo(reply_to_msg_id) if reply_to_msg_id else None
        self.post_author: str | None = None
        self.date: object | None = None


class FakeIncomingEvent:
    """Форма события Telethon, на которую рассчитывает рантайм."""

    def __init__(self, message: IncomingMessage, client: object) -> None:
        self.chat_id = message.chat_id
        self.sender_id = message.sender_id
        self.id = message.message_id
        self.text = message.text
        self.raw_text = message.text
        self.message = _FakeMessage(message.reply_to_msg_id)
        self.is_private = True
        self.client = client
        self.grouped_id = message.grouped_id
        self._reply_to_msg_id = message.reply_to_msg_id

    async def get_chat(self) -> object:
        return type("Chat", (), {"id": self.chat_id, "username": None})()

    async def get_reply_message(self) -> object | None:
        if self._reply_to_msg_id is None:
            return None
        preview = f"original text {self._reply_to_msg_id}"
        return type("ReplyMessage", (), {"raw_text": preview, "text": preview})()

    async def get_input_chat(self) -> object:
        return await self.get_chat()


class FakeTelegramAccount:
    def __init__(self) -> None:
        self.phone: str | None = None
        self.username: str | None = None
        self.authorized = False
        self.expected_code: str | None = None
        self.password: str | None = None
        self.password_satisfied = True
        self.code_requested = False
        self.sent: list[SentMessage] = []
        self.incoming: list[IncomingMessage] = []
        self.read_marks: list[str] = []
        self.handlers: list[Callable[[Any], Awaitable[None]]] = []
        self._next_message_id = 1000
        self._next_order_value = 0

    def next_order(self) -> int:
        """Сквозной номер события для хронологии переписки."""
        self._next_order_value += 1
        return self._next_order_value

    def script_code(self, code: str) -> None:
        self.expected_code = code

    def require_password(self, password: str) -> None:
        self.password = password
        self.password_satisfied = False

    async def deliver(self, *, chat_id: int, text: str, sender_id: int = 999) -> None:
        self._next_message_id += 1
        message = IncomingMessage(
            chat_id=chat_id,
            message_id=self._next_message_id,
            text=text,
            sender_id=sender_id,
            order=self.next_order(),
        )
        self.incoming.append(message)
        for handler in list(self.handlers):
            await handler(FakeIncomingEvent(message, client=self))

    async def download_media(self, message: Any, file: Any = None, **kwargs: Any) -> Any:
        return None
