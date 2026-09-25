"""Медленный режим и запрет писать в настоящем Telegram.

Проверяющий создаёт супергруппу, зовёт туда мимика и меняет её настройки.
Смотрим и поведение, и то, что реально приходит мимику: не упущено ли что-то.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
import pytest

from mimic42.testing.real_tg.checker import Checker, SeenMessage
from mimic42.testing.slots import plain_dsn

pytestmark = pytest.mark.real_tg

SLOW_MODE_SECONDS = 30
# Слот 30 с, ход слабой модели занимает десятки секунд: окна наблюдения с запасом.
FLOOD_WATCH_SECONDS = 180
SILENCE_WATCH_SECONDS = 90
# Закрытое окно агент перечитывает раз в минуту (SendWindowTracker.restricted_ttl).
REREAD_PAUSE_SECONDS = 70


async def agent_events(agent_id: str, since: datetime) -> list[dict[str, object]]:
    conn = await asyncpg.connect(plain_dsn(os.environ["DATABASE_CONNECTION_STRING"]))
    try:
        rows = await conn.fetch(
            "select event_type, status, payload, error, created_at from agent_events "
            "where agent_id = $1 and created_at >= $2 order by created_at",
            UUID(agent_id),
            since,
        )
    finally:
        await conn.close()
    return [dict(row) for row in rows]


@asynccontextmanager
async def supergroup(checker: Checker, title: str, members: list[str]) -> AsyncIterator[int]:
    group = await checker.create_supergroup(title, members)
    try:
        yield group
    finally:
        await checker.delete_group(group)


async def mention(checker: Checker, phone: str) -> str:
    """Обращение к мимику по имени: иначе слабая модель может счесть чат не своим."""
    entity = await checker.client.get_entity(phone)
    return str(getattr(entity, "first_name", "") or "эй")


async def say_and_watch(
    checker: Checker, group: int, texts: list[str], *, pause: float, watch: float
) -> list[SeenMessage]:
    """Слушатель поднимается ДО отправки: иначе первые ответы можно пропустить."""
    watcher = asyncio.ensure_future(checker.collect_messages(group, seconds=watch))
    await asyncio.sleep(1)
    await checker.send_many(group, texts, pause=pause)
    return await watcher


async def test_flood_under_slow_mode_never_hits_a_slow_mode_error(
    checker: Checker, started_mimics: list[tuple[str, str]]
) -> None:
    agent_id, phone = started_mimics[0]
    await checker.import_contact(phone)
    mimic_id = await checker.resolve_id(phone)
    name = await mention(checker, phone)
    started = datetime.now(UTC)

    async with supergroup(checker, "Mimic42 slow mode", [phone]) as group:
        await checker.set_slow_mode(group, SLOW_MODE_SECONDS)
        seen = await say_and_watch(
            checker,
            group,
            [
                f"{name}, привет всем",
                f"{name}, ты тут?",
                "кто-нибудь знает хорошее место для кофе",
                f"{name}, посоветуй что-нибудь",
                f"{name}, ну так что?",
            ],
            pause=2.0,
            watch=FLOOD_WATCH_SECONDS,
        )

    mimic_messages = [m for m in seen if m.sender_id == mimic_id]
    events = await agent_events(agent_id, started)
    kinds = [str(e["event_type"]) for e in events]
    print("события агента:", kinds)  # noqa: T201 — нужно при разборе живого прогона
    print("сообщения мимика:", [(m.text[:40], m.reply_to) for m in mimic_messages])  # noqa: T201

    failed_sends = [e for e in events if e["event_type"] == "message.send_failed"]
    assert not failed_sends, f"Telegram отверг отправку при медленном режиме: {failed_sends}"
    assert mimic_messages, "мимик не ответил в группе с медленным режимом"
    # Больше сообщений, чем слотов за время наблюдения, физически отправить нельзя.
    assert len(mimic_messages) <= FLOOD_WATCH_SECONDS // SLOW_MODE_SECONDS + 1
    later = mimic_messages[1:]
    assert all(m.reply_to is not None for m in later), (
        "второй и следующие ответы схлопнутой пачки обязаны быть репликой: "
        f"{[(m.text[:30], m.reply_to) for m in later]}"
    )


async def test_restriction_silences_the_agent_and_lifting_it_brings_him_back(
    checker: Checker, started_mimics: list[tuple[str, str]]
) -> None:
    agent_id, phone = started_mimics[0]
    await checker.import_contact(phone)
    mimic_id = await checker.resolve_id(phone)
    name = await mention(checker, phone)
    started = datetime.now(UTC)

    async with supergroup(checker, "Mimic42 mute", [phone]) as group:
        await checker.restrict(group, mimic_id)
        silent = await say_and_watch(
            checker,
            group,
            [f"{name}, ответь пожалуйста"],
            pause=0.0,
            watch=SILENCE_WATCH_SECONDS,
        )
        assert [m for m in silent if m.sender_id == mimic_id] == [], (
            "мимик написал в чат, где у него отобрано право писать"
        )
        events = await agent_events(agent_id, started)
        kinds = [str(e["event_type"]) for e in events]
        print("события агента при запрете:", kinds)  # noqa: T201
        assert "message.write_forbidden" in kinds, f"событие о запрете не записано: {kinds}"

        await checker.unrestrict(group, mimic_id)
        await asyncio.sleep(REREAD_PAUSE_SECONDS)
        back = await say_and_watch(
            checker,
            group,
            [f"{name}, теперь можно, ответь"],
            pause=0.0,
            watch=FLOOD_WATCH_SECONDS,
        )

    assert [m for m in back if m.sender_id == mimic_id], "после снятия запрета мимик не ожил"
