"""Разрешение цели атаки: канал, пост, обсуждение и slow mode.

Цель разрешается на клиенте конкретного мимика. Приватная группа приходит с
``access_hash`` только в ответе ``GetDiscussionMessageRequest`` того клиента,
который его сделал, поэтому результат не кэшируется между мимиками и не
попадает в базу: там остаются только публичные id для интерфейса.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from telethon import functions, types

from mimic42.core.attack import TargetRef
from mimic42.core.send_window import window_from_chat

MAX_ALBUM_ITEMS = 10


class AttackTargetError(RuntimeError):
    """Цель атаки не разрешается в пост с открытым для комментариев обсуждением."""


class PostNotFoundError(AttackTargetError):
    """Поста канала по ссылке нет или ссылка ведёт не на пост канала."""


class CommentsDisabledError(AttackTargetError):
    """У поста нет обсуждения или комментарии в нём закрыты."""


class TargetNotWritableError(AttackTargetError):
    """В группу обсуждения нельзя писать, и вступление этого не изменит."""


@dataclass(frozen=True)
class AttackTarget:
    """Разрешённая цель одного мимика: группа обсуждения и корень треда.

    ``group`` это сущность из ответа Telegram, а не голый id: в ней лежит
    ``access_hash``, полученный клиентом мимика.
    """

    group: Any
    root_reply_id: int
    slowmode_seconds: int | None


async def resolve_target(client: Any, ref: TargetRef) -> AttackTarget:
    """Разрешить пост канала и группу его обсуждения.

    Пост-альбом сводится к первому сообщению: Telegram привязывает обсуждение
    только к нему. Ответ обсуждения приходит в обратном хронологическом
    порядке, поэтому корнем треда считается сообщение с наименьшим id.
    """
    channel = await client.get_entity(_peer_argument(ref.channel))
    if not isinstance(channel, types.Channel) or getattr(channel, "megagroup", False):
        raise PostNotFoundError(f"Ссылка {ref.link} ведёт не на пост канала.")

    post = _single(await client.get_messages(channel, ids=ref.post_id))
    if post is None or isinstance(post, types.MessageEmpty):
        raise PostNotFoundError(f"Пост {ref.link} не найден.")

    anchor = await _album_anchor(client, channel, ref, post)
    discussion = await client(
        functions.messages.GetDiscussionMessageRequest(peer=channel, msg_id=anchor)
    )
    root, group = _discussion_root(discussion, ref)
    slowmode = await _slowmode(client, group)
    _ensure_writable(group)
    return AttackTarget(group=group, root_reply_id=root.id, slowmode_seconds=slowmode)


async def refresh_slow_mode(client: Any, target: AttackTarget) -> AttackTarget:
    """Перечитать slow mode: пока мимик ждал, настройку могли изменить."""
    return replace(target, slowmode_seconds=await _slowmode(client, target.group))


def _peer_argument(peer: str) -> str | int:
    """Числовой peer Telethon ждёт числом, иначе резолв идёт как по юзернейму."""
    stripped = peer.strip()
    if stripped.lstrip("-").isdigit():
        return int(stripped)
    return stripped


async def _album_anchor(client: Any, channel: types.Channel, ref: TargetRef, post: Any) -> int:
    grouped_id = getattr(post, "grouped_id", None)
    if not isinstance(grouped_id, int):
        return ref.post_id

    first = max(1, ref.post_id - (MAX_ALBUM_ITEMS - 1))
    album = await client.get_messages(channel, ids=list(range(first, ref.post_id + 1)))
    ids = [
        item.id
        for item in _messages(album)
        if isinstance(getattr(item, "id", None), int)
        and getattr(item, "grouped_id", None) == grouped_id
    ]
    return min(ids) if ids else ref.post_id


def _discussion_root(discussion: Any, ref: TargetRef) -> tuple[Any, Any]:
    messages = getattr(discussion, "messages", None) or []
    if not messages:
        raise CommentsDisabledError(f"У поста {ref.link} нет обсуждения.")

    root = min(messages, key=lambda message: message.id)
    peer = getattr(root, "peer_id", None)
    channel_id = getattr(peer, "channel_id", None)
    chats = getattr(discussion, "chats", None) or []
    group = next((chat for chat in chats if getattr(chat, "id", None) == channel_id), None)
    if not isinstance(peer, types.PeerChannel) or group is None:
        raise CommentsDisabledError(f"У поста {ref.link} нет связанной группы обсуждения.")
    return root, group


async def _slowmode(client: Any, group: Any) -> int | None:
    full = await client(functions.channels.GetFullChannelRequest(channel=group))
    seconds = getattr(getattr(full, "full_chat", None), "slowmode_seconds", None)
    return seconds if isinstance(seconds, int) and seconds > 0 else None


def _ensure_writable(group: Any) -> None:
    window = window_from_chat(group, datetime.now(UTC))
    if window.forever and not _joinable(group):
        raise TargetNotWritableError("В группу обсуждения нельзя писать.")


def _joinable(group: Any) -> bool:
    """Группа, куда мимик ещё может вступить: запрет снимет join_if_needed."""
    return (
        isinstance(group, types.Channel)
        and bool(getattr(group, "megagroup", False))
        and bool(getattr(group, "left", False))
        and getattr(group, "join_to_send", None) is not False
    )


def _single(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _messages(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
