from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mimic42.testing.telegram.account import FakeTelegramAccount, SentMessage


class FakeTelegramClient:
    def __init__(self, account: FakeTelegramAccount | None = None) -> None:
        # Рабочий клиент по умолчанию изображает уже прошедшую онбординг
        # сессию — в отличие от голого FakeTelegramAccount() для входа.
        if account is None:
            account = FakeTelegramAccount()
            account.authorized = True
        self.account = account
        self.requests: list[object] = []
        self.connected = False
        self.connect_calls = 0
        self.disconnect_calls = 0

    async def __call__(self, request: Any) -> Any:
        self.requests.append(request)
        name = type(request).__name__
        if "ReadHistory" in name:
            self.account.read_marks.append(str(getattr(request, "peer", "")))
        return {}

    async def connect(self) -> None:
        self.connect_calls += 1
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    async def is_user_authorized(self) -> bool:
        return self.account.authorized

    async def send_message(self, entity: str, message: str, **kwargs: Any) -> object:
        self.account.sent.append(SentMessage(chat_id=str(entity), text=message, kwargs=kwargs))
        return type("Message", (), {"id": len(self.account.sent)})()

    def add_event_handler(
        self,
        callback: Callable[[Any], Awaitable[None]],
        event: object | None = None,
    ) -> None:
        self.account.handlers.append(callback)

    async def emit_message(self, event: Any) -> None:
        """Скармливает произвольное событие зарегистрированным обработчикам
        напрямую — в отличие от account.deliver, не строит событие само,
        подходит и для кастомных форм события (медиа-вложения и т.п.)."""
        for callback in list(self.account.handlers):
            await callback(event)

    @property
    def sent_messages(self) -> list[tuple[str, str]]:
        return [(message.chat_id, message.text) for message in self.account.sent]

    @property
    def handlers(self) -> list[Callable[[Any], Awaitable[None]]]:
        return self.account.handlers

    async def download_media(self, message: Any, file: Any = None, **kwargs: Any) -> Any:
        return await self.account.download_media(message, file, **kwargs)
