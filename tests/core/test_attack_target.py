from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from telethon import errors, functions, types

from mimic42.core import attack_join
from mimic42.core.attack import parse_target_link
from mimic42.core.attack_join import JoinBlockedError, join_if_needed
from mimic42.core.attack_target import (
    AttackTarget,
    CommentsDisabledError,
    PostNotFoundError,
    TargetNotWritableError,
    refresh_slow_mode,
    resolve_target,
)

SOURCE_ID = 42
GROUP_ID = 555
ROOT_ID = 900


def make_channel(
    *,
    channel_id: int = GROUP_ID,
    access_hash: int = 888,
    broadcast: bool = False,
    megagroup: bool = True,
    has_link: bool = True,
    left: bool | None = None,
    join_to_send: bool | None = None,
    banned_rights: types.ChatBannedRights | None = None,
    slowmode_enabled: bool | None = None,
) -> types.Channel:
    return types.Channel(
        id=channel_id,
        title="Обсуждение",
        photo=types.ChatPhotoEmpty(),
        date=None,
        access_hash=access_hash,
        broadcast=broadcast,
        megagroup=megagroup,
        has_link=has_link,
        left=left,
        join_to_send=join_to_send,
        banned_rights=banned_rights,
        slowmode_enabled=slowmode_enabled,
    )


def make_message(
    message_id: int,
    *,
    peer: types.PeerChannel,
    grouped_id: int | None = None,
    post: bool = False,
    date: datetime | None = None,
    buttons: bool = False,
) -> types.Message:
    markup = None
    if buttons:
        markup = types.ReplyInlineMarkup(
            rows=[
                types.KeyboardButtonRow(
                    buttons=[types.KeyboardButtonCallback(text="Проверка", data=b"check")]
                )
            ]
        )
    return types.Message(
        id=message_id,
        peer_id=peer,
        date=date,
        message="текст",
        post=post,
        grouped_id=grouped_id,
        reply_markup=markup,
    )


def make_discussion(
    group: types.Channel,
    *,
    extra_ids: tuple[int, ...] = (),
    chats: list[Any] | None = None,
) -> types.messages.DiscussionMessage:
    messages: list[Any] = [
        make_message(message_id, peer=types.PeerChannel(group.id))
        for message_id in (ROOT_ID, *extra_ids)
    ]
    return types.messages.DiscussionMessage(
        messages=messages,
        unread_count=0,
        chats=list(chats) if chats is not None else [group],
        users=[],
    )


def make_full_channel(
    group: types.Channel,
    slowmode: int | None,
    next_send: datetime | None = None,
) -> types.messages.ChatFull:
    return types.messages.ChatFull(
        full_chat=types.ChannelFull(
            id=group.id,
            about="",
            read_inbox_max_id=0,
            read_outbox_max_id=0,
            unread_count=0,
            chat_photo=types.PhotoEmpty(id=0),
            notify_settings=types.PeerNotifySettings(),
            bot_info=[],
            pts=0,
            slowmode_seconds=slowmode,
            slowmode_next_send_date=next_send,
        ),
        chats=[group],
        users=[],
    )


def make_target(group: types.Channel) -> AttackTarget:
    return AttackTarget(group=group, root_reply_id=ROOT_ID, slowmode_seconds=None)


class FakeTelegram:
    def __init__(
        self,
        *,
        entity: types.Channel,
        group: types.Channel | None = None,
        posts: dict[int, Any] | None = None,
        discussion: types.messages.DiscussionMessage | None = None,
        slowmode: int | None = None,
        next_send: datetime | None = None,
        recent: list[Any] | None = None,
        join_error: Exception | None = None,
        inspection_error: Exception | None = None,
    ) -> None:
        self.entity = entity
        self.group = group
        self.posts = posts or {}
        self.discussion = discussion
        self.slowmode = slowmode
        self.next_send = next_send
        self.recent = recent or []
        self.join_error = join_error
        self.inspection_error = inspection_error
        self.entities: list[Any] = []
        self.requests: list[Any] = []
        self.message_queries: list[tuple[Any, Any, int | None]] = []

    async def get_entity(self, peer: Any) -> types.Channel:
        self.entities.append(peer)
        return self.entity

    async def get_messages(self, entity: Any, *, ids: Any = None, limit: int | None = None) -> Any:
        self.message_queries.append((entity, ids, limit))
        if limit is not None:
            if self.inspection_error is not None:
                raise self.inspection_error
            return self.recent
        if isinstance(ids, list):
            return [self.posts[message_id] for message_id in ids if message_id in self.posts]
        return self.posts.get(ids)

    async def __call__(self, request: Any) -> Any:
        self.requests.append(request)
        if isinstance(request, functions.messages.GetDiscussionMessageRequest):
            return self.discussion
        if isinstance(request, functions.channels.GetFullChannelRequest):
            assert self.group is not None
            return make_full_channel(self.group, self.slowmode, self.next_send)
        if isinstance(request, functions.channels.JoinChannelRequest):
            if self.join_error is not None:
                raise self.join_error
            return None
        raise AssertionError(f"Неожиданный запрос: {request!r}")


