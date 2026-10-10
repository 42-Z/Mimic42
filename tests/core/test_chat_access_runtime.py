"""Отключённые чаты не получают ходов, первых комментариев и таймеров."""

from __future__ import annotations

from typing import Any

import pytest

from mimic42.core.agent_runtime import ChatListUnavailableError, MimicAgentRuntime
from mimic42.core.chat_access import ChatAccess, ChatDisabledError
from mimic42.core.chat_directory import ChatDirectory, ChatItem
from mimic42.core.first_comment import FirstCommentSettings, FirstCommentVariant
from mimic42.testing.telegram import FakeTelegramClient
from tests.core.test_agent_runtime import FakeLangChainAgent, make_config
from tests.core.test_warmup_runtime import StubGate

CHANNEL = -1001111111111
GROUP = -1002222222222


def _access(disabled: set[int], links: dict[int, int] | None = None) -> ChatAccess:
    async def discussion_of(chat_id: int) -> int | None:
        return (links or {}).get(chat_id)

    return ChatAccess(frozenset(disabled), discussion_of)


def _runtime(
    access: ChatAccess | None, directory: ChatDirectory | None = None
) -> tuple[MimicAgentRuntime, FakeTelegramClient, FakeLangChainAgent]:
    telegram = FakeTelegramClient()
    agent = FakeLangChainAgent(response="ответ")
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram,
        langchain_agent=agent,
        chat_access=access,
        chat_directory=directory,
    )
    return runtime, telegram, agent


@pytest.mark.asyncio
async def test_incoming_from_a_disabled_chat_starts_no_turn() -> None:
    runtime, telegram, agent = _runtime(_access({99}))
    await runtime.start()

    await telegram.account.deliver(chat_id=99, text="привет")

    assert agent.inputs == []
    assert telegram.sent_messages == []


@pytest.mark.asyncio
async def test_refused_incoming_leaves_no_trace_in_the_activity_feed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, telegram, _ = _runtime(_access({99}))
    recorded: list[str] = []

    async def record_event(**kwargs: Any) -> None:
        recorded.append(kwargs["event_type"])

    monkeypatch.setattr(runtime, "_record_event", record_event)
    await runtime.start()
    recorded.clear()

    await telegram.account.deliver(chat_id=99, text="привет")

    assert recorded == []


@pytest.mark.asyncio
async def test_other_chats_are_answered_as_before() -> None:
    runtime, telegram, agent = _runtime(_access({99}))
    await runtime.start()

    await telegram.account.deliver(chat_id=100, text="привет")

    assert len(agent.inputs) == 1
    assert telegram.sent_messages == [("100", "ответ")]


@pytest.mark.asyncio
async def test_comments_of_an_enabled_channel_are_answered_even_if_the_group_is_disabled() -> None:
    runtime, telegram, agent = _runtime(_access({GROUP}, {GROUP: CHANNEL}))
    await runtime.start()

    await telegram.account.deliver(chat_id=GROUP, text="комментарий")

    assert len(agent.inputs) == 1


@pytest.mark.asyncio
async def test_comments_of_a_disabled_channel_stay_silent() -> None:
    runtime, telegram, agent = _runtime(_access({GROUP, CHANNEL}, {GROUP: CHANNEL}))
    await runtime.start()

    await telegram.account.deliver(chat_id=GROUP, text="комментарий")

    assert agent.inputs == []


@pytest.mark.asyncio
async def test_dialog_with_another_mimic_ignores_the_disabled_list() -> None:
    runtime, telegram, agent = _runtime(_access({555}))
    runtime.set_warmup_gate(StubGate(True))
    await runtime.start()

    await telegram.account.deliver(chat_id=555, text="привет", sender_id=555)

    assert len(agent.inputs) == 1


