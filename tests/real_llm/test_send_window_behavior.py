"""Понимает ли слабая модель шапку про медленный режим.

Механика окна проверена модульными тестами, но решение принимает модель:
именно она читает шапку и выбирает, тратить слот или молчать. Каждый
сценарий гоняется несколько раз — модель недетерминирована, а нужен худший
случай, а не удачный прогон.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    _batch_header,
    _extract_structured_response,
)
from mimic42.core.onboarding import load_default_system_prompt
from mimic42.core.send_window import SendWindow
from mimic42.integrations.langchain_agent import build_langchain_agent

pytestmark = pytest.mark.real_llm

ATTEMPTS = 5
CALL_TIMEOUT = 120.0  # зациклившаяся модель может генерировать бесконечно
REQUIRED = 3  # из ATTEMPTS: планка слабой модели, а не идеал


def block(message_id: int, sender: str, text: str, chat: str = 'Группа "Тусовка"') -> str:
    """Один входящий в том же формате, что собирает _format_incoming."""
    return (
        "[Входящее сообщение]\n"
        "Время: 2026-09-20 18:00:00\n"
        f"Чат: {chat}\n"
        f"Отправитель: {sender}\n"
        f"ID сообщения: {message_id}\n"
        f"Содержимое: {text}"
    )


def batch(blocks: list[str], window: SendWindow | None) -> str:
    return _batch_header(len(blocks), window) + "\n\n".join(blocks)


SLOW = SendWindow(slowmode_seconds=30)

FLOOD = batch(
    [
        block(101, "Аня (@anya, ID: 1)", "кто-нибудь видел мой зарядник"),
        block(102, "Боря (@boris, ID: 2)", "не видел"),
        block(103, "Вика (@vika, ID: 3)", "Мимик, а во сколько завтра собираемся"),
        block(104, "Аня (@anya, ID: 1)", "нашла, был в сумке"),
        block(105, "Вика (@vika, ID: 3)", "эй, Мимик, ты тут? во сколько завтра"),
    ],
    SLOW,
)

NOT_FOR_AGENT = batch(
    [
        block(201, "Аня (@anya, ID: 1)", "Боря, скинь пожалуйста акт за август", 'Группа "Работа"'),
        block(202, "Боря (@boris, ID: 2)", "сейчас найду", 'Группа "Работа"'),
        block(203, "Боря (@boris, ID: 2)", "держи, там же и сентябрьский", 'Группа "Работа"'),
    ],
    SLOW,
)

SINGLE_FOR_AGENT = batch(
    [block(301, "Вика (@vika, ID: 3)", "Мимик, привет! как дела вообще?")],
    SLOW,
)


async def run_turn(model: str, text: str) -> dict[str, Any]:
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
    agent = build_langchain_agent(config, tools=[])
    response = await asyncio.wait_for(
        agent.ainvoke({"messages": [{"role": "user", "content": text}]}), CALL_TIMEOUT
    )
    # structured_response приходит экземпляром AgentResponse, а не словарём.
    structured = _extract_structured_response(response)
    assert structured is not None, "модель не вернула структурированный ответ"
    return structured


async def pass_rate(
    model: str, text: str, ok: Callable[[dict[str, Any]], bool]
) -> tuple[int, list[dict[str, Any]]]:
    outcomes = await asyncio.gather(
        *(run_turn(model, text) for _ in range(ATTEMPTS)), return_exceptions=True
    )
    # Сбой вызова (таймаут, отказ провайдера) — проваленная попытка, а не падение теста.
    results = [
        outcome if isinstance(outcome, dict) else {"error": repr(outcome)} for outcome in outcomes
    ]
    return sum(1 for result in results if "error" not in result and ok(result)), results


async def test_flood_addressed_to_the_agent_gets_a_sane_reply(weak_model: str) -> None:
    passed, results = await pass_rate(
        weak_model,
        FLOOD,
        # reply_to может быть пустым — его достроит рантайм (fallback_reply_to), но
        # выдуманный ID вне пачки дал бы ответ на несуществующее сообщение.
        lambda r: (
            r["send_any_message"] is True
            and r["reply_to"] in (None, 101, 102, 103, 104, 105)
            and len(r["text"]) <= 4096
        ),
    )
    assert passed >= REQUIRED, f"{passed}/{ATTEMPTS}, ответы модели: {results}"


async def test_talk_not_addressed_to_the_agent_stays_silent(weak_model: str) -> None:
    passed, results = await pass_rate(
        weak_model, NOT_FOR_AGENT, lambda r: r["send_any_message"] is False
    )
    assert passed >= REQUIRED, f"{passed}/{ATTEMPTS}, агент влез в чужой разговор: {results}"


async def test_slow_mode_header_does_not_make_the_agent_mute(weak_model: str) -> None:
    """Шапка про кд не должна отбивать желание отвечать тому, кто обратился напрямую."""
    passed, results = await pass_rate(
        weak_model, SINGLE_FOR_AGENT, lambda r: r["send_any_message"] is True
    )
    assert passed >= REQUIRED, (
        f"{passed}/{ATTEMPTS}, агент промолчал на прямое обращение: {results}"
    )


# Уведомление о запрете писать здесь намеренно не проверяется: слабая модель отвечает
# на любой входящий текст, как ни формулируй (замер: «текущее» 7/8, «явное» 6/8 ответов).
# Молчание в закрытом чате обеспечивает не модель, а предохранитель рантайма —
# он покрыт tests/core/test_send_window_runtime.py.
