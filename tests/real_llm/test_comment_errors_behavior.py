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
from telethon import errors, functions, types, utils

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
CAPTCHA_MESSAGE_ID = 2557938
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

    def __init__(
        self, *, refuse: Exception | None, requires_join: bool, captcha: bool = False
    ) -> None:
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
        # Бот-верификатор встречает вступившего капчей, пока её не решат, писать нельзя.
        self.captcha = captcha
        self.verified = False
        self.refusals: list[str] = []
        self.joined = False
        self.attempts: list[dict[str, Any]] = []
        # Только настоящие комментарии под нужным постом: именно их ждёт задача.
        self.sent: list[dict[str, Any]] = []
        # Отправки, ушедшие не туда: в канал без comment_to или не под тот пост.
        self.stray: list[dict[str, Any]] = []
        self.private: list[dict[str, Any]] = []
        self.requests: list[str] = []
        # Вступления и нажатия не в ту группу, не на то сообщение, не той кнопкой.
        self.wrong_joins: list[str] = []
        self.wrong_clicks: list[str] = []
        # Что делала модель, по порядку: нужно при разборе упавшего прогона.
        self.log: list[str] = []

    async def get_input_entity(self, peer: Any) -> Any:
        return peer

    async def get_peer_id(self, peer: Any, add_mark: bool = True) -> int:
        """ID с пометкой типа: у канала и группы разные, у человека — обычный."""
        if isinstance(peer, int):
            return peer
        if self._is_group(peer):
            return utils.get_peer_id(types.PeerChannel(self.group.id))
        if self._is_channel(peer):
            return utils.get_peer_id(types.PeerChannel(self.channel.id))
        return 6121153070

    @staticmethod
    def _name(peer: Any) -> str:
        return str(getattr(peer, "username", None) or peer).lstrip("@").lower()

    def _is_group(self, peer: Any) -> bool:
        name = self._name(peer)
        marked = str(utils.get_peer_id(types.PeerChannel(self.group.id)))
        return peer is self.group or name in {"strimrs_chat", "2", marked} or "чат" in name

    def _is_channel(self, peer: Any) -> bool:
        name = self._name(peer)
        marked = str(utils.get_peer_id(types.PeerChannel(self.channel.id)))
        return not self._is_group(peer) and (
            peer is self.channel or name in {"strimrs", "1", marked} or "стример" in name
        )

    def _is_group_or_channel(self, peer: Any) -> bool:
        return self._is_group(peer) or self._is_channel(peer)

    async def get_entity(self, peer: Any) -> Any:
        return self.group if self._is_group(peer) else self.channel

    async def send_message(self, entity: Any, message: str = "", **kwargs: Any) -> Any:
        self.log.append(f"send {self._name(entity)} comment_to={kwargs.get('comment_to')}")
        # Отказ касается групп и каналов: личная переписка у аккаунта работает.
        if not self._is_group_or_channel(entity):
            self.private.append({"to": str(entity), "text": message})
            return SimpleNamespace(id=7000 + len(self.private))
        self.attempts.append({"text": message, **kwargs})
        refusal: Exception | None = None
        if self.refuse is not None:
            refusal = self.refuse
        elif self.requires_join and not self.joined:
            refusal = errors.ChatGuestSendForbiddenError(request=_send_request())
        elif self.captcha and self.joined and not self.verified:
            refusal = errors.ChatWriteForbiddenError(request=_send_request())
        if refusal is not None:
            self.refusals.append(type(refusal).__name__)
            raise refusal
        # Комментарий — это отправка в канал с comment_to=ID поста. Простая отправка в
        # вещательный канал без прав администратора Telegram не пропускает, а сообщение
        # прямо в группу — не комментарий под постом.
        is_comment = self._is_channel(entity) and kwargs.get("comment_to") == POST_ID
        if not is_comment:
            self.stray.append({"to": self._name(entity), "text": message, **kwargs})
            if self._is_channel(entity):
                refusal = errors.ChatWriteForbiddenError(request=_send_request())
                self.refusals.append(type(refusal).__name__)
                raise refusal
            return SimpleNamespace(id=8000 + len(self.stray))
        self.sent.append({"text": message, **kwargs})
        return SimpleNamespace(id=9000 + len(self.sent))

    def _captcha_message(self) -> Any:
        keyboard = types.ReplyInlineMarkup(
            rows=[
                types.KeyboardButtonRow(
                    buttons=[types.KeyboardButtonUrl(text="Правила", url="https://example.org")]
                ),
                types.KeyboardButtonRow(
                    buttons=[
                        types.KeyboardButtonCallback(text=answer, data=data)
                        for answer, data in (
                            ("19", b"wrong-19"),
                            ("10", b"wrong-10"),
                            ("59", b"right-59"),
                            ("22", b"wrong-22"),
                        )
                    ]
                ),
            ]
        )
        return SimpleNamespace(
            id=CAPTCHA_MESSAGE_ID,
            text="Добро пожаловать! Для вступления в чат реши математический пример. "
            "Captcha: 33+26",
            sender_id=8172563028,
            date=datetime.now(UTC),
            reply_markup=keyboard,
            media=None,
        )

    def _history(self, entity: Any) -> list[Any]:
        if self._is_group(entity):
            if self.captcha and self.joined and not self.verified:
                return [self._captcha_message()]
            return []
        return [
            SimpleNamespace(
                id=POST_ID,
                text="Сегодня стрим по новому патчу, ждём всех",
                sender_id=-1001,
                date=DATE,
                reply_markup=None,
                media=None,
            )
        ]

    async def get_messages(self, entity: Any, limit: int | None = None, **kwargs: Any) -> Any:
        self.log.append(f"get_messages {self._name(entity)}")
        return self._history(entity)[: limit or None]

    async def iter_messages(self, entity: Any, limit: int | None = None, **kwargs: Any) -> Any:
        self.log.append(f"iter_messages {self._name(entity)}")
        for message in self._history(entity)[: limit or None]:
            yield message

    async def __call__(self, request: Any) -> Any:
        self.requests.append(type(request).__name__)
        detail = ""
        if isinstance(request, functions.channels.JoinChannelRequest):
            detail = f" {self._name(request.channel)}"
        elif isinstance(request, functions.messages.GetBotCallbackAnswerRequest):
            detail = f" {self._name(request.peer)} msg={request.msg_id} data={request.data!r}"
        self.log.append(f"{type(request).__name__}{detail}")
        if isinstance(request, functions.channels.GetFullChannelRequest):
            full = SimpleNamespace(
                about="Стримеры и всё про них",
                participants_count=1200,
                admins_count=3,
                linked_chat_id=2,
            )
            return SimpleNamespace(full_chat=full, chats=[self.channel, self.group], users=[])
        if isinstance(request, functions.channels.JoinChannelRequest):
            # Комментировать пускает только вступление в группу обсуждения: вступление
            # в сам канал её не открывает.
            if not self._is_group(request.channel):
                self.wrong_joins.append(self._name(request.channel))
                return SimpleNamespace(updates=[], chats=[self.channel], users=[])
            self.joined = True
            return SimpleNamespace(updates=[], chats=[self.group], users=[])
        if isinstance(request, functions.messages.StartBotRequest):
            return SimpleNamespace(updates=[], chats=[], users=[])
        if isinstance(request, functions.messages.GetBotCallbackAnswerRequest):
            # Капча живёт в сообщении группы: нажатие по другому чату или сообщению
            # ничего не решает, как и неверный ответ.
            if not self._is_group(request.peer) or request.msg_id != CAPTCHA_MESSAGE_ID:
                self.wrong_clicks.append(f"{self._name(request.peer)}:{request.msg_id}")
                return SimpleNamespace(message="Сообщение не найдено", alert=True, url=None)
            if self.joined and request.data == b"right-59":
                self.verified = True
                return SimpleNamespace(message="Вы разблокированы", alert=True, url=None)
            return SimpleNamespace(message="Неверно, попробуйте ещё раз", alert=True, url=None)
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
            rows.append({"error": repr(result), "log": list(client.log)})
            continue
        rows.append(
            {
                "log": list(client.log),
                "text": str(result.get("text") or ""),
                "attempts": len(client.attempts),
                "sent": len(client.sent),
                "joined": client.joined,
                "verified": client.verified,
                "refusals": list(client.refusals),
                "stray": len(client.stray),
                "wrong_joins": list(client.wrong_joins),
                "wrong_clicks": list(client.wrong_clicks),
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


async def test_model_looks_around_before_commenting_in_a_group_with_a_captcha(
    weak_model: str,
) -> None:
    """Осмотр до действия: без слепых отправок, вступление, капча, затем комментарий."""
    rows = await outcomes(
        weak_model, lambda: DiscussionClient(refuse=None, requires_join=True, captcha=True)
    )
    print("\nнужно вступить и пройти капчу:", rows)  # noqa: T201

    check_errors(rows)
    done = count(rows, lambda row: row["joined"] and row["verified"] and row["sent"] >= 1)
    assert done >= ATTEMPTS * 5 // 8, f"{done}/{ATTEMPTS} дошли до комментария: {rows}"
    # Главное: комментарий не уходил вслепую и не упирался в отказ Telegram.
    blind = count(rows, lambda row: len(row["refusals"]) > 0)
    assert blind <= ATTEMPTS // 4, f"{blind}/{ATTEMPTS} получили отказ при отправке: {rows}"
    # И путь был верным: не в тот чат, не на то сообщение, не простой отправкой в канал.
    misdirected = count(
        rows, lambda row: row["stray"] > 0 or bool(row["wrong_joins"] or row["wrong_clicks"])
    )
    assert misdirected <= ATTEMPTS // 4, f"{misdirected}/{ATTEMPTS} действовали не туда: {rows}"
    duplicated = count(rows, lambda row: row["sent"] > 1)
    assert duplicated <= ATTEMPTS // 8, f"{duplicated}/{ATTEMPTS} продублировали: {rows}"
