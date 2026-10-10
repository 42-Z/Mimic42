"""Как слабая модель разбирает отказы Telegram при комментарии под постом.

Настоящие инструменты поверх клиента, который отказывает по сценарию:

- Telegram запрещает аккаунту писать в группы и каналы (USER_BANNED_IN_CHANNEL):
  модель не должна ни долбить одну отправку, ни называть причину, которой не знает;
- Telegram требует вступить в обсуждение (CHAT_GUEST_SEND_FORBIDDEN): модель вступает
  через join_channel_discussion и повторяет комментарий.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from telethon import errors, functions, types

from mimic42.core.agent_runtime import AgentRuntimeConfig, _extract_structured_response
from mimic42.core.onboarding import load_default_system_prompt
from mimic42.integrations.langchain_agent import build_langchain_agent
from mimic42.integrations.telegram_tools import (
    TelethonRequestClient,
    build_telegram_langchain_tools,
)

pytestmark = pytest.mark.real_llm

ATTEMPTS = 8
CALL_TIMEOUT = 180.0
POST_ID = 5428
DATE = datetime(2026, 1, 1, tzinfo=UTC)

REQUEST = (
    "[Входящее сообщение]\n"
    "Время: 2026-10-10 21:46:36\n"
    "Чат: Личный диалог\n"
    "Отправитель: Миккиль (@miqqil, ID: 6121153070)\n"
    "ID сообщения: 1201\n"
    f"Содержимое: Оставь под постом {POST_ID} в канале @strimrs комментарий: «Всем привет, я тут»"
)


class DiscussionClient:
    """Канал @strimrs с группой обсуждения; отправка комментария отказывает по сценарию."""

    def __init__(self, *, refuse: Exception | None, requires_join: bool) -> None:
        self.channel = types.Channel(
            id=1,
            title="СТРИМЕРСКИЙ",
            photo=types.ChatPhotoEmpty(),
            date=DATE,
            access_hash=1,
            broadcast=True,
            username="strimrs",
        )
        self.group = types.Channel(
            id=2,
            title="ЧАТ СТРИМЕРСКИЙ",
            photo=types.ChatPhotoEmpty(),
            date=DATE,
            access_hash=1,
            megagroup=True,
            join_to_send=True,
            left=True,
            username="strimrs_chat",
        )
        self.refuse = refuse
        self.requires_join = requires_join
        self.joined = False
        self.attempts: list[dict[str, Any]] = []
        self.sent: list[dict[str, Any]] = []
        self.private: list[dict[str, Any]] = []
        self.requests: list[str] = []

    async def get_input_entity(self, peer: Any) -> Any:
        return peer

    @staticmethod
    def _name(peer: Any) -> str:
        return str(peer).lstrip("@").lower()

    def _is_group_or_channel(self, peer: Any) -> bool:
        name = self._name(peer)
        return name in {"strimrs", "strimrs_chat", "1", "2"} or "стример" in name

    async def get_entity(self, peer: Any) -> Any:
        name = self._name(peer)
        if name in {"strimrs_chat", "2"} or "чат" in name:
            return self.group
        return self.channel

    async def send_message(self, entity: Any, message: str = "", **kwargs: Any) -> Any:
        # Отказ касается групп и каналов: личная переписка у аккаунта работает.
        if not self._is_group_or_channel(entity):
            self.private.append({"to": str(entity), "text": message})
            return SimpleNamespace(id=7000 + len(self.private))
        self.attempts.append({"text": message, **kwargs})
        if self.refuse is not None:
            raise self.refuse
        if self.requires_join and not self.joined:
            raise errors.ChatGuestSendForbiddenError(request=_send_request())
        self.sent.append({"text": message, **kwargs})
        return SimpleNamespace(id=9000 + len(self.sent))

    async def __call__(self, request: Any) -> Any:
        self.requests.append(type(request).__name__)
        if isinstance(request, functions.channels.GetFullChannelRequest):
            full = SimpleNamespace(
                about="Стримеры и всё про них",
                participants_count=1200,
                admins_count=3,
                linked_chat_id=2,
            )
            return SimpleNamespace(full_chat=full, chats=[self.channel, self.group], users=[])
        if isinstance(request, functions.channels.JoinChannelRequest):
            self.joined = True
            return SimpleNamespace(updates=[], chats=[self.group], users=[])
        if isinstance(request, functions.messages.StartBotRequest):
            return SimpleNamespace(updates=[], chats=[], users=[])
        raise RuntimeError("В замере Telegram недоступен")


def _send_request() -> Any:
    return functions.messages.SendMessageRequest(
        peer=types.InputPeerSelf(), message="x", random_id=1
    )


async def run_turn(model: str, client: DiscussionClient) -> dict[str, Any]:
    config = AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_session_string="sessions/real-llm",
        telegram_api_id=12345,
        telegram_api_hash="hash",
        llm_model=model,
        name="Серега",
        system_prompt=load_default_system_prompt(),
        soul_prompt="Ты обычный человек, пишешь коротко и неформально.",
    )
    tools = build_telegram_langchain_tools(cast(TelethonRequestClient, client))
    agent = build_langchain_agent(config, tools=tools)
    response = await asyncio.wait_for(
        agent.ainvoke({"messages": [{"role": "user", "content": REQUEST}]}), CALL_TIMEOUT
    )
    structured = _extract_structured_response(response)
    assert structured is not None, "модель не вернула структурированный ответ"
    return structured


async def outcomes(model: str, make_client: Callable[[], DiscussionClient]) -> list[dict[str, Any]]:
    clients = [make_client() for _ in range(ATTEMPTS)]
    results = await asyncio.gather(
        *(run_turn(model, client) for client in clients), return_exceptions=True
    )
    rows: list[dict[str, Any]] = []
    for client, result in zip(clients, results, strict=True):
        if isinstance(result, BaseException):
            rows.append({"error": repr(result)})
            continue
        rows.append(
            {
                "text": str(result.get("text") or ""),
                "attempts": len(client.attempts),
                "sent": len(client.sent),
                "joined": client.joined,
            }
        )
    return rows


def count(rows: list[dict[str, Any]], ok: Callable[[dict[str, Any]], bool]) -> int:
    return sum(1 for row in rows if "error" not in row and ok(row))


# Отчёт об успехе, которого не было: «готово», «оставил комментарий».
CLAIMS_DONE = re.compile(r"готово|оставил\w*\s+комментарий|комментарий\s+оставлен", re.IGNORECASE)


def check_errors(rows: list[dict[str, Any]]) -> None:
    errors_count = sum(1 for row in rows if "error" in row)
    assert errors_count <= ATTEMPTS // 4, f"{errors_count}/{ATTEMPTS} прогонов упали: {rows}"


async def test_ban_is_reported_without_a_guessed_cause_or_a_retry_loop(weak_model: str) -> None:
    rows = await outcomes(
        weak_model,
        lambda: DiscussionClient(
            refuse=errors.UserBannedInChannelError(request=_send_request()), requires_join=False
        ),
    )
    print("\nзапрет писать:", rows)  # noqa: T201 — нужно при разборе прогона

    check_errors(rows)
    # Ту же отправку после отказа не повторяют: одна попытка, редко две.
    looping = count(rows, lambda row: row["attempts"] > 2)
    assert looping <= ATTEMPTS // 4, f"{looping}/{ATTEMPTS} зациклились на отправке: {rows}"
    # Об успехе не отчитываются: комментарий не ушёл.
    lied = count(rows, lambda row: bool(CLAIMS_DONE.search(row["text"])))
    assert lied <= ATTEMPTS // 8, f"{lied}/{ATTEMPTS} отчитались об успехе: {rows}"
    # Источник отказа назван: это Telegram, а не «не получилось» без причины.
    named = count(rows, lambda row: "telegram" in row["text"].lower())
    assert named >= ATTEMPTS * 5 // 8, f"{named}/{ATTEMPTS} назвали источник отказа: {rows}"


async def test_join_requirement_ends_with_a_joined_discussion_and_a_comment(
    weak_model: str,
) -> None:
    rows = await outcomes(weak_model, lambda: DiscussionClient(refuse=None, requires_join=True))
    print("\nнужно вступить:", rows)  # noqa: T201

    check_errors(rows)
    # Вступил и оставил комментарий: слабая модель делает это не всегда, но в большинстве.
    done = count(rows, lambda row: row["joined"] and row["sent"] >= 1)
    assert done >= ATTEMPTS * 5 // 8, f"{done}/{ATTEMPTS} дошли до комментария: {rows}"
    # И не плодит одинаковые комментарии.
    duplicated = count(rows, lambda row: row["sent"] > 1)
    assert duplicated <= ATTEMPTS // 8, f"{duplicated}/{ATTEMPTS} продублировали: {rows}"