@pytest.fixture
def no_join_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(attack_join, "JOIN_SETTLE_SECONDS", 0.0)


async def test_public_post_resolves_the_discussion_root_and_slow_mode() -> None:
    source = make_channel(channel_id=SOURCE_ID, megagroup=False, has_link=False)
    group = make_channel(slowmode_enabled=True)
    fake = FakeTelegram(
        entity=source,
        group=group,
        posts={412: make_message(412, peer=types.PeerChannel(SOURCE_ID), post=True)},
        discussion=make_discussion(group, extra_ids=(950, 1001)),
        slowmode=30,
    )

    target = await resolve_target(fake, parse_target_link("https://t.me/example/412"))

    assert fake.entities == ["example"]
    assert target.group is group
    assert target.group.access_hash == 888
    assert target.root_reply_id == ROOT_ID
    assert target.slowmode_seconds == 30
    discussion_requests = [
        request
        for request in fake.requests
        if isinstance(request, functions.messages.GetDiscussionMessageRequest)
    ]
    assert [request.msg_id for request in discussion_requests] == [412]


async def test_private_link_resolves_the_numeric_channel_peer() -> None:
    source = make_channel(channel_id=123456789, megagroup=False, has_link=False)
    group = make_channel()
    fake = FakeTelegram(
        entity=source,
        group=group,
        posts={412: make_message(412, peer=types.PeerChannel(123456789), post=True)},
        discussion=make_discussion(group),
    )

    await resolve_target(fake, parse_target_link("https://t.me/c/123456789/412"))

    assert fake.entities == [-100123456789]


async def test_album_comment_targets_the_first_message() -> None:
    source = make_channel(channel_id=SOURCE_ID, megagroup=False, has_link=False)
    group = make_channel()
    posts = {
        403: make_message(403, peer=types.PeerChannel(SOURCE_ID), post=True),
        407: make_message(407, peer=types.PeerChannel(SOURCE_ID), post=True, grouped_id=111),
        408: make_message(408, peer=types.PeerChannel(SOURCE_ID), post=True, grouped_id=777),
        409: make_message(409, peer=types.PeerChannel(SOURCE_ID), post=True, grouped_id=777),
        410: make_message(410, peer=types.PeerChannel(SOURCE_ID), post=True, grouped_id=777),
        411: make_message(411, peer=types.PeerChannel(SOURCE_ID), post=True, grouped_id=777),
        412: make_message(412, peer=types.PeerChannel(SOURCE_ID), post=True, grouped_id=777),
    }
    fake = FakeTelegram(
        entity=source,
        group=group,
        posts=posts,
        discussion=make_discussion(group),
    )

    await resolve_target(fake, parse_target_link("https://t.me/example/412"))

    discussion_requests = [
        request
        for request in fake.requests
        if isinstance(request, functions.messages.GetDiscussionMessageRequest)
    ]
    assert [request.msg_id for request in discussion_requests] == [408]


async def test_a_missing_post_is_not_a_target() -> None:
    source = make_channel(channel_id=SOURCE_ID, megagroup=False, has_link=False)
    group = make_channel()
    fake = FakeTelegram(entity=source, group=group, discussion=make_discussion(group))

    with pytest.raises(PostNotFoundError):
        await resolve_target(fake, parse_target_link("https://t.me/example/412"))


