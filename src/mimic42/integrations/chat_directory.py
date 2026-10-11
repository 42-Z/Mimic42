"""Диалоги аккаунта и связь «канал — группа обсуждения» через Telethon."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

from telethon import functions, types, utils

from mimic42.core.chat_directory import ChatItem, ChatKind

logger = logging.getLogger("mimic42.chat_directory")

LINK_CACHE_TTL_SECONDS = 3600.0
# Короткий: кнопка «Обновить список» в настройках должна показывать новые чаты, а кеш
# только гасит повторные запросы при перемонтировании секции.
LIST_CACHE_TTL_SECONDS = 10.0
SAVED_MESSAGES_TITLE = "Избранное"
# Основной список и архив: Telegram отдаёт архив папкой 1.
_DIALOG_FOLDERS = (0, 1)
# Запросов GetFullChannel одновременно: у аккаунта с сотнями групп обсуждения
# первая загрузка списка иначе упирается во флуд-лимит.
_LOOKUP_CONCURRENCY = 5


class DirectoryClient(Protocol):
    def iter_dialogs(self, limit: int | None = None, **kwargs: Any) -> Any: ...
    async def get_input_entity(self, entity: Any) -> Any: ...
    async def __call__(self, request: object) -> Any: ...


def chat_kind(entity: Any) -> ChatKind:
    """Вещательный канал, группа (в т. ч. супергруппа) или личный диалог."""
    if isinstance(entity, types.User):
        return "private"
    if isinstance(entity, types.Channel):
        return "group" if entity.megagroup else "channel"
    return "group"


class TelethonChatDirectory:
    """Список диалогов для настроек и поиск канала по его группе обсуждения."""

    def __init__(
        self, client: DirectoryClient, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._client = client
        self._clock = clock
        self._links: dict[int, tuple[int | None, float]] = {}
        self._listing: tuple[list[ChatItem], float] | None = None
        self._lookup_slots = asyncio.Semaphore(_LOOKUP_CONCURRENCY)
        self._lookups: dict[int, asyncio.Future[int | None]] = {}

    async def discussion_of(self, chat_id: int) -> int | None:
        """Marked ID канала, чья группа обсуждения — ``chat_id``; ``None`` — не она.

        Успех кешируется на час; сбой поднимается вызывающему и не запоминается.
        Одновременные вызовы про одну группу делят один запрос: проверка доступа идёт
        на каждое входящее сообщение, и всплеск в группе иначе породил бы столько же
        запросов к Telegram, пока первый ещё не ответил. Все запросы идут через общий
        лимит одновременных.
        """
        cached = self._links.get(chat_id)
        if cached is not None and cached[1] > self._clock():
            return cached[0]
        lookup = self._lookups.get(chat_id)
        if lookup is None:
            lookup = asyncio.ensure_future(self._lookup(chat_id))
            self._lookups[chat_id] = lookup
            lookup.add_done_callback(lambda done: self._finish_lookup(chat_id, done))
        # shield: отмена одного ожидающего не должна обрывать запрос для остальных.
        return await asyncio.shield(lookup)

    async def _lookup(self, chat_id: int) -> int | None:
        async with self._lookup_slots:
            channel_id = await self._fetch_discussion_of(chat_id)
        self._links[chat_id] = (channel_id, self._clock() + LINK_CACHE_TTL_SECONDS)
        return channel_id

    def _finish_lookup(self, chat_id: int, done: asyncio.Future[int | None]) -> None:
        if self._lookups.get(chat_id) is done:
            del self._lookups[chat_id]
        if not done.cancelled():
            # Ошибку получили ожидающие; без этого asyncio пишет «exception was never
            # retrieved», когда все ожидающие успели уйти.
            done.exception()

    async def _fetch_discussion_of(self, chat_id: int) -> int | None:
        real_id, _ = utils.resolve_id(chat_id)
        input_chat = await self._client.get_input_entity(chat_id)
        full = await self._client(functions.channels.GetFullChannelRequest(channel=input_chat))
        group = next((chat for chat in full.chats if getattr(chat, "id", None) == real_id), None)
        # Связь у вещательного канала указывает на его обсуждение, а не наоборот:
        # «канала, чьей группой он был бы» у него нет.
        if not (isinstance(group, types.Channel) and group.megagroup):
            return None
        linked = getattr(full.full_chat, "linked_chat_id", None)
        if not isinstance(linked, int):
            return None
        return utils.get_peer_id(types.PeerChannel(linked))

    async def list_chats(self) -> list[ChatItem]:
        if self._listing is not None and self._listing[1] > self._clock():
            return self._listing[0]
        dialogs = await self._read_dialogs()
        items = list(await asyncio.gather(*(self._to_item(dialog) for dialog in dialogs)))
        self._listing = (items, self._clock() + LIST_CACHE_TTL_SECONDS)
        return items

    async def _read_dialogs(self) -> list[Any]:
        seen: set[int] = set()
        dialogs: list[Any] = []
        for folder in _DIALOG_FOLDERS:
            async for dialog in self._client.iter_dialogs(folder=folder):
                if dialog.id in seen:
                    continue
                seen.add(dialog.id)
                dialogs.append(dialog)
        return dialogs

    async def _to_item(self, dialog: Any) -> ChatItem:
        entity = dialog.entity
        is_self = bool(getattr(entity, "is_self", False))
        discussion_of: int | None = None
        discussion_unknown = False
        # Признак has_link есть у самой сущности: запрос нужен только супергруппам,
        # которые чьи-то обсуждения.
        if (
            isinstance(entity, types.Channel)
            and entity.megagroup
            and bool(getattr(entity, "has_link", False))
        ):
            try:
                discussion_of = await self.discussion_of(dialog.id)
            except Exception:
                # Список не ломается из-за одной группы, но «не узнали» — не то же, что
                # «своего канала нет»: иначе группу предложили бы отключить отдельно, а
                # правило доступа отпустило бы её вместе с включённым каналом.
                logger.warning(
                    "Failed to find the channel of discussion group %s", dialog.id, exc_info=True
                )
                discussion_unknown = True
        return ChatItem(
            id=dialog.id,
            title=SAVED_MESSAGES_TITLE if is_self else (dialog.title or str(dialog.id)),
            username=getattr(entity, "username", None),
            kind=chat_kind(entity),
            discussion_of=discussion_of,
            discussion_unknown=discussion_unknown,
        )
