from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mimic42.testing.telegram.account import FakeTelegramAccount, SentMessage


def _peer_key(peer: Any) -> str:
    """Каноничный ключ пира для отметок о прочтении.

    Рантайм передаёт то int, то InputPeer-объект; у объекта id живёт в
    атрибутах. Строковый repr сюда не годится: по нему нельзя сравнить
    пиров на равенство."""
    for attr in ("user_id", "chat_id", "id"):
        value = getattr(peer, attr, None)
        if isinstance(value, int):
            return str(value)
    return str(peer)


class FakeTelegramClient:
    """Подделка клиента-пользователя: связь, отправка, отметки, события.

    Отвечает на служебные запросы рантайма (typing, read, notify) пустым
    объектом, потому что рантайм читает из них поля через getattr с
    дефолтом. Полноценные RPC-ответы (диалоги, история, медиа) здесь не
    эмулируются: инструменты телеги проверяются своими тестами против
    адресных заглушек, а не против этой подделки.
    """

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
            self.account.read_marks.append(_peer_key(getattr(request, "peer", "")))
        return {}

    async def connect(self) -> None:
        self.connect_calls += 1
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    async def is_user_authorized(self) -> bool:
        return self.account.authorized

    async def send_message(self, entity: str | int, message: str, **kwargs: Any) -> object:
        self.account.sent.append(
            SentMessage(
                chat_id=str(entity),
                text=message,
                kwargs=kwargs,
                order=self.account.next_order(),
            )
        )
        return type("Message", (), {"id": len(self.account.sent)})()

    async def send_file(self, entity: str | int, file: Any, **kwargs: Any) -> object:
        """Файл записывается как обычное сообщение: текст — подпись, а сам
        поток кладётся в kwargs, чтобы тест мог проверить имя и содержимое."""
        caption = kwargs.pop("caption", None) or ""
        self.account.sent.append(
            SentMessage(
                chat_id=str(entity),
                text=caption,
                kwargs={**kwargs, "file": file},
                order=self.account.next_order(),
            )
        )
        # media отправленного сообщения Telethon принимает обратно как файл:
        # по нему тест видит, что картинка переотправлена, а не залита заново.
        message_id = len(self.account.sent)
        media = type("Media", (), {"message_id": message_id})()
        return type("Message", (), {"id": message_id, "media": media})()

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
