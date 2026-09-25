"""Первый комментарий под постом канала в настоящем Telegram.

У проверяющего два постоянных канала: с группой обсуждения и без неё, мимик
подписан на оба. Первый комментарий мимику включается так же, как это делает
дашборд: запись в настройки агента и перезагрузка рантайма. Затем проверяющий
публикует посты и слушает обсуждение: комментарий к посту — это реплика на его
автопересылку в группу.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from PIL import Image

from mimic42.integrations.supabase_media import BUCKET
from mimic42.testing.real_tg.checker import Checker, ThreadMessage
from mimic42.testing.slots import plain_dsn
from supabase import create_client
from tests.real_tg.backend.helpers import jwt

pytestmark = pytest.mark.real_tg

# Каналы создаются один раз и живут на аккаунте проверяющего (Checker.ensure_channel).
DISCUSSION_CHANNEL = "Mimic42 · первый комментарий"
QUIET_CHANNEL = "Mimic42 · без обсуждения"
# Без ИИ комментарий — это доставка поста, пара секунд FLOOD_WAIT на ветку
# свежего поста и два запроса к Telegram.
FAST_SECONDS = 10.0
WATCH_SECONDS = 25.0
# Новый подписчик получает апдейты канала не в ту же секунду после приглашения.
SETTLE_SECONDS = 3.0


def dsn() -> str:
    return plain_dsn(os.environ["DATABASE_CONNECTION_STRING"])


@asynccontextmanager
async def first_comment(
    client: AsyncClient, token: str, agent_id: str, variants: list[dict[str, Any]]
) -> AsyncIterator[None]:
    """Включает первый комментарий и возвращает прежнее значение настройки."""
    conn = await asyncpg.connect(dsn())
    try:
        original = await conn.fetchval(
            "select settings->'first_comment' from agents where id = $1::uuid", agent_id
        )
        await conn.execute(
            "update agents set settings = settings"
            " || jsonb_build_object('first_comment', $2::jsonb) where id = $1::uuid",
            agent_id,
            json.dumps({"enabled": True, "variants": variants}),
        )
    finally:
        await conn.close()
    try:
        await reload(client, token, agent_id)
        yield
    finally:
        conn = await asyncpg.connect(dsn())
        try:
            if original is None:
                await conn.execute(
                    "update agents set settings = settings - 'first_comment' where id = $1::uuid",
                    agent_id,
                )
            else:
                await conn.execute(
                    "update agents set settings = jsonb_set(settings, '{first_comment}', $2::jsonb)"
                    " where id = $1::uuid",
                    agent_id,
                    original,
                )
        finally:
            await conn.close()


async def reload(client: AsyncClient, token: str, agent_id: str) -> None:
    response = await client.post(
        f"/api/v1/agents/{agent_id}/reload", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 204, response.text


async def channel_with_discussion(checker: Checker, phone: str) -> tuple[int, int]:
    channel_id, group_id = await checker.ensure_channel(DISCUSSION_CHANNEL, discussion=True)
    assert group_id is not None
    if await checker.subscribe(channel_id, phone):
        await asyncio.sleep(SETTLE_SECONDS)
    return channel_id, group_id


async def channel_without_discussion(checker: Checker, phone: str) -> int:
    channel_id, _ = await checker.ensure_channel(QUIET_CHANNEL, discussion=False)
    if await checker.subscribe(channel_id, phone):
        await asyncio.sleep(SETTLE_SECONDS)
    return channel_id


async def first_comment_events(agent_id: str, since: datetime) -> list[dict[str, Any]]:
    conn = await asyncpg.connect(dsn())
    try:
        rows = await conn.fetch(
            "select event_type, payload from agent_events where agent_id = $1"
            " and created_at >= $2 and event_type like 'first_comment.%' order by created_at",
            UUID(agent_id),
            since,
        )
    finally:
        await conn.close()
    return [{"event_type": row["event_type"], **json.loads(row["payload"] or "{}")} for row in rows]


def png(color: tuple[int, int, int]) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (320, 240), color).save(buffer, format="PNG")
    return buffer.getvalue()


def comments_under(
    seen: list[ThreadMessage], post_ids: list[int], author: int, text: str
) -> list[ThreadMessage]:
    """Комментарии автора с заданным текстом к указанным постам канала."""
    forwards = {m.message_id for m in seen if m.channel_post in post_ids}
    assert forwards, f"посты {post_ids} не переслались в обсуждение: {seen}"
    return [m for m in seen if m.sender_id == author and m.text == text and m.reply_to in forwards]


async def test_post_and_album_get_one_instant_comment_and_quiet_channel_gets_none(
    real_app: tuple[FastAPI, AsyncClient],
    checker: Checker,
    started_mimics: list[tuple[str, str]],
) -> None:
    _, client = real_app
    agent_id, phone = started_mimics[0]
    await checker.import_contact(phone)
    mimic_id = await checker.resolve_id(phone)
    token = await jwt()
    comment = f"Первый! {uuid4().hex[:6]}"
    started = datetime.now(UTC)
    loop = asyncio.get_running_loop()

    channel_id, group_id = await channel_with_discussion(checker, phone)
    quiet_id = await channel_without_discussion(checker, phone)

    async with first_comment(client, token, agent_id, [{"text": comment}]):
        watcher = asyncio.ensure_future(checker.collect_thread(group_id, seconds=WATCH_SECONDS))
        await asyncio.sleep(1)
        post_at = loop.time()
        post_id = await checker.post(channel_id, "Понедельник, а прод уже лежит")
        await asyncio.sleep(3)
        album_at = loop.time()
        album_ids = await checker.post_album(
            channel_id, [png((200, 40, 40)), png((40, 40, 200))], "Фотки с митапа"
        )
        await checker.post(quiet_id, "Здесь комментарии выключены")
        seen = await watcher

    events = await first_comment_events(agent_id, started)
    print("обсуждение:", seen)  # noqa: T201 — нужно при разборе живого прогона
    print("события первого комментария:", events)  # noqa: T201

    on_post = comments_under(seen, [post_id], mimic_id, comment)
    on_album = comments_under(seen, album_ids, mimic_id, comment)
    assert len(on_post) == 1, f"под постом {len(on_post)} первых комментариев"
    assert len(on_album) == 1, f"под альбомом {len(on_album)} первых комментариев"
    print(  # noqa: T201
        f"задержка: пост {on_post[0].arrived - post_at:.1f} с, "
        f"альбом {on_album[0].arrived - album_at:.1f} с"
    )
    assert on_post[0].arrived - post_at < FAST_SECONDS
    assert on_album[0].arrived - album_at < FAST_SECONDS

    assert not [e for e in events if e["event_type"] == "first_comment.failed"], events
    assert [e for e in events if e.get("peer") == str(quiet_id)] == [], (
        "у канала без обсуждения не должно быть ни комментария, ни ошибки"
    )


async def test_image_comment_reuses_the_uploaded_photo(
    real_app: tuple[FastAPI, AsyncClient],
    checker: Checker,
    started_mimics: list[tuple[str, str]],
) -> None:
    app, client = real_app
    if app.state.media_uploader is None:
        # Service-ключ в CI не передаётся намеренно: там картинку негде хранить.
        pytest.skip("хранилище медиа не настроено: нужен SUPABASE_SERVICE_ROLE_KEY")
    agent_id, phone = started_mimics[0]
    await checker.import_contact(phone)
    mimic_id = await checker.resolve_id(phone)
    token = await jwt()
    caption = f"Я первый {uuid4().hex[:6]}"
    started = datetime.now(UTC)
    loop = asyncio.get_running_loop()

    upload = await client.post(
        f"/api/v1/agents/{agent_id}/media",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("first.png", png((40, 160, 90)), "image/png")},
    )
    assert upload.status_code == 201, upload.text
    image_path = upload.json()["storage_path"]
    try:
        channel_id, group_id = await channel_with_discussion(checker, phone)
        async with first_comment(
            client,
            token,
            agent_id,
            [{"text": caption, "image_path": image_path, "image_name": "first.png"}],
        ):
            watcher = asyncio.ensure_future(checker.collect_thread(group_id, seconds=WATCH_SECONDS))
            await asyncio.sleep(1)
            first_at = loop.time()
            first_id = await checker.post(channel_id, "Первый пост недели")
            await asyncio.sleep(5)
            second_at = loop.time()
            second_id = await checker.post(channel_id, "И второй следом")
            seen = await watcher
    finally:
        # Картинка тестовая: в хранилище агента её не оставляем.
        storage = create_client(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        ).storage
        await asyncio.to_thread(lambda: storage.from_(BUCKET).remove([image_path]))

    events = await first_comment_events(agent_id, started)
    print("обсуждение:", seen)  # noqa: T201
    print("события первого комментария:", events)  # noqa: T201

    first = comments_under(seen, [first_id], mimic_id, caption)
    second = comments_under(seen, [second_id], mimic_id, caption)
    assert len(first) == 1 and len(second) == 1, f"комментарии: {first}, {second}"
    print(  # noqa: T201
        f"задержка: загрузка {first[0].arrived - first_at:.1f} с, "
        f"повтор {second[0].arrived - second_at:.1f} с"
    )
    assert first[0].photo_id is not None, "картинка не дошла — комментарий ушёл без неё"
    assert second[0].photo_id == first[0].photo_id, (
        "картинка загружена заново, а не переиспользована"
    )
    assert second[0].arrived - second_at < FAST_SECONDS
    assert not [e for e in events if e["event_type"] == "first_comment.failed"], events