async def test_an_empty_post_is_not_a_target() -> None:
    source = make_channel(channel_id=SOURCE_ID, megagroup=False, has_link=False)
    group = make_channel()
    fake = FakeTelegram(
        entity=source,
        group=group,
        posts={412: types.MessageEmpty(id=412, peer_id=types.PeerChannel(SOURCE_ID))},
        discussion=make_discussion(group),
    )

    with pytest.raises(PostNotFoundError):
        await resolve_target(fake, parse_target_link("https://t.me/example/412"))


async def test_a_group_message_is_not_a_channel_post() -> None:
    source = make_channel(channel_id=SOURCE_ID, megagroup=True)
    group = make_channel()
    fake = FakeTelegram(entity=source, group=group, discussion=make_discussion(group))

    with pytest.raises(PostNotFoundError):
        await resolve_target(fake, parse_target_link("https://t.me/c/42/412"))


async def test_a_post_without_discussion_cannot_be_attacked() -> None:
    source = make_channel(channel_id=SOURCE_ID, megagroup=False, has_link=False)
    fake = FakeTelegram(
        entity=source,
        group=make_channel(),
        posts={412: make_message(412, peer=types.PeerChannel(SOURCE_ID), post=True)},
        discussion=types.messages.DiscussionMessage(
            messages=[], unread_count=0, chats=[], users=[]
        ),
    )

    with pytest.raises(CommentsDisabledError):
        await resolve_target(fake, parse_target_link("https://t.me/example/412"))


async def test_a_discussion_without_a_linked_group_cannot_be_attacked() -> None:
    source = make_channel(channel_id=SOURCE_ID, megagroup=False, has_link=False)
    group = make_channel()
    fake = FakeTelegram(
        entity=source,
        group=group,
        posts={412: make_message(412, peer=types.PeerChannel(SOURCE_ID), post=True)},
        discussion=make_discussion(group, chats=[]),
    )

    with pytest.raises(CommentsDisabledError):
        await resolve_target(fake, parse_target_link("https://t.me/example/412"))


async def test_a_group_without_slow_mode_reports_none() -> None:
    source = make_channel(channel_id=SOURCE_ID, megagroup=False, has_link=False)
    group = make_channel()
    fake = FakeTelegram(
        entity=source,
        group=group,
        posts={412: make_message(412, peer=types.PeerChannel(SOURCE_ID), post=True)},
        discussion=make_discussion(group),
        slowmode=0,
    )

    target = await resolve_target(fake, parse_target_link("https://t.me/example/412"))

    assert target.slowmode_seconds is None
    assert target.slowmode_next_send_at is None


async def test_the_accounts_open_slow_mode_window_is_kept() -> None:
    source = make_channel(channel_id=SOURCE_ID, megagroup=False, has_link=False)
    group = make_channel(slowmode_enabled=True)
    open_at = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    fake = FakeTelegram(
        entity=source,
        group=group,
        posts={412: make_message(412, peer=types.PeerChannel(SOURCE_ID), post=True)},
        discussion=make_discussion(group),
        slowmode=300,
        next_send=open_at,
    )

    target = await resolve_target(fake, parse_target_link("https://t.me/example/412"))

    assert target.slowmode_seconds == 300
    assert target.slowmode_next_send_at == open_at


async def test_a_forever_banned_group_cannot_be_attacked() -> None:
    source = make_channel(channel_id=SOURCE_ID, megagroup=False, has_link=False)
    group = make_channel(banned_rights=types.ChatBannedRights(until_date=None, send_messages=True))
    fake = FakeTelegram(
        entity=source,
        group=group,
        posts={412: make_message(412, peer=types.PeerChannel(SOURCE_ID), post=True)},
        discussion=make_discussion(group),
    )

    with pytest.raises(TargetNotWritableError):
        await resolve_target(fake, parse_target_link("https://t.me/example/412"))


async def test_a_temporary_restriction_still_leaves_the_target_usable() -> None:
    source = make_channel(channel_id=SOURCE_ID, megagroup=False, has_link=False)
    until = datetime.now(UTC) + timedelta(hours=1)
    group = make_channel(banned_rights=types.ChatBannedRights(until_date=until, send_messages=True))
    fake = FakeTelegram(
        entity=source,
        group=group,
        posts={412: make_message(412, peer=types.PeerChannel(SOURCE_ID), post=True)},
        discussion=make_discussion(group),
    )

    target = await resolve_target(fake, parse_target_link("https://t.me/example/412"))

    assert target.group is group


