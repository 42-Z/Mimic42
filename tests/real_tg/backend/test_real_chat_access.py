"""Отключённые чаты в настоящем Telegram: личка без ответа, канал без комментария.

Настройка включается так же, как это делает дашборд: запись в ``agents.settings``
и перезагрузка рантайма. Модель бесплатная, а ожидание ответа ограничено, чтобы
отсутствие реплики было доказательством, а не таймаутом на медленной модели:
в той же сессии «включённый» чат отвечает, значит, молчание — результат настройки.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from mimic42.testing.real_tg.checker import Checker, ThreadMessage
from tests.real_tg.backend.helpers import jwt
from tests.real_tg.backend.test_real_first_comment import (
    FAST_SECONDS,
    WATCH_SECONDS,
    channel_with_discussion,
    comments_under,
    dsn,
    first_comment,
    first_comment_events,
    reload,
)

pytestmark = pytest.mark.real_tg

# Сколько ждать ответа, который не должен прийти: модель на бесплатном тарифе отвечает
# за десятки секунд, а положительный контроль в конце теста подтверждает, что ответы идут.
SILENCE_SECONDS = 60.0


@asynccontextmanager
async def disabled_chats(
    client: AsyncClient, token: str, agent_id: str, chat_ids: list[int]
) -> AsyncGenerator[None]:
    """Отключает чаты и возвращает прежнее значение настройки."""
    conn = await asyncpg.connect(dsn())
    try:
        original = await conn.fetchval(
            "select settings->'disabled_chats' from agents where id = $1::uuid", agent_id
        )
        await conn.execute(
            "update agents set settings = settings"
            " || jsonb_build_object('disabled_chats', $2::jsonb) where id = $1::uuid",
            agent_id,
            json.dumps(chat_ids),
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
                    "update agents set settings = settings - 'disabled_chats'"
                    " where id = $1::uuid",
                    agent_id,
                )
            else:
                await conn.execute(
                    "update agents set settings = jsonb_set(settings, '{disabled_chats}', $2::jsonb)"
                    " where id = $1::uuid",
                    agent_id,
                    original,
                )
        finally:
            await conn.close()
        await reload(client, token, agent_id)


def comments_under_or_empty(
    seen: list[ThreadMessage], post_ids: list[int], author: int, text: str
) -> list[ThreadMessage]:
    """Комментарии автора к постам; пересылка поста в обсуждение может не прийти за окно."""
    forwards = {m.message_id for m in seen if m.channel_post in post_ids}
    return [m for m in seen if m.sender_id == author and m.text == text and m.reply_to in forwards]


async def test_disabled_private_chat_gets_no_reply_and_enabled_one_does(
    real_app: tuple[FastAPI, AsyncClient],
    checker: Checker,
    started_mimics: list[tuple[str, str]],
) -> None:
    _, client = real_app
    agent_id, phone = started_mimics[0]
    await checker.import_contact(phone)
    mimic_id = await checker.resolve_id(phone)
    checker_id = await checker.my_id()
    token = await jwt()

    async with disabled_chats(client, token, agent_id, [checker_id]):
        watcher = asyncio.ensure_future(
            checker.collect_messages(mimic_id, seconds=SILENCE_SECONDS)
        )
        await asyncio.sleep(1)
        await checker.send(phone, "Ты меня слышишь?")
        seen = await watcher
    replies = [m for m in seen if m.sender_id == mimic_id]
    assert replies == [], f"мимик ответил из отключённого чата: {replies}"

    # Положительный контроль: после включения чата тот же собеседник получает ответ.
    reply = await checker.send_and_wait_reply(phone, "А теперь слышишь?", timeout=300)
    assert reply.strip(), "после включения чата мимик не ответил"


async def test_disabled_channel_gets_no_first_comment_and_enabled_one_gets(
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

    async with first_comment(client, token, agent_id, [{"text": comment}]):
        async with disabled_chats(client, token, agent_id, [channel_id]):
            watcher = asyncio.ensure_future(
                checker.collect_thread(group_id, seconds=WATCH_SECONDS)
            )
            await asyncio.sleep(1)
            muted_post = await checker.post(channel_id, "Пост в отключённый канал")
            muted_seen = await watcher

        events_muted = await first_comment_events(agent_id, started)
        assert comments_under_or_empty(muted_seen, [muted_post], mimic_id, comment) == []
        assert [e for e in events_muted if e.get("peer") == str(channel_id)] == [], events_muted

        # Положительный контроль: канал снова включён (disabled_chats вернулся).
        watcher = asyncio.ensure_future(checker.collect_thread(group_id, seconds=WATCH_SECONDS))
        await asyncio.sleep(1)
        post_at = loop.time()
        post_id = await checker.post(channel_id, "Пост во включённый канал")
        seen = await watcher

    on_post = comments_under(seen, [post_id], mimic_id, comment)
    assert len(on_post) == 1, f"под постом {len(on_post)} первых комментариев"
    assert on_post[0].arrived - post_at < FAST_SECONDS
