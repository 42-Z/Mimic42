"""Реальный диалог: проверяющий пишет мимику, мимик отвечает в настоящем TG."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from mimic42.testing.real_tg.checker import Checker
from mimic42.testing.slots import plain_dsn
from tests.real_tg.backend.helpers import jwt

pytestmark = pytest.mark.real_tg


async def test_agent_replies_in_real_telegram(
    checker: Checker, started_mimics: list[tuple[str, str]]
) -> None:
    agent_id, phone = started_mimics[0]
    await checker.import_contact(phone)
    reply = await checker.send_and_wait_reply(phone, "Привет, как дела?", timeout=300)
    assert reply and reply.strip(), "Мимик не ответил в реальном Telegram"

    conn = await asyncpg.connect(plain_dsn(os.environ["DATABASE_CONNECTION_STRING"]))
    try:
        rows = await conn.fetch(
            "select direction from agent_messages where agent_id = $1 "
            "order by created_at desc limit 10",
            UUID(agent_id),
        )
    finally:
        await conn.close()
    directions = {row["direction"] for row in rows}
    assert "incoming" in directions, "Входящее не записано в agent_messages"
    assert "agent_response" in directions, "Ответ не записан в agent_messages"


async def test_trigger_message_arrives_in_telegram(
    real_app: tuple[FastAPI, AsyncClient],
    checker: Checker,
    started_mimics: list[tuple[str, str]],
) -> None:
    agent_id, phone = started_mimics[1]
    _, client = real_app
    token = await jwt()
    await checker.import_contact(phone)
    # Мимик должен увидеть проверяющего: телефон резолвится только из контактов,
    # а числовой id — из кэша сессии после входящего сообщения. Заодно ждём
    # ответ, чтобы кэш точно был заполнен до триггера.
    await checker.send_and_wait_reply(phone, "Разогрев перед триггером", timeout=300)
    checker_id = await checker.my_id()
    incoming = asyncio.ensure_future(checker.wait_incoming(phone, timeout=300))
    response = await client.post(
        f"/api/v1/agents/{agent_id}/messages/trigger",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "peer": str(checker_id),
            "text": "Ответь проверяющему, что сообщение из дашборда дошло",
        },
    )
    assert response.status_code == 200, response.text
    # Модель обязана отправить ответ (а не промолчать) — иначе ждать доставку
    # бессмысленно, и это видно сразу по ответу API.
    assert response.json()["telegram_message_id"] is not None, response.text
    text = await incoming
    assert text and text.strip()
