"""Проверяющий Telegram-аккаунт: пишет мимику и читает ответ.

По документации Telethon: StringSession (Sessions), телефон работает, только
если контакт импортирован (Entities), хендлер NewMessage регистрируется ДО
отправки, луп клиента не меняется после connect (FAQ), сессию нельзя делить
между процессами (FAQ: «database is locked»).
"""

from __future__ import annotations

import asyncio
import random
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

import asyncpg
from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession
from telethon.tl.functions.channels import (
    CreateChannelRequest,
    DeleteChannelRequest,
    InviteToChannelRequest,
    ToggleSlowModeRequest,
)
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact

from mimic42.testing.slots import plain_dsn

REPLY_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True)
class SeenMessage:
    """Сообщение, замеченное проверяющим в группе."""

    message_id: int
    sender_id: int | None
    text: str
    reply_to: int | None
    date: datetime


class Checker:
    """Асинхронное ядро проверяющего."""

    def __init__(self, api_id: int, api_hash: str, session_string: str) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._session_string = session_string
        self._client: TelegramClient | None = None

    async def start(self) -> None:
        self._client = TelegramClient(
            StringSession(self._session_string), self._api_id, self._api_hash
        )
        await self._client.connect()
        if not await self._client.is_user_authorized():
            raise RuntimeError("Session string проверяющего не авторизована — прогони login")

    async def stop(self) -> None:
        if self._client is None:
            return
        await self._client.disconnect()
        self._client = None

    @property
    def client(self) -> TelegramClient:
        assert self._client is not None
        return self._client

    async def mimic_phones(self, dsn: str, owner_id: UUID) -> list[str]:
        conn = await asyncpg.connect(plain_dsn(dsn))
        try:
            rows = await conn.fetch(
                """
                select ts.phone_number
                from agents a
                join telegram_sessions ts on ts.agent_id = a.id
                where a.owner_id = $1 and ts.phone_number is not null
                order by a.created_at
                """,
                owner_id,
            )
        finally:
            await conn.close()
        phones = [row["phone_number"] for row in rows if row["phone_number"]]
        if not phones:
            raise RuntimeError("Мимики не заведены — прогони реальный онборд")
        return phones

    async def import_contact(self, phone: str) -> None:
        """Импортирует телефон в контакты: без этого chats=[phone] не резолвится."""
        try:
            await self.client.get_input_entity(phone)
            return
        except ValueError:
            await self.client(
                ImportContactsRequest(
                    contacts=[
                        InputPhoneContact(
                            client_id=random.randrange(-(2**63), 2**63),
                            phone=phone,
                            first_name="Mimic",
                            last_name="Test",
                        )
                    ]
                )
            )
            await self.client.get_input_entity(phone)

    async def send(self, phone: str, text: str) -> int:
        message = await self.client.send_message(phone, text)
        return int(cast(Any, message).id)

    async def my_id(self) -> int:
        me = await self.client.get_me()
        if me is None:
            raise RuntimeError("Проверяющий не авторизован")
        return int(cast(Any, me).id)

    async def wait_incoming(self, phone: str, *, timeout: float = REPLY_TIMEOUT_SECONDS) -> str:
        """Ждёт первое входящее сообщение от `phone` с момента вызова."""
        loop = asyncio.get_running_loop()
        got: asyncio.Future[str] = loop.create_future()

        async def handler(event: object) -> None:
            if not got.done():
                got.set_result(str(cast(Any, event).text or ""))

        self.client.add_event_handler(handler, events.NewMessage(chats=[phone], incoming=True))
        try:
            return await asyncio.wait_for(got, timeout)
        finally:
            self.client.remove_event_handler(handler)

    # --- группы: медленный режим и права ------------------------------------------------

    async def create_supergroup(self, title: str, members: list[str]) -> int:
        """Создаёт супергруппу (медленный режим бывает только у них) и зовёт участников.

        Возвращает peer id в формате Telethon (-100...). InviteToChannelRequest не
        бросает исключение на отказ по приватности: недоставленные приглашения
        лежат в `missing_invitees`, поэтому их проверяем явно.
        """
        created = await self.client(
            CreateChannelRequest(title=title, about="mimic42 send window test", megagroup=True)
        )
        channel = cast(Any, created).chats[0]
        peer_id = int(utils.get_peer_id(channel))
        if members:
            users = [await self.client.get_input_entity(phone) for phone in members]
            invited = await self.client(
                InviteToChannelRequest(channel=channel, users=cast(Any, users))
            )
            missing = list(getattr(invited, "missing_invitees", None) or [])
            if missing:
                raise RuntimeError(f"Не удалось пригласить в группу: {missing}")
        return peer_id

    async def delete_group(self, peer_id: int) -> None:
        """Убирает тестовую группу: они создаются на настоящем аккаунте и копились бы."""
        channel = await self.client.get_input_entity(peer_id)
        await self.client(DeleteChannelRequest(channel=cast(Any, channel)))

    async def set_slow_mode(self, peer_id: int, seconds: int) -> None:
        """Допустимо: 0 (выкл), 10, 30, 60, 300, 900, 3600 — иначе SecondsInvalidError."""
        channel = await self.client.get_input_entity(peer_id)
        await self.client(ToggleSlowModeRequest(channel=cast(Any, channel), seconds=seconds))

    async def restrict(self, peer_id: int, user: int | str, *, seconds: int = 0) -> None:
        """Запрещает пользователю писать. seconds=0 — бессрочно (по документации
        edit_permissions срок короче 30 с или длиннее 366 дней считается вечным)."""
        until = timedelta(seconds=seconds) if seconds else None
        await self.client.edit_permissions(peer_id, user, until, send_messages=False)

    async def unrestrict(self, peer_id: int, user: int | str) -> None:
        """Все флаги по умолчанию True — то есть «ничего не запрещать»."""
        await self.client.edit_permissions(peer_id, user)

    async def set_default_write(self, peer_id: int, *, allowed: bool) -> None:
        """Права по умолчанию для всех участников (user=None)."""
        await self.client.edit_permissions(peer_id, None, send_messages=allowed)

    async def resolve_id(self, phone: str) -> int:
        entity = await self.client.get_entity(phone)
        return int(cast(Any, entity).id)

    async def send_many(self, peer_id: int, texts: list[str], *, pause: float) -> list[int]:
        ids: list[int] = []
        for text in texts:
            message = await self.client.send_message(peer_id, text)
            ids.append(int(cast(Any, message).id))
            await asyncio.sleep(pause)
        return ids

    async def collect_messages(self, peer_id: int, *, seconds: float) -> list[SeenMessage]:
        """Слушает группу заданное время и возвращает всё, что в ней появилось."""
        seen: list[SeenMessage] = []

        async def handler(event: Any) -> None:
            message = event.message
            reply = getattr(message, "reply_to", None)
            seen.append(
                SeenMessage(
                    message_id=int(message.id),
                    sender_id=event.sender_id,
                    text=str(message.message or ""),
                    reply_to=getattr(reply, "reply_to_msg_id", None),
                    date=message.date,
                )
            )

        self.client.add_event_handler(handler, events.NewMessage(chats=[peer_id]))
        try:
            await asyncio.sleep(seconds)
        finally:
            self.client.remove_event_handler(handler)
        return seen

    async def send_and_wait_reply(
        self, phone: str, text: str, *, timeout: float = REPLY_TIMEOUT_SECONDS
    ) -> str:
        """Регистрирует хендлер, отправляет, ждёт ответ. Порядок обязателен."""
        waiter = asyncio.ensure_future(self.wait_incoming(phone, timeout=timeout))
        await self.send(phone, text)
        try:
            return await waiter
        except BaseException:
            waiter.cancel()
            raise


