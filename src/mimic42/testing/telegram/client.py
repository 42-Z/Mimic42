from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from telethon import errors, functions, types

from mimic42.testing.telegram.account import FakeTelegramAccount, SentMessage

_FAKE_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{5,32}$")


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
        if isinstance(request, functions.account.GetPasswordRequest):
            return types.account.Password(
                new_algo=types.PasswordKdfAlgoUnknown(),
                new_secure_algo=types.SecurePasswordKdfAlgoUnknown(),
                secure_random=b"\0" * 256,
                has_password=self.account.has_password,
                hint=self.account.password_hint,
            )
        if isinstance(request, functions.account.UpdateUsernameRequest):
            return self._update_username(request)
        name = type(request).__name__
        if "ReadHistory" in name:
            self.account.read_marks.append(_peer_key(getattr(request, "peer", "")))
        return {}

    def _update_username(self, request: functions.account.UpdateUsernameRequest) -> object:
        username = request.username
        if _FAKE_USERNAME_PATTERN.fullmatch(username) is None:
            raise errors.UsernameInvalidError(request=request)
        if username == self.account.username:
            raise errors.UsernameNotModifiedError(request=request)
        if username in self.account.occupied_usernames:
            raise errors.UsernameOccupiedError(request=request)
        self.account.username = username
        return types.User(id=777, first_name="Fake", username=username)

    async def connect(self) -> None:
        self.connect_calls += 1
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    async def is_user_authorized(self) -> bool:
        return self.account.authorized

    async def get_me(self) -> object:
        # Как у Telethon: без входа пользователь неизвестен (None),
        # а у аккаунта может не быть @username.
        if not self.account.authorized:
            return None
        return type("User", (), {"id": 777, "username": self.account.username})()

    async def edit_2fa(
        self,
        current_password: str | None = None,
        new_password: str | None = None,
        *,
        hint: str = "",
    ) -> bool:
        return await self.account.apply_password_change(current_password, new_password, hint)

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

    def iter_dialogs(self, limit: int | None = None, **kwargs: Any) -> Any:
        """Диалоги как у Telethon: без фильтра — все вместе с архивом, ``folder=0`` или
        ``archived=False`` — основной список, ``folder=1`` или ``archived=True`` — архив."""
        folder = kwargs.get("folder")
        archived_only = kwargs.get("archived")
        if folder is None and archived_only is not None:
            folder = 1 if archived_only else 0
        if folder is None:
            dialogs = list(self.account.dialogs)
        else:
            dialogs = [d for d in self.account.dialogs if d.archived == (folder == 1)]

        async def gen() -> Any:
            for dialog in dialogs:
                yield type(
                    "Dialog",
                    (),
                    {"id": dialog.id, "title": dialog.title, "entity": dialog.entity},
                )()

        return gen()

    @property
    def sent_messages(self) -> list[tuple[str, str]]:
        return [(message.chat_id, message.text) for message in self.account.sent]

    @property
    def handlers(self) -> list[Callable[[Any], Awaitable[None]]]:
        return self.account.handlers

    async def download_media(self, message: Any, file: Any = None, **kwargs: Any) -> Any:
        return await self.account.download_media(message, file, **kwargs)
