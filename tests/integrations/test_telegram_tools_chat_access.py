"""Инструменты Telegram не работают с чатами, отключёнными в настройках агента."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from telethon import functions, types, utils

from mimic42.core.chat_access import ChatAccess
from mimic42.integrations.telegram_tools import TelegramToolbox
from tests.integrations.test_telegram_tools import FakeTelethonClient

ALLOWED = -1000000000001
BLOCKED = -1000000000002
GROUP = -1000000000003
BLOCKED_USER = 42
OWN_ID = 777
ALIASES = {
    "@allowed": ALLOWED,
    "@blocked": BLOCKED,
    "@group": GROUP,
    "@blocked_user": BLOCKED_USER,
}
DATE = datetime(2026, 1, 1, tzinfo=UTC)


def _input_peer(marked_id: int) -> Any:
    real_id, kind = utils.resolve_id(marked_id)
    if kind is types.PeerChannel:
        return types.InputPeerChannel(channel_id=real_id, access_hash=1)
    return types.InputPeerUser(user_id=real_id, access_hash=1)


def _entity(marked_id: int) -> Any:
    real_id, kind = utils.resolve_id(marked_id)
    if kind is types.PeerChannel:
        # Только у группы обсуждения признак связи True, как у разобранной сущности Telegram.
        return types.Channel(
            id=real_id,
            title="Чат",
            photo=types.ChatPhotoEmpty(),
            date=DATE,
            access_hash=1,
            has_link=(marked_id == GROUP),
        )
    return types.User(id=real_id, first_name="Ivan", access_hash=1)


class AccessClient(FakeTelethonClient):
    """Клиент, у которого @-имена и числа разрешаются в пиров с настоящими ID."""

    def __init__(self) -> None:
        super().__init__()
        self.dialog_list: list[Any] = []

    @staticmethod
    def _marked(peer: Any) -> int:
        return peer if isinstance(peer, int) else ALIASES[peer]

    @staticmethod
    def _known(peer: Any) -> bool:
        return isinstance(peer, int) or peer in ALIASES

    async def __call__(self, request: object) -> Any:
        if isinstance(request, functions.messages.GetCommonChatsRequest):
            self.requests.append(request)
            # Настоящий канал: ID берётся из сущности, как у ответа Telegram.
            return SimpleNamespace(chats=[_entity(-1000000000789)])
        return await super().__call__(request)

    async def get_input_entity(self, peer: Any) -> Any:
        if peer == "me":
            return types.InputPeerSelf()
        if self._known(peer):
            return _input_peer(self._marked(peer))
        return await super().get_input_entity(peer)

    async def get_entity(self, peer: Any) -> Any:
        if peer == "me":
            return types.User(id=OWN_ID, first_name="Я", is_self=True, access_hash=1)
        if self._known(peer):
            return _entity(self._marked(peer))
        return await super().get_entity(peer)

    async def get_peer_id(self, peer: Any, add_mark: bool = True) -> int:
        # Как в документации Telethon: 'me' — ID самого аккаунта.
        if peer == "me":
            return OWN_ID
        return utils.get_peer_id(peer)

    def iter_dialogs(self, limit: int | None = None, **kwargs: Any) -> Any:
        assert limit is None
        dialogs = list(self.dialog_list)

        async def gen() -> Any:
            for dialog in dialogs:
                yield dialog

        return gen()


def _access(disabled: set[int], links: dict[int, int] | None = None) -> ChatAccess:
    async def discussion_of(chat_id: int) -> int | None:
        return (links or {}).get(chat_id)

    return ChatAccess(frozenset(disabled), discussion_of)


def _toolbox(
    disabled: set[int],
    links: dict[int, int] | None = None,
    **kwargs: Any,
) -> tuple[TelegramToolbox, AccessClient]:
    client = AccessClient()
    toolbox = TelegramToolbox(cast(Any, client), chat_access=_access(disabled, links), **kwargs)
    return toolbox, client


def _dialog(marked_id: int, title: str) -> Any:
    entity = SimpleNamespace(username=None, is_self=False, has_link=False)
    return SimpleNamespace(id=marked_id, title=title, unread_count=0, entity=entity)


def _failure(result: Any) -> dict[str, Any]:
    """Результат инструмента как словарь: у инструментов-списков отказ — первый элемент."""
    return result[0] if isinstance(result, list) and result else result


def _refused(result: Any) -> bool:
    item = _failure(result)
    return item.get("success") is False and item.get("error_code") == "ChatDisabledError"


Call = Callable[[TelegramToolbox], Awaitable[Any]]

REFUSED_CALLS: dict[str, Call] = {
    "send_text_message": lambda tb: tb.send_text_message("@blocked", "привет"),
    "numeric_peer_string": lambda tb: tb.send_text_message(str(BLOCKED), "привет"),
    "private_chat": lambda tb: tb.send_text_message("@blocked_user", "привет"),
    "get_messages": lambda tb: tb.get_messages("@blocked"),
    "search_messages": lambda tb: tb.search_messages("@blocked", "q"),
    "forward_to_blocked": lambda tb: tb.forward_messages("@allowed", "@blocked", [1]),
    "forward_from_blocked": lambda tb: tb.forward_messages("@blocked", "@allowed", [1]),
    "invite_to_channel": lambda tb: tb.invite_to_channel("@blocked", ["username"]),
    "kick_chat_member": lambda tb: tb.kick_chat_member("@blocked", "username"),
    "ban_chat_member": lambda tb: tb.ban_chat_member("@blocked", "username"),
    "archive_dialogs": lambda tb: tb.archive_dialogs(["@allowed", "@blocked"]),
    "start_bot": lambda tb: tb.start_bot("@blocked_user"),
    "query_inline_bot_peer": lambda tb: tb.query_inline_bot("username", "q", peer="@blocked"),
    "join_channel": lambda tb: tb.join_channel("@blocked"),
    "delete_channel": lambda tb: tb.delete_channel("@blocked"),
    "get_discussion_messages": lambda tb: tb.get_discussion_messages("@blocked", 1),
    "get_profile_of_a_chat": lambda tb: tb.get_profile("@blocked"),
    # send_file сам подменяет тексты ошибок на «Не удалось отправить медиа»: отказ — исключение.
    "send_file": lambda tb: tb.send_file("@blocked", "https://example.com/a.png"),
    "chat_folder": lambda tb: tb.create_or_update_chat_folder(
        2, "Работа", include_peers=["@allowed", "@blocked"]
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(REFUSED_CALLS))
async def test_disabled_chat_is_refused_with_its_own_error(name: str) -> None:
    toolbox, client = _toolbox({BLOCKED, BLOCKED_USER})

    result = await REFUSED_CALLS[name](toolbox)

    assert _refused(result), f"{name}: {result}"
    assert "отключён в настройках агента" in _failure(result)["error"]
    assert [call for call in client.calls if call[0] in ("send_message", "send_file")] == []
    assert not [r for r in client.requests if type(r).__name__ == "UpdateDialogFilterRequest"]


@pytest.mark.asyncio
async def test_archive_changes_nothing_when_one_of_the_chats_is_disabled() -> None:
    toolbox, client = _toolbox({BLOCKED})

    await toolbox.archive_dialogs(["@allowed", "@blocked"])

    assert not [r for r in client.requests if type(r).__name__ == "EditPeerFoldersRequest"]


@pytest.mark.asyncio
async def test_admin_tools_hand_telethon_the_checked_entity_not_the_raw_string() -> None:
    """Проверенный и действующий чат — один объект: строку Telethon разобрал бы заново."""
    toolbox, client = _toolbox({BLOCKED})

    await toolbox.kick_chat_member("@allowed", "username")
    await toolbox.ban_chat_member("@allowed", "username")
    await toolbox.restrict_chat_member("@allowed", "username")
    await toolbox.promote_chat_member("@allowed", "username")

    handed = [call[1]["entity"] for call in client.calls if call[0] != "get_input_entity"]
    assert len(handed) == 4
    assert all(isinstance(entity, types.InputPeerChannel) for entity in handed)


@pytest.mark.asyncio
async def test_admin_tools_keep_the_raw_peer_without_an_access_rule() -> None:
    client = AccessClient()
    toolbox = TelegramToolbox(cast(Any, client))

    await toolbox.kick_chat_member("@allowed", "username")

    (entity,) = [call[1]["entity"] for call in client.calls if call[0] == "kick_participant"]
    assert entity == "@allowed"


@pytest.mark.asyncio
async def test_enabled_chat_keeps_working() -> None:
    toolbox, client = _toolbox({BLOCKED})

    result = await toolbox.send_text_message("@allowed", "привет")

    assert result["success"] is True
    assert [call[0] for call in client.calls].count("send_message") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        # as_input=False: разрешение в полную сущность (User с is_self).
        lambda tb: tb.get_messages("me"),
        # as_input=True: InputPeerSelf, для которого запрашивается get_peer_id('me').
        lambda tb: tb.send_text_message("me", "заметка"),
    ],
    ids=["entity", "input_peer_self"],
)
async def test_saved_messages_are_checked_by_the_own_id(call: Call) -> None:
    toolbox, _ = _toolbox({OWN_ID})

    assert _refused(await call(toolbox))


@pytest.mark.asyncio
async def test_people_are_not_chats_for_profile_and_contacts() -> None:
    toolbox, _ = _toolbox({BLOCKED_USER})

    result = await toolbox.get_profile("username")

    assert result.get("error_code") != "ChatDisabledError"


@pytest.mark.asyncio
async def test_discussion_group_of_an_enabled_channel_is_readable() -> None:
    toolbox, _ = _toolbox({GROUP}, links={GROUP: ALLOWED})

    result = await toolbox.get_messages("@group")

    assert not _refused(result)


@pytest.mark.asyncio
async def test_discussion_group_of_a_disabled_channel_is_refused() -> None:
    toolbox, _ = _toolbox({GROUP, ALLOWED}, links={GROUP: ALLOWED})

    assert _refused(await toolbox.get_messages("@group"))


@pytest.mark.asyncio
async def test_invite_link_join_is_not_checked() -> None:
    toolbox, _ = _toolbox({BLOCKED})

    result = await toolbox.join_channel("https://t.me/+AbCdEf123")

    assert result["success"] is True


@pytest.mark.asyncio
async def test_get_dialogs_hides_disabled_chats_and_still_fills_the_limit() -> None:
    toolbox, client = _toolbox({BLOCKED})
    client.dialog_list = [
        _dialog(BLOCKED, "Закрытый"),
        _dialog(ALLOWED, "Открытый"),
        _dialog(BLOCKED_USER, "Анна"),
    ]

    result = await toolbox.get_dialogs(limit=2)

    assert [d["id"] for d in result] == [ALLOWED, BLOCKED_USER]


@pytest.mark.asyncio
async def test_chat_folders_hide_disabled_peers() -> None:
    # Подделка отдаёт папку: закреплён user 123, включён channel 456.
    toolbox, _ = _toolbox({-1000000000456})

    folders = await toolbox.get_chat_folders()

    custom = next(f for f in folders if f["id"] == 2)
    assert custom["pinned_peers"] == [{"type": "user", "id": 123}]
    assert custom["include_peers"] == []


@pytest.mark.asyncio
async def test_common_chats_hide_disabled_chats() -> None:
    # AccessClient отдаёт общий канал с ID 789.
    toolbox, _ = _toolbox({-1000000000789})

    assert await toolbox.get_common_chats("username") == []


@pytest.mark.asyncio
async def test_wakeup_timer_for_a_disabled_chat_is_refused_before_touching_the_database() -> None:
    session_factory = MagicMock()
    toolbox, _ = _toolbox({BLOCKED}, agent_id=MagicMock(), session_factory=session_factory)

    result = await toolbox.set_wakeup_timer("@blocked", 60, "напомнить")

    assert _refused(result)
    session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_toolbox_without_an_access_rule_does_not_resolve_ids() -> None:
    client = AccessClient()
    toolbox = TelegramToolbox(cast(Any, client))

    result = await toolbox.send_text_message("@blocked", "привет")

    assert result["success"] is True


CHAT_PARAMS = {
    "peer",
    "peers",
    "from_peer",
    "to_peer",
    "channel",
    "broadcast",
    "group",
    "pinned_peers",
    "include_peers",
    "exclude_peers",
}
# Параметр peer здесь — человек, а не чат: результат фильтруется или не проверяется.
# get_profile проверяет доступ сам, когда peer оказывается чатом (ветка не-пользователя).
PEOPLE_TOOLS = {"get_profile", "delete_contact", "get_common_chats"}


def test_every_chat_addressed_tool_goes_through_the_access_guard() -> None:
    """Новый инструмент с чат-параметром не должен обойти настройку «Чаты и каналы»."""
    unguarded: list[str] = []
    for name, method in inspect.getmembers(TelegramToolbox, inspect.iscoroutinefunction):
        if name.startswith("_") or name in PEOPLE_TOOLS:
            continue
        if not CHAT_PARAMS & set(inspect.signature(method).parameters):
            continue
        source = inspect.getsource(method)
        guards = ("_resolve_chat(", "_guard_chat(", "_chat_target(")
        if not any(guard in source for guard in guards):
            unguarded.append(name)
    assert unguarded == []
