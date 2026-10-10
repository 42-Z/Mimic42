"""Ответы инструментов объясняют, что значит ошибка Telegram и что делать дальше."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from telethon import errors, functions, types

from mimic42.integrations.telegram_tools import TelegramToolbox
from tests.integrations.test_telegram_tools import FakeTelethonClient


class FailingSendClient(FakeTelethonClient):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error
        self.attempts = 0

    async def send_message(self, entity: Any, message: str, **kwargs: Any) -> object:
        self.attempts += 1
        raise self._error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (errors.UserBannedInChannelError(request=None), "USER_BANNED_IN_CHANNEL"),
        (errors.ChatGuestSendForbiddenError(request=None), "join_channel_discussion"),
        (errors.ChatWriteForbiddenError(request=None), "get_messages"),
        (errors.UserNotParticipantError(request=None), "join_channel"),
        (errors.PeerFloodError(request=None), "PEER_FLOOD"),
        (errors.MsgIdInvalidError(request=None), "comment_to_msg_id"),
    ],
    ids=["banned", "guest", "write_forbidden", "not_participant", "peer_flood", "msg_id"],
)
async def test_send_failure_carries_a_hint_for_the_model(error: Exception, expected: str) -> None:
    toolbox = TelegramToolbox(cast(Any, FailingSendClient(error)))

    result = await toolbox.send_text_message("12345", "привет", comment_to_msg_id=5)

    assert result["success"] is False
    assert result["error_code"] == type(error).__name__
    assert expected in result["hint"]


@pytest.mark.asyncio
async def test_ban_hint_does_not_blame_the_agent_settings_or_a_specific_chat() -> None:
    toolbox = TelegramToolbox(
        cast(Any, FailingSendClient(errors.UserBannedInChannelError(request=None)))
    )

    result = await toolbox.send_text_message("12345", "привет")

    hint = result["hint"]
    assert "не настройка агента" in hint
    assert "@SpamBot" in hint
    assert "не утверждай" in hint


DATE = datetime(2026, 1, 1, tzinfo=UTC)
NEWS = types.Channel(
    id=1, title="Новости", photo=types.ChatPhotoEmpty(), date=DATE, access_hash=1, broadcast=True
)


def _discussion(*, joined: bool, join_to_send: bool) -> Any:
    return types.Channel(
        id=2,
        title="Обсуждение",
        photo=types.ChatPhotoEmpty(),
        date=DATE,
        access_hash=1,
        megagroup=True,
        left=None if joined else True,
        join_to_send=join_to_send or None,
    )


class NewsClient(FakeTelethonClient):
    """Канал «Новости» с обсуждением; ``linked`` — что вернёт GetFullChannel."""

    def __init__(self, linked: Any | None, *, already_participant: bool = False) -> None:
        super().__init__()
        self._linked = linked
        self._already_participant = already_participant

    async def get_entity(self, peer: Any) -> Any:
        return self._linked if peer == 2 else NEWS

    async def __call__(self, request: object) -> Any:
        if isinstance(request, functions.channels.GetFullChannelRequest):
            full = SimpleNamespace(
                about="",
                participants_count=10,
                admins_count=1,
                linked_chat_id=2 if self._linked is not None else None,
            )
            return SimpleNamespace(full_chat=full, chats=[NEWS, self._linked], users=[])
        if isinstance(request, functions.channels.JoinChannelRequest) and self._already_participant:
            raise errors.UserAlreadyParticipantError(request=None)
        return await super().__call__(request)


@pytest.mark.asyncio
async def test_channel_info_tells_whether_comments_need_joining() -> None:
    client = NewsClient(_discussion(joined=False, join_to_send=True))

    info = await TelegramToolbox(cast(Any, client)).get_chat_info("news")

    assert info["has_discussion"] is True
    assert info["discussion"] == {
        "id": -1000000000002,
        "title": "Обсуждение",
        "joined": False,
        "join_required_to_comment": True,
    }


@pytest.mark.asyncio
async def test_channel_without_discussion_is_reported_as_such() -> None:
    info = await TelegramToolbox(cast(Any, NewsClient(None))).get_chat_info("news")

    assert info["has_discussion"] is False
    assert "discussion" not in info


@pytest.mark.asyncio
async def test_joining_the_discussion_points_to_the_comment_call() -> None:
    client = NewsClient(_discussion(joined=False, join_to_send=True))

    result = await TelegramToolbox(cast(Any, client)).join_channel_discussion("news")

    assert result["success"] is True
    assert result["already_joined"] is False
    assert "comment_to_msg_id" in result["hint"]


@pytest.mark.asyncio
async def test_joining_a_discussion_the_agent_is_already_in_is_not_a_failure() -> None:
    client = NewsClient(_discussion(joined=True, join_to_send=True), already_participant=True)

    result = await TelegramToolbox(cast(Any, client)).join_channel_discussion("news")

    assert result["success"] is True
    assert result["already_joined"] is True


@pytest.mark.asyncio
async def test_repeat_after_a_ban_is_answered_without_asking_telegram_again() -> None:
    client = FailingSendClient(errors.UserBannedInChannelError(request=None))
    toolbox = TelegramToolbox(cast(Any, client))

    first = await toolbox.send_text_message("strimrs", "привет", comment_to_msg_id=5)
    again = await toolbox.send_text_message("@strimrs", "ещё раз", comment_to_msg_id=5)

    assert first["error_code"] == "UserBannedInChannelError"
    assert again["success"] is False
    assert again["error_code"] == "SendRefusedRecently"
    assert again["retry_after_seconds"] > 0
    assert "USER_BANNED_IN_CHANNEL" not in again["error"]
    assert "UserBannedInChannelError" in again["error"]
    assert client.attempts == 1


@pytest.mark.asyncio
async def test_joining_the_discussion_allows_another_attempt() -> None:
    client = FailingSendClient(errors.UserBannedInChannelError(request=None))
    toolbox = TelegramToolbox(cast(Any, client))

    await toolbox.send_text_message("group", "привет", comment_to_msg_id=5)
    assert (await toolbox.join_channel_discussion("group"))["success"] is True
    again = await toolbox.send_text_message("group", "привет", comment_to_msg_id=5)

    assert again["error_code"] == "UserBannedInChannelError"
    assert client.attempts == 2


@pytest.mark.asyncio
async def test_a_ban_in_one_chat_does_not_block_other_chats() -> None:
    client = FailingSendClient(errors.UserBannedInChannelError(request=None))
    toolbox = TelegramToolbox(cast(Any, client))

    await toolbox.send_text_message("strimrs", "привет")
    other = await toolbox.send_text_message("another", "привет")

    assert other["error_code"] == "UserBannedInChannelError"
    assert client.attempts == 2


@pytest.mark.asyncio
async def test_the_refusal_expires() -> None:
    client = FailingSendClient(errors.UserBannedInChannelError(request=None))
    toolbox = TelegramToolbox(cast(Any, client))

    await toolbox.send_text_message("strimrs", "привет")
    code = toolbox._refusals["strimrs"][1]
    toolbox._refusals["strimrs"] = (time.monotonic() - 1, code)
    again = await toolbox.send_text_message("strimrs", "привет")

    assert again["error_code"] == "UserBannedInChannelError"
    assert client.attempts == 2


@pytest.mark.asyncio
async def test_recoverable_refusals_are_not_remembered() -> None:
    client = FailingSendClient(errors.ChatGuestSendForbiddenError(request=None))
    toolbox = TelegramToolbox(cast(Any, client))

    await toolbox.send_text_message("strimrs", "привет", comment_to_msg_id=5)
    again = await toolbox.send_text_message("strimrs", "после вступления", comment_to_msg_id=5)

    assert again["error_code"] == "ChatGuestSendForbiddenError"
    assert client.attempts == 2


SPAMBOT_ID = 178220800


class SpamBotByIdClient(FailingSendClient):
    """Клиент, который уже знает id @SpamBot и разрешает в него любую запись ссылки."""

    spambot_user_id = SPAMBOT_ID

    async def get_input_entity(self, peer: Any) -> Any:
        user_id = SPAMBOT_ID if peer in (SPAMBOT_ID, "telegram_alias") else 555
        return types.InputPeerUser(user_id=user_id, access_hash=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("peer", ["178220800", "telegram_alias"])
async def test_the_spam_bot_is_found_by_its_id_whatever_the_link_looks_like(peer: str) -> None:
    client = SpamBotByIdClient(RuntimeError("до Telegram не должно дойти"))
    toolbox = TelegramToolbox(cast(Any, client))

    sent = await toolbox.send_text_message(peer, "Это ошибка")

    assert sent["error_code"] == "OffLimitsBotError"
    assert client.attempts == 0


@pytest.mark.asyncio
async def test_other_users_are_not_taken_for_the_spam_bot() -> None:
    client = SpamBotByIdClient(RuntimeError("сбой"))
    toolbox = TelegramToolbox(cast(Any, client))

    result = await toolbox.send_text_message("555", "привет")

    assert result["error_code"] == "RuntimeError"
    assert client.attempts == 1


def test_off_limits_entity_matches_users_and_input_peers_only() -> None:
    from mimic42.integrations.telegram_tools import _is_off_limits_entity

    assert _is_off_limits_entity(types.User(id=SPAMBOT_ID), SPAMBOT_ID)
    assert _is_off_limits_entity(types.InputPeerUser(SPAMBOT_ID, 1), SPAMBOT_ID)
    assert not _is_off_limits_entity(types.User(id=1), SPAMBOT_ID)
    assert not _is_off_limits_entity(types.InputPeerChannel(SPAMBOT_ID, 1), SPAMBOT_ID)
    assert not _is_off_limits_entity(types.User(id=SPAMBOT_ID), None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "peer",
    [
        "@SpamBot",
        "SpamBot",
        "spambot",
        "  @SpamBot  ",
        "https://t.me/SpamBot",
        "t.me/spambot/",
        "telegram.me/SpamBot",
        "Диалог#@SpamBot",
    ],
)
async def test_the_spam_bot_is_off_limits_for_the_agent(peer: str) -> None:
    client = FailingSendClient(RuntimeError("до Telegram не должно дойти"))
    toolbox = TelegramToolbox(cast(Any, client))

    sent = await toolbox.send_text_message(peer, "Это ошибка")
    started = await toolbox.start_bot(peer)
    history = await toolbox.get_messages(peer)

    assert sent["error_code"] == "OffLimitsBotError"
    assert started["error_code"] == "OffLimitsBotError"
    assert history[0]["error_code"] == "OffLimitsBotError"
    assert "владелец" in sent["error"]
    assert client.attempts == 0


@pytest.mark.asyncio
async def test_no_timers_for_the_spam_bot() -> None:
    session_factory = MagicMock()
    toolbox = TelegramToolbox(
        cast(Any, FailingSendClient(RuntimeError("нет"))),
        agent_id=MagicMock(),
        session_factory=session_factory,
    )

    result = await toolbox.set_wakeup_timer("@SpamBot", 1800, "Проверить апелляцию")

    assert result["error_code"] == "OffLimitsBotError"
    session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_other_bots_stay_available() -> None:
    client = FailingSendClient(RuntimeError("сбой"))
    toolbox = TelegramToolbox(cast(Any, client))

    result = await toolbox.send_text_message("@BotFather", "/help")

    assert result["error_code"] == "RuntimeError"
    assert client.attempts == 1


@pytest.mark.asyncio
async def test_unknown_errors_have_no_hint() -> None:
    toolbox = TelegramToolbox(cast(Any, FailingSendClient(RuntimeError("сбой"))))

    result = await toolbox.send_text_message("12345", "привет")

    assert result["success"] is False
    assert "hint" not in result
