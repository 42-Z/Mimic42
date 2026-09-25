"""Как слабая модель читает строку о своём первом комментарии под постом.

Комментарий под постом модель оставляет инструментом (``comment_to_msg_id``),
поэтому ей дан полный набор настоящих инструментов поверх клиента, который
только записывает отправки. Два сценария: обычный пост, где первого
комментария хватает, и пост с вопросом к подписчикам, где ответ по делу
уместен и строка не должна глушить агента.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

import pytest

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    _extract_structured_response,
    _first_comment_note,
)
from mimic42.core.first_comment import FirstCommentVariant
from mimic42.core.onboarding import load_default_system_prompt
from mimic42.integrations.langchain_agent import build_langchain_agent
from mimic42.integrations.telegram_tools import (
    TelethonRequestClient,
    build_telegram_langchain_tools,
)

pytestmark = pytest.mark.real_llm

ATTEMPTS = 10
CALL_TIMEOUT = 180.0
POST_ID = 57
FIRST = FirstCommentVariant(text="Первый!")


class RecordingClient:
    """Клиент Telethon, который ничего не шлёт, а только запоминает отправки."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def get_input_entity(self, peer: Any) -> Any:
        return peer

    async def get_entity(self, peer: Any) -> Any:
        return type("Entity", (), {"id": peer, "title": "Будни айтишника"})()

    async def send_message(self, entity: Any, message: str = "", **kwargs: Any) -> Any:
        self.sent.append({"entity": entity, "text": message, **kwargs})
        return type("Message", (), {"id": 900 + len(self.sent)})()

    async def send_file(self, entity: Any, file: Any, **kwargs: Any) -> Any:
        self.sent.append({"entity": entity, "file": file, **kwargs})
        return type("Message", (), {"id": 900 + len(self.sent)})()

    async def __call__(self, request: Any) -> Any:
        raise RuntimeError("В замере Telegram недоступен")


def post(text: str, note: str | None) -> str:
    """Пост канала в том же формате, что собирает _format_incoming."""
    return (
        "[Входящее сообщение]\n"
        "Время: 2026-09-25 10:00:00\n"
        'Чат: Канал "Будни айтишника"\n'
        "Отправитель: Будни айтишника (@it_budni, ID: 1987654321)\n"
        f"ID сообщения: {POST_ID}\n"
        f"Содержимое: {text}" + (f"\n{note}" if note else "")
    )


GENERIC = (
    "Понедельник, 10 утра, а прод уже лежит. Классика. Держитесь там, коллеги, "
    "и не деплойте в пятницу."
)
QUESTION = (
    "Вопрос к подписчикам: какой язык вы бы посоветовали первым для новичка в 2026 году? "
    "Пишите в комментариях, самые интересные ответы соберу в отдельный пост."
)


async def run_turn(model: str, text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    config = AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_session_string="sessions/real-llm",
        telegram_api_id=12345,
        telegram_api_hash="hash",
        llm_model=model,
        name="Мимик",
        system_prompt=load_default_system_prompt(),
        soul_prompt="Ты обычный человек, пишешь коротко и неформально.",
    )
    client = RecordingClient()
    tools = build_telegram_langchain_tools(cast(TelethonRequestClient, client))
    agent = build_langchain_agent(config, tools=tools)
    response = await asyncio.wait_for(
        agent.ainvoke({"messages": [{"role": "user", "content": text}]}), CALL_TIMEOUT
    )
    structured = _extract_structured_response(response)
    assert structured is not None, "модель не вернула структурированный ответ"
    return structured, client.sent


def comments(sent: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in sent if item.get("comment_to") == POST_ID]


async def outcomes(model: str, text: str) -> list[dict[str, Any]]:
    results = await asyncio.gather(
        *(run_turn(model, text) for _ in range(ATTEMPTS)), return_exceptions=True
    )
    rows: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, BaseException):
            rows.append({"error": repr(result)})
            continue
        structured, sent = result
        rows.append({"structured": structured, "comments": comments(sent), "sent": sent})
    return rows


def count(rows: list[dict[str, Any]], ok: Callable[[dict[str, Any]], bool]) -> int:
    return sum(1 for row in rows if "error" not in row and ok(row))


def _normalized(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def repeats_first(row: dict[str, Any]) -> bool:
    """«Первый!» ещё раз — слово в слово или в начале своего ответа."""
    return any(
        _normalized(str(item.get("text", ""))).startswith(_normalized(FIRST.text))
        for item in row["comments"]
    )


def check_run(rows: list[dict[str, Any]]) -> None:
    errors = sum(1 for row in rows if "error" in row)
    assert errors <= ATTEMPTS // 5, f"{errors}/{ATTEMPTS} прогонов упали: {rows}"
    # Прямая строка «твой первый комментарий: «…»» давала повтор в каждом
    # прогоне; ветка комментариев — дважды за тридцать прогонов. Планка слабой
    # модели, а не идеал: чаще раза из десяти — формулировка тянет к повтору.
    repeated = count(rows, repeats_first)
    assert repeated <= ATTEMPTS // 10, f"модель повторяет «Первый!»: {rows}"


async def test_first_comment_note_does_not_breed_a_second_blind_comment(weak_model: str) -> None:
    rows = await outcomes(weak_model, post(GENERIC, _first_comment_note(FIRST)))
    print("\nобычный пост:", rows)  # noqa: T201 — нужно при разборе прогона

    check_run(rows)
    # Слабая модель комментирует такой пост примерно в половине прогонов — и
    # со строкой о ветке (14 из 26), и без неё (8 из 16). Девять-десять из
    # десяти значат, что строка подталкивает комментировать вслепую.
    commented = count(rows, lambda row: bool(row["comments"]))
    assert commented <= ATTEMPTS * 8 // 10, f"{commented}/{ATTEMPTS} вторых комментариев: {rows}"


async def test_first_comment_note_does_not_mute_a_question_post(weak_model: str) -> None:
    rows = await outcomes(weak_model, post(QUESTION, _first_comment_note(FIRST)))
    print("\nпост-вопрос:", rows)  # noqa: T201

    check_run(rows)
    # Автор прямо зовёт в комментарии: ответ по делу уместен и после «Первый!».
    commented = count(rows, lambda row: bool(row["comments"]))
    assert commented >= ATTEMPTS // 5, f"{commented}/{ATTEMPTS}, строка заглушила агента: {rows}"