async def test_a_group_that_requires_joining_is_still_a_valid_target() -> None:
    source = make_channel(channel_id=SOURCE_ID, megagroup=False, has_link=False)
    group = make_channel(left=True, join_to_send=True)
    fake = FakeTelegram(
        entity=source,
        group=group,
        posts={412: make_message(412, peer=types.PeerChannel(SOURCE_ID), post=True)},
        discussion=make_discussion(group),
    )

    target = await resolve_target(fake, parse_target_link("https://t.me/example/412"))

    assert target.group is group


async def test_refresh_slow_mode_keeps_the_group_and_the_root() -> None:
    group = make_channel()
    open_at = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    fake = FakeTelegram(entity=group, group=group, slowmode=60, next_send=open_at)

    refreshed = await refresh_slow_mode(
        fake, AttackTarget(group=group, root_reply_id=ROOT_ID, slowmode_seconds=30)
    )

    assert refreshed == AttackTarget(
        group=group,
        root_reply_id=ROOT_ID,
        slowmode_seconds=60,
        slowmode_next_send_at=open_at,
    )
    assert refreshed.group is group


async def test_an_available_group_is_not_joined() -> None:
    group = make_channel()
    fake = FakeTelegram(entity=group, group=group)

    await join_if_needed(fake, make_target(group))

    assert fake.requests == []
    assert fake.message_queries == []


async def test_a_group_that_needs_no_membership_is_not_joined() -> None:
    group = make_channel(left=True, join_to_send=False)
    fake = FakeTelegram(entity=group, group=group)

    await join_if_needed(fake, make_target(group))

    assert fake.requests == []


async def test_a_newcomer_joins_the_group(no_join_wait: None) -> None:
    group = make_channel(left=True, join_to_send=True)
    fake = FakeTelegram(entity=group, group=group)

    await join_if_needed(fake, make_target(group))

    joins = [
        request
        for request in fake.requests
        if isinstance(request, functions.channels.JoinChannelRequest)
    ]
    assert len(joins) == 1
    assert joins[0].channel is group


async def test_a_stale_left_flag_is_not_a_failure(no_join_wait: None) -> None:
    group = make_channel(left=True, join_to_send=True)
    fake = FakeTelegram(
        entity=group,
        group=group,
        join_error=errors.UserAlreadyParticipantError(request=None),
    )

    await join_if_needed(fake, make_target(group))


async def test_recent_buttons_after_joining_mean_a_verification_gate(no_join_wait: None) -> None:
    group = make_channel(left=True, join_to_send=True)
    fake = FakeTelegram(
        entity=group,
        group=group,
        recent=[
            make_message(
                ROOT_ID + 1,
                peer=types.PeerChannel(GROUP_ID),
                date=datetime.now(UTC),
                buttons=True,
            )
        ],
    )

    with pytest.raises(JoinBlockedError):
        await join_if_needed(fake, make_target(group))


async def test_old_buttons_are_history_not_a_verification_gate(no_join_wait: None) -> None:
    group = make_channel(left=True, join_to_send=True)
    fake = FakeTelegram(
        entity=group,
        group=group,
        recent=[
            make_message(
                ROOT_ID + 1,
                peer=types.PeerChannel(GROUP_ID),
                date=datetime.now(UTC) - timedelta(minutes=5),
                buttons=True,
            )
        ],
    )

    await join_if_needed(fake, make_target(group))


@pytest.mark.parametrize(
    "error",
    [
        errors.InviteRequestSentError(request=None),
        errors.ChatWriteForbiddenError(request=None),
        errors.UserBannedInChannelError(request=None),
        errors.ChannelPrivateError(request=None),
        errors.ChatAdminRequiredError(request=None),
    ],
)
async def test_join_refusals_block_the_mimic(error: Exception) -> None:
    group = make_channel(left=True, join_to_send=True)
    fake = FakeTelegram(entity=group, group=group, join_error=error)

    with pytest.raises(JoinBlockedError):
        await join_if_needed(fake, make_target(group))


async def test_a_group_that_disappears_after_joining_blocks_the_mimic(
    no_join_wait: None,
) -> None:
    group = make_channel(left=True, join_to_send=True)
    fake = FakeTelegram(
        entity=group,
        group=group,
        inspection_error=errors.ChannelPrivateError(request=None),
    )

    with pytest.raises(JoinBlockedError):
        await join_if_needed(fake, make_target(group))