@pytest.mark.asyncio
async def test_ordinary_person_in_a_disabled_chat_is_still_ignored_with_a_warmup_gate() -> None:
    runtime, telegram, agent = _runtime(_access({555}))
    runtime.set_warmup_gate(StubGate(None))
    await runtime.start()

    await telegram.account.deliver(chat_id=555, text="привет", sender_id=555)

    assert agent.inputs == []


def _comment_runtime(access: ChatAccess) -> tuple[MimicAgentRuntime, FakeTelegramClient]:
    runtime, telegram, _ = _runtime(access)
    runtime.config.first_comment = FirstCommentSettings(
        enabled=True, variants=[FirstCommentVariant(text="Первый!")]
    )
    return runtime, telegram


@pytest.mark.asyncio
async def test_disabled_channel_gets_no_first_comment() -> None:
    runtime, telegram = _comment_runtime(_access({CHANNEL}))
    await runtime.start()

    await telegram.account.deliver_post(chat_id=CHANNEL, text="Новый пост")

    assert [m for m in telegram.account.sent if "comment_to" in m.kwargs] == []


@pytest.mark.asyncio
async def test_other_channels_still_get_the_first_comment() -> None:
    runtime, telegram = _comment_runtime(_access({GROUP}))
    await runtime.start()

    await telegram.account.deliver_post(chat_id=CHANNEL, text="Новый пост")

    assert len([m for m in telegram.account.sent if "comment_to" in m.kwargs]) == 1


@pytest.mark.asyncio
async def test_peer_check_resolves_the_peer_through_the_client() -> None:
    runtime, telegram, _ = _runtime(_access({CHANNEL}))

    async def get_peer_id(peer: object, add_mark: bool = True) -> int:
        if peer == "@news":
            return CHANNEL
        assert isinstance(peer, int)
        return peer

    telegram.get_peer_id = get_peer_id  # ty: ignore[unresolved-attribute]

    with pytest.raises(ChatDisabledError):
        await runtime._ensure_peer_allowed("@news")
    with pytest.raises(ChatDisabledError):
        await runtime._ensure_peer_allowed(str(CHANNEL))
    await runtime._ensure_peer_allowed("-1009999999999")


@pytest.mark.asyncio
async def test_peer_check_fails_closed_when_the_peer_cannot_be_resolved() -> None:
    runtime, telegram, _ = _runtime(_access({CHANNEL}))

    async def get_peer_id(peer: object, add_mark: bool = True) -> int:
        raise ValueError("Cannot find any entity")

    telegram.get_peer_id = get_peer_id  # ty: ignore[unresolved-attribute]

    with pytest.raises(ValueError):
        await runtime._ensure_peer_allowed("@unknown")


@pytest.mark.asyncio
async def test_peer_check_refuses_when_the_client_cannot_resolve_ids() -> None:
    runtime, _, _ = _runtime(_access({CHANNEL}))

    with pytest.raises(ChatDisabledError):
        await runtime._ensure_peer_allowed("@news")


@pytest.mark.asyncio
async def test_peer_check_without_a_rule_resolves_nothing() -> None:
    runtime, _, _ = _runtime(None)

    await runtime._ensure_peer_allowed("@anything")


class _StubDirectory:
    async def list_chats(self) -> list[ChatItem]:
        return [ChatItem(id=7, title="Анна", kind="private")]

    async def discussion_of(self, chat_id: int) -> int | None:
        return None


@pytest.mark.asyncio
async def test_list_chats_needs_a_running_agent() -> None:
    runtime, _, _ = _runtime(None, _StubDirectory())

    with pytest.raises(ChatListUnavailableError):
        await runtime.list_chats()

    await runtime.start()
    assert [chat.id for chat in await runtime.list_chats()] == [7]

    await runtime.stop()
    with pytest.raises(ChatListUnavailableError):
        await runtime.list_chats()


@pytest.mark.asyncio
async def test_list_chats_without_a_directory_is_unavailable() -> None:
    runtime, _, _ = _runtime(None, None)
    await runtime.start()

    with pytest.raises(ChatListUnavailableError):
        await runtime.list_chats()