class SyncChecker:
    """Синхронная обёртка для pytest-playwright: приватный луп в потоке.

    Луп один на весь срок жизни клиента (FAQ: «event loop must not change
    after connection»); все вызовы сериализуются на его лупе.
    """

    def __init__(self, api_id: int, api_hash: str, session_string: str) -> None:
        self._checker = Checker(api_id, api_hash, session_string)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def _run(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=600)

    def start(self) -> None:
        self._run(self._checker.start())

    def stop(self) -> None:
        try:
            self._run(self._checker.stop())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=30)

    def mimic_phones(self, dsn: str, owner_id: UUID) -> list[str]:
        return cast(list[str], self._run(self._checker.mimic_phones(dsn, owner_id)))

    def ensure_contact(self, phone: str) -> None:
        self._run(self._checker.import_contact(phone))

    def send(self, phone: str, text: str) -> None:
        self._run(self._checker.send(phone, text))

    def wait_incoming(self, phone: str, *, timeout: float = REPLY_TIMEOUT_SECONDS) -> str:
        return cast(str, self._run(self._checker.wait_incoming(phone, timeout=timeout)))

    def send_and_wait_reply(
        self, phone: str, text: str, *, timeout: float = REPLY_TIMEOUT_SECONDS
    ) -> str:
        return cast(str, self._run(self._checker.send_and_wait_reply(phone, text, timeout=timeout)))
