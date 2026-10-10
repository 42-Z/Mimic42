"""Каталог диалогов: виды чатов, архив, группы обсуждения, кеши."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from telethon import functions, types

from mimic42.core.chat_directory import ChatItem
from mimic42.integrations.chat_directory import (
    LINK_CACHE_TTL_SECONDS,
    LIST_CACHE_TTL_SECONDS,
    TelethonChatDirectory,
    chat_kind,
)

DATE = datetime(2026, 1, 1, tzinfo=UTC)
CHANNEL_ID = -1001000000001
GROUP_ID = -1001000000002


def _channel(real_id: int, title: str, *, megagroup: bool, has_link: bool = False) -> Any:
    return types.Channel(
        id=real_id,
        title=title,
        photo=types.ChatPhotoEmpty(),
        date=DATE,
        access_hash=1,
        broadcast=not megagroup or None,
        megagroup=megagroup or None,
        has_link=has_link or None,
        username=f"u{real_id}",
    )


def _user(real_id: int, name: str, *, is_self: bool = False) -> Any:
    return types.User(id=real_id, first_name=name, access_hash=1, is_self=is_self or None)


def _dialog(marked_id: int, title: str, entity: Any) -> Any:
    return SimpleNamespace(id=marked_id, title=title, entity=entity)


class FakeDirectoryClient:
    def __init__(
        self,
        main: list[Any] | None = None,
        archive: list[Any] | None = None,
        links: dict[int, int | None] | None = None,
        discussions: dict[int, int] | None = None,
    ) -> None:
        self.folders = {0: main or [], 1: archive or []}
        # реальный ID группы → реальный ID канала (или None)
        self.links = links or {}
        # реальный ID вещательного канала → реальный ID его группы обсуждения
        self.discussions = discussions or {}
        self.requests: list[Any] = []
        self.fail_lookups = False

    def iter_dialogs(self, limit: int | None = None, **kwargs: Any) -> Any:
        # Каталог читает диалоги целиком: лимита быть не должно.
        assert limit is None
        dialogs = self.folders[kwargs["folder"]]

        async def gen() -> Any:
            for dialog in dialogs:
                yield dialog

        return gen()

    async def get_input_entity(self, entity: Any) -> Any:
        return types.InputPeerChannel(channel_id=abs(entity) - 1_000_000_000_000, access_hash=1)

    async def __call__(self, request: object) -> Any:
        assert isinstance(request, functions.channels.GetFullChannelRequest)
        self.requests.append(request)
        if self.fail_lookups:
            raise RuntimeError("FLOOD_WAIT")
        real_id = cast(Any, request.channel).channel_id
        if real_id in self.links:
            group = _channel(real_id, "g", megagroup=True, has_link=True)
            linked = self.links[real_id]
        else:
            group = _channel(real_id, "c", megagroup=False, has_link=True)
            linked = self.discussions.get(real_id)
        return SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=linked), chats=[group])


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_chat_kinds() -> None:
    assert chat_kind(_user(7, "Анна")) == "private"
    assert chat_kind(_channel(1, "Новости", megagroup=False)) == "channel"
    assert chat_kind(_channel(2, "Чат", megagroup=True)) == "group"
    chat = types.Chat(
        id=3,
        title="Старая группа",
        photo=types.ChatPhotoEmpty(),
        participants_count=2,
        date=DATE,
        version=1,
    )
    assert chat_kind(chat) == "group"


@pytest.mark.asyncio
async def test_list_merges_main_list_and_archive_without_duplicates() -> None:
    news = _dialog(CHANNEL_ID, "Новости", _channel(1000000001, "Новости", megagroup=False))
    anna = _dialog(7, "Анна", _user(7, "Анна"))
    client = FakeDirectoryClient(main=[news, anna], archive=[anna])
    directory = TelethonChatDirectory(client)

    items = await directory.list_chats()

    assert [(item.id, item.kind, item.title) for item in items] == [
        (CHANNEL_ID, "channel", "Новости"),
        (7, "private", "Анна"),
    ]
    assert all(isinstance(item, ChatItem) for item in items)
    assert items[0].username == "u1000000001"


@pytest.mark.asyncio
async def test_own_chat_is_titled_saved_messages() -> None:
    me = _dialog(777, "Janna", _user(777, "Janna", is_self=True))
    directory = TelethonChatDirectory(FakeDirectoryClient(main=[me]))

    assert (await directory.list_chats())[0].title == "Избранное"


@pytest.mark.asyncio
async def test_discussion_group_points_to_its_channel() -> None:
    group = _dialog(
        GROUP_ID, "Комментарии", _channel(1000000002, "Комментарии", megagroup=True, has_link=True)
    )
    client = FakeDirectoryClient(main=[group], links={1000000002: 1000000001})
    directory = TelethonChatDirectory(client)

    (item,) = await directory.list_chats()

    assert item.kind == "group"
    assert item.discussion_of == CHANNEL_ID


@pytest.mark.asyncio
async def test_plain_supergroup_triggers_no_lookup() -> None:
    group = _dialog(GROUP_ID, "Чат", _channel(1000000002, "Чат", megagroup=True))
    client = FakeDirectoryClient(main=[group])

    (item,) = await TelethonChatDirectory(client).list_chats()

    assert item.discussion_of is None
    assert client.requests == []


@pytest.mark.asyncio
async def test_failed_lookup_leaves_the_link_empty_without_breaking_the_list() -> None:
    group = _dialog(
        GROUP_ID, "Комментарии", _channel(1000000002, "Комментарии", megagroup=True, has_link=True)
    )
    client = FakeDirectoryClient(main=[group], links={1000000002: 1000000001})
    client.fail_lookups = True

    (item,) = await TelethonChatDirectory(client).list_chats()

    assert item.title == "Комментарии"
    assert item.discussion_of is None


@pytest.mark.asyncio
async def test_discussion_of_resolves_the_marked_id_of_the_channel() -> None:
    client = FakeDirectoryClient(links={1000000002: 1000000001})
    directory = TelethonChatDirectory(client)

    assert await directory.discussion_of(GROUP_ID) == CHANNEL_ID


@pytest.mark.asyncio
async def test_broadcast_channel_is_not_a_discussion_group() -> None:
    # У вещательного канала linked_chat_id — его обсуждение, а не «его канал»:
    # принять его за связь значило бы открыть отключённый канал через его группу.
    client = FakeDirectoryClient(discussions={1000000001: 1000000002})
    directory = TelethonChatDirectory(client)

    assert await directory.discussion_of(CHANNEL_ID) is None
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_link_is_cached_for_an_hour_then_refreshed() -> None:
    clock = Clock()
    client = FakeDirectoryClient(links={1000000002: 1000000001})
    directory = TelethonChatDirectory(client, clock=clock)

    await directory.discussion_of(GROUP_ID)
    await directory.discussion_of(GROUP_ID)
    assert len(client.requests) == 1

    clock.now += LINK_CACHE_TTL_SECONDS + 1
    await directory.discussion_of(GROUP_ID)
    assert len(client.requests) == 2


@pytest.mark.asyncio
async def test_failed_lookup_is_raised_and_not_cached() -> None:
    client = FakeDirectoryClient(links={1000000002: 1000000001})
    client.fail_lookups = True
    directory = TelethonChatDirectory(client)

    with pytest.raises(RuntimeError):
        await directory.discussion_of(GROUP_ID)

    client.fail_lookups = False
    assert await directory.discussion_of(GROUP_ID) == CHANNEL_ID


@pytest.mark.asyncio
async def test_listing_is_cached_for_ten_seconds() -> None:
    clock = Clock()
    anna = _dialog(7, "Анна", _user(7, "Анна"))
    client = FakeDirectoryClient(main=[anna])
    directory = TelethonChatDirectory(client, clock=clock)

    first = await directory.list_chats()
    client.folders[0].append(_dialog(8, "Борис", _user(8, "Борис")))
    assert await directory.list_chats() == first

    clock.now += LIST_CACHE_TTL_SECONDS + 1
    assert [item.id for item in await directory.list_chats()] == [7, 8]
