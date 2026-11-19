"""Режим атаки в настоящем Telegram: кампания, вступление и комментарии.

Сценарий проверяет то, что нельзя проверить на подделках: пост канала
разрешается в группу обсуждения, мимик вступает в неё сам, сырые запросы с
``random_id`` доходят до Telegram, альбом теряет лишние картинки и не
повторяет их внутри комментария, а общий лимит останавливает кампанию.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from io import BytesIO
from typing import Any, cast
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from PIL import Image
from telethon import events, functions
from telethon.errors import ChatNotModifiedError

from mimic42.api.app import create_app
from mimic42.testing.real_tg.checker import Checker
from mimic42.testing.slots import plain_dsn
from tests.real_tg.backend.helpers import (
    MemoryMediaStorage,
    agent_id_for_phone,
    disable_auto_restore,
    jwt,
    real_app_settings,
    user_id_from_token,
)

pytestmark = pytest.mark.real_tg

CHANNEL_TITLE = "Mimic42 attack"
IMAGE_COUNT = 12
COMMENT_COUNT = 3
MESSAGE_LIMIT = COMMENT_COUNT * 10
ATTACK_TIMEOUT_SECONDS = 180
SLOW_MODE_SECONDS = 30


def png(color: tuple[int, int, int]) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (64, 64), color).save(buffer, format="PNG")
    return buffer.getvalue()


def private_link(channel_id: int, post_id: int) -> str:
    marked = str(abs(channel_id))
    assert marked.startswith("100"), f"не канал: {channel_id}"
    return f"https://t.me/c/{marked[3:]}/{post_id}"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def attack_app() -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    """Приложение с хранилищем в памяти: боевой ключ Storage может быть недоступен."""
    media = MemoryMediaStorage()
    app = create_app(settings=real_app_settings(), media_uploader=media)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield app, client


@pytest_asyncio.fixture
async def attack_mimics(checker: Checker) -> list[tuple[str, str]]:
    """Мимики без запуска и без проверки бесплатной модели.

    Атака не вызывает LLM: комментарии берутся из пула текстов, поэтому
    платная модель на аккаунте не тратится. Запуск делает сам сервис при
    старте кампании — так проверяется и сценарий «мимик был остановлен».
    """
    token = await jwt()
    owner_id = user_id_from_token(token)
    dsn = os.environ["DATABASE_CONNECTION_STRING"]
    await disable_auto_restore(dsn, owner_id)
    agents: list[tuple[str, str]] = []
    for phone in await checker.mimic_phones(dsn, owner_id):
        agents.append((await agent_id_for_phone(dsn, phone, owner_id), phone))
    return agents


async def wait_finished(client: AsyncClient, attack_id: str, token: str) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + ATTACK_TIMEOUT_SECONDS
    while loop.time() < deadline:
        response = await client.get(f"/api/v1/attacks/{attack_id}", headers=auth(token))
        assert response.status_code == 200, response.text
        detail = cast(dict[str, Any], response.json())
        if detail["status"] in ("finished", "cancelled"):
            return detail
        await asyncio.sleep(2)
    raise AssertionError(f"атака не завершилась за {ATTACK_TIMEOUT_SECONDS} секунд")


async def thread_messages(
    checker: Checker, channel_id: int, group_id: int, post_id: int
) -> tuple[Any, list[Any]]:
    channel = await checker.client.get_input_entity(channel_id)
    discussion = await checker.client(
        functions.messages.GetDiscussionMessageRequest(peer=channel, msg_id=post_id)
    )
    root_id = min(int(message.id) for message in cast(Any, discussion).messages)
    messages = cast(list[Any], await checker.client.get_messages(group_id, limit=100))
    root = next(message for message in messages if message.id == root_id)
    comments = [
        message
        for message in messages
        if getattr(message.reply_to, "reply_to_msg_id", None) == root_id
    ]
    return root, comments


async def cleanup_attacks(ids: list[str], client: AsyncClient, token: str) -> None:
    for attack_id in ids:
        response = await client.post(f"/api/v1/attacks/{attack_id}/cancel", headers=auth(token))
        assert response.status_code in (200, 409), response.text
    if not ids:
        return
    conn = await asyncpg.connect(plain_dsn(os.environ["DATABASE_CONNECTION_STRING"]))
    try:
        await conn.execute(
            "delete from attacks where id = any($1::uuid[])",
            [UUID(attack_id) for attack_id in ids],
        )
    finally:
        await conn.close()


async def test_attack_comments_appear_under_a_real_channel_post(
    attack_app: tuple[FastAPI, AsyncClient],
    checker: Checker,
    attack_mimics: list[tuple[str, str]],
) -> None:
    _, client = attack_app
    token = await jwt()
    agent_ids = [UUID(agent_id) for agent_id, _ in attack_mimics]
    mimic_ids = {await checker.resolve_id(phone) for _, phone in attack_mimics}

    channel_id, group_id = await checker.ensure_channel(CHANNEL_TITLE, discussion=True)
    assert group_id is not None, "у канала нет группы обсуждения"
    post_id = await checker.post(channel_id, f"mimic42 attack {uuid4()}")
    # Подписка после публикации: иначе работающий мимик получит пост как
    # обычное входящее и потратит ход LLM до старта атаки.
    for _, phone in attack_mimics:
        await checker.subscribe(channel_id, phone)

    media: list[dict[str, str]] = []
    for index in range(IMAGE_COUNT):
        data = png((20 + index * 15, 80, 160))
        response = await client.post(
            "/api/v1/attack-media",
            headers=auth(token),
            files={"file": (f"attack{index}.png", data, "image/png")},
        )
        assert response.status_code == 201, response.text
        body = cast(dict[str, Any], response.json())
        media.append({"path": body["storage_path"], "name": body["name"]})

    created = await client.post(
        "/api/v1/attacks",
        headers=auth(token),
        json={
            "title": f"Атака {uuid4()}",
            "target_link": private_link(channel_id, post_id),
            "texts": ["Первый текст атаки", "Второй текст атаки"],
            "images": media,
            "limit_kind": "messages",
            "message_limit": MESSAGE_LIMIT,
            "agent_ids": [str(agent_id) for agent_id in agent_ids],
        },
    )
    assert created.status_code == 201, created.text
    attack = cast(dict[str, Any], created.json())
    attack_id = str(attack["id"])
    repeat_id: str | None = None

    typing_users: set[int] = set()
    user_update = events.UserUpdate()

    async def on_typing(event: Any) -> None:
        if getattr(event, "action", None) is None:
            return
        user_id = getattr(event, "user_id", None)
        if isinstance(user_id, int) and user_id in mimic_ids:
            typing_users.add(user_id)

    checker.client.add_event_handler(on_typing, user_update)
    try:
        started = await client.post(f"/api/v1/attacks/{attack_id}/start", headers=auth(token))
        assert started.status_code == 200, started.text
        detail = await wait_finished(client, attack_id, token)

        assert detail["status"] == "finished"
        assert detail["end_reason"] == "limit_reached"
        assert detail["sent_count"] == MESSAGE_LIMIT
        assert detail["claimed_count"] == MESSAGE_LIMIT

        root, messages = await thread_messages(checker, channel_id, group_id, post_id)
        assert root.fwd_from is not None
        assert root.fwd_from.channel_post == post_id
        albums: dict[int, list[Any]] = {}
        for message in messages:
            grouped_id = getattr(message, "grouped_id", None)
            if isinstance(grouped_id, int):
                albums.setdefault(grouped_id, []).append(message)
        assert len(albums) == COMMENT_COUNT, [
            (message.id, message.sender_id, message.message) for message in messages
        ]
        captions: list[str] = []
        orders: set[tuple[int, ...]] = set()
        sent: list[tuple[int, Any]] = []
        for items in albums.values():
            assert len(items) == 10, f"в альбоме {len(items)} сообщений"
            photo_ids = [item.photo.id for item in items if item.photo is not None]
            assert len(photo_ids) == 10
            assert len(set(photo_ids)) == 10, "внутри комментария картинка повторилась"
            orders.add(tuple(photo_ids))
            own_captions = [item.message for item in items if item.message]
            assert len(own_captions) == 1, own_captions
            captions.append(own_captions[0])
            sent.append((items[0].sender_id, min(item.date for item in items)))
        assert all(caption in detail["texts"] for caption in captions)
        assert len(orders) > 1, "порядок картинок не меняется между комментариями"
        assert {sender for sender, _ in sent} == mimic_ids

        for sender in mimic_ids:
            own = sorted(date for agent, date in sent if agent == sender)
            for previous, current in zip(own, own[1:], strict=False):
                pause = (current - previous).total_seconds()
                assert pause >= 10, f"мимик {sender} писал чаще паузы: {pause} с"

        await asyncio.sleep(1)
        assert typing_users, "проверяющий не увидел статус «печатает»"

        repeated = await client.post(f"/api/v1/attacks/{attack_id}/repeat", headers=auth(token))
        assert repeated.status_code == 201, repeated.text
        draft = cast(dict[str, Any], repeated.json())
        repeat_id = str(draft["id"])
        assert draft["status"] == "draft"
        assert draft["sent_count"] == 0
        assert {agent["agent_id"] for agent in draft["agents"]} == {
            str(agent_id) for agent_id in agent_ids
        }
        assert draft["target_link"] == attack["target_link"]
    finally:
        checker.client.remove_event_handler(on_typing, user_update)
        ids = [attack_id] + ([repeat_id] if repeat_id else [])
        await cleanup_attacks(ids, client, token)


async def test_a_slow_mode_attack_keeps_a_ten_image_album(
    attack_app: tuple[FastAPI, AsyncClient],
    checker: Checker,
    attack_mimics: list[tuple[str, str]],
) -> None:
    """Slow mode ограничивает частоту сообщений, а не вложения в альбоме."""
    _, client = attack_app
    token = await jwt()
    agent_id, phone = attack_mimics[0]
    mimic_id = await checker.resolve_id(phone)
    channel_id, group_id = await checker.ensure_channel("Mimic42 attack slow mode", discussion=True)
    assert group_id is not None, "у канала нет группы обсуждения"
    try:
        await checker.set_slow_mode(group_id, SLOW_MODE_SECONDS)
    except ChatNotModifiedError:
        pass
    post_id = await checker.post(channel_id, f"mimic42 slow album {uuid4()}")
    await checker.subscribe(channel_id, phone)

    media: list[dict[str, str]] = []
    for index in range(IMAGE_COUNT):
        data = png((20 + index * 15, 80, 160))
        response = await client.post(
            "/api/v1/attack-media",
            headers=auth(token),
            files={"file": (f"slow{index}.png", data, "image/png")},
        )
        assert response.status_code == 201, response.text
        body = cast(dict[str, Any], response.json())
        media.append({"path": body["storage_path"], "name": body["name"]})

    created = await client.post(
        "/api/v1/attacks",
        headers=auth(token),
        json={
            "title": f"Медленный альбом {uuid4()}",
            "target_link": private_link(channel_id, post_id),
            "texts": ["Медленный текст атаки"],
            "images": media,
            "limit_kind": "messages",
            "message_limit": IMAGE_COUNT,
            "agent_ids": [agent_id],
        },
    )
    assert created.status_code == 201, created.text
    attack_id = str(cast(dict[str, Any], created.json())["id"])

    try:
        started = await client.post(f"/api/v1/attacks/{attack_id}/start", headers=auth(token))
        assert started.status_code == 200, started.text
        detail = await wait_finished(client, attack_id, token)

        assert detail["status"] == "finished"
        assert detail["sent_count"] == IMAGE_COUNT
        assert detail["claimed_count"] == IMAGE_COUNT
        assert detail["agents"][0]["last_error"] is None

        _, messages = await thread_messages(checker, channel_id, group_id, post_id)
        own = [message for message in messages if message.sender_id == mimic_id]
        assert len(own) == IMAGE_COUNT, [
            (message.id, message.sender_id, message.message) for message in messages
        ]
        grouped = {getattr(message, "grouped_id", None) for message in own}
        assert None not in grouped
        assert all(message.photo is not None for message in own)
        assert any(message.message for message in own)
    finally:
        await cleanup_attacks([attack_id], client, token)
