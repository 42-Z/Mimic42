"""Can the real agent read Rose's CAPTCHA instead of guessing a callback?

The three photos and answer grids come from the September 29 trace. Telegram
is not contacted: tools replay the relevant replies and record what the agent
does, while the configured OpenRouter model still sees the actual JPEGs.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, StructuredTool

from mimic42.core.agent_runtime import AgentRuntimeConfig, _extract_structured_response
from mimic42.core.onboarding import load_default_system_prompt
from mimic42.integrations.langchain_agent import LangChainGraphAgent, build_langchain_agent
from mimic42.integrations.telegram_tools import SendWindowClosed, _tool_failure

pytestmark = pytest.mark.real_llm

TRACE_MODEL = "z-ai/glm-5.3-flash"
CALL_TIMEOUT = 180.0
BOT = "MissRose_bot"
GROUP_ID = "12345"
CAPTCHA_MESSAGE_ID = 767
WALT_MESSAGE_ID = 528923
CAPTCHA_DIR = Path(__file__).parent / "fixtures" / "rose"
CAPTCHAS = (
    ("mimic42-cap-1.jpg", 1001, ("16", "87", "78", "-18", "22", "-36", "56", "42", "95"), "56"),
    ("mimic42-cap-2.jpg", 1002, ("26", "44", "42", "1", "21", "89", "91", "-36", "-53"), "21"),
    ("mimic42-cap-3.jpg", 1003, ("-51", "-36", "-17", "8", "-24", "-46", "44", "-46", "-28"), "8"),
)
RESTRICTED_ERROR = str(SendWindowClosed("restricted", None))


def _is_group(peer: str) -> bool:
    return peer.lstrip("-") in (GROUP_ID, f"100{GROUP_ID}")


class RoseScenario:
    """Replay the Telegram tool results from the trace, without a client."""

    def __init__(
        self,
        photo: str,
        photo_id: int,
        options: tuple[str, ...],
        answer: str,
        restricted: bool = False,
    ) -> None:
        self.photo = photo
        self.media_id = f"photo:{photo_id}:2000:0102:4"
        self.options = options
        self.answer = answer
        self.restricted = restricted
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.clicked: list[str] = []
        self.sent: list[dict[str, Any]] = []

    def _solved(self) -> bool:
        return bool(self.clicked) and self.clicked[0] == self.answer

    def tools(self) -> list[BaseTool]:
        async def get_messages(
            peer: str, limit: int = 20, offset_id: int = 0
        ) -> list[dict[str, Any]]:
            """Get recent messages in a chat, including photo media IDs."""
            self.calls.append(
                ("get_messages", {"peer": peer, "limit": limit, "offset_id": offset_id})
            )
            if _is_group(peer):
                return [
                    {
                        "id": WALT_MESSAGE_ID,
                        "sender_id": 609517172,
                        "date": "2026-10-01T08:27:51+00:00",
                        "text": (
                            "Луи MAGNUM, привет! Здесь мы обсуждаем новости сервиса и индустрии."
                        ),
                        "has_buttons": True,
                    }
                ]
            if peer.lstrip("@") == BOT:
                if self.clicked:
                    return [
                        {
                            "id": CAPTCHA_MESSAGE_ID,
                            "text": (
                                "CAPTCHA passed. You can chat."
                                if self.clicked[0] == self.answer
                                else "CAPTCHA failed - please try again. 2/3 attempts remaining."
                            ),
                            "has_buttons": False,
                        }
                    ]
                return [
                    {
                        "id": CAPTCHA_MESSAGE_ID,
                        "sender_id": 500,
                        "date": "2026-09-29T07:09:19+00:00",
                        "text": (
                            f"[Фото id={self.media_id}] "
                            "Please complete the above CAPTCHA! You have 3/3 tries left. "
                            "Note: If you can't see the full picture, try opening it."
                        ),
                        "has_buttons": True,
                    }
                ]
            return []

        async def get_message_buttons(peer: str, message_id: int) -> dict[str, Any]:
            """Get inline buttons and their callback data from a message."""
            self.calls.append(("get_message_buttons", {"peer": peer, "message_id": message_id}))
            if peer.lstrip("@") == BOT and message_id == CAPTCHA_MESSAGE_ID:
                return {
                    "buttons": [
                        {
                            "row": index // 3,
                            "column": index % 3,
                            "text": value,
                            "type": "KeyboardButtonCallback",
                            "data": f"captcha_{self.photo}_{index}",
                        }
                        for index, value in enumerate(self.options)
                    ]
                }
            if _is_group(peer) and message_id == WALT_MESSAGE_ID:
                return {
                    "buttons": [
                        {
                            "row": 0,
                            "column": 0,
                            "text": "Чтобы общаться в чате, нажмите на кнопку 💛",
                            "type": "KeyboardButtonUrl",
                            "url": f"https://t.me/{BOT}?start=captcha_-100{GROUP_ID}_X",
                        }
                    ]
                }
            return {"buttons": []}

        async def view_image(
            media_id: str,
        ) -> tuple[list[dict[str, Any]], None]:
            """View a photo by Media ID; return the actual JPEG as an image block."""
            self.calls.append(("view_image", {"media_id": media_id}))
            if media_id != self.media_id:
                return ([{"type": "text", "text": "Photo not found"}], None)
            jpeg = (CAPTCHA_DIR / self.photo).read_bytes()
            image_url = f"data:image/jpeg;base64,{base64.b64encode(jpeg).decode('ascii')}"
            return (
                [
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    }
                ],
                None,
            )

        async def click_inline_button(
            peer: str,
            message_id: int,
            button_data: str | None = None,
            button_index: int | None = None,
        ) -> dict[str, Any]:
            """Click a callback button using its data or zero-based index."""
            self.calls.append(
                (
                    "click_inline_button",
                    {
                        "peer": peer,
                        "message_id": message_id,
                        "button_data": button_data,
                        "button_index": button_index,
                    },
                )
            )
            if peer.lstrip("@") != BOT or message_id != CAPTCHA_MESSAGE_ID:
                return {"success": False, "error": "Message not found"}
            if button_data is not None:
                buttons = [f"captcha_{self.photo}_{i}" for i in range(len(self.options))]
                if button_data not in buttons:
                    return {"success": False, "error": "Invalid callback"}
                button_index = buttons.index(button_data)
            if button_index is None or not 0 <= button_index < len(self.options):
                return {"success": False, "error": "Invalid button index"}
            self.clicked.append(self.options[button_index])
            return {"success": True, "message": None, "alert": False, "url": None}

        async def send_text_message(
            peer: str,
            message: str,
            reply_to_msg_id: int | None = None,
            comment_to_msg_id: int | None = None,
        ) -> dict[str, Any]:
            """Send a text message; a restricted chat refuses until the captcha is solved."""
            self.calls.append(
                (
                    "send_text_message",
                    {
                        "peer": peer,
                        "message": message,
                        "reply_to_msg_id": reply_to_msg_id,
                        "comment_to_msg_id": comment_to_msg_id,
                    },
                )
            )
            if self.restricted and _is_group(peer) and not self._solved():
                return _tool_failure(SendWindowClosed("restricted", None))
            self.sent.append({"peer": peer, "text": message})
            return {"success": True, "message_id": 1000 + len(self.sent)}

        send_tools = (
            [StructuredTool.from_function(coroutine=send_text_message)] if self.restricted else []
        )
        return (
            send_tools
            + [
                StructuredTool.from_function(coroutine=fn)
                for fn in (get_messages, get_message_buttons, click_inline_button)
            ]
            + [
                StructuredTool.from_function(
                    coroutine=view_image,
                    response_format="content_and_artifact",
                )
            ]
        )


async def run_case(
    photo: str, photo_id: int, options: tuple[str, ...], answer: str
) -> dict[str, Any]:
    scenario = RoseScenario(photo, photo_id, options, answer)
    config = AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_session_string="sessions/real-llm",
        telegram_api_id=12345,
        telegram_api_hash="hash",
        llm_model=TRACE_MODEL,
        name="Walt Mimic",
        system_prompt=load_default_system_prompt(),
        soul_prompt="Ты обычный человек, пишешь коротко и неформально.",
    )
    agent = cast(LangChainGraphAgent, build_langchain_agent(config, tools=scenario.tools()))
    try:
        response = await asyncio.wait_for(
            agent.ainvoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "А там ничего не писал бот для верификации? "
                                "Для чата @yandexmusic_live от @MissRose_bot пришла капча — "
                                "попробуй пройти её.\n\n"
                                "[Входящее сообщение]\n"
                                "Время: 2026-09-29 07:09:19\n"
                                "Чат: ЛС с @MissRose_bot\n"
                                "Отправитель: Rose (@MissRose_bot, ID: 500)\n"
                                f"ID сообщения: {CAPTCHA_MESSAGE_ID}\n"
                                f"Содержимое: [Фото id={scenario.media_id}] "
                                "Please complete the above CAPTCHA! You have 3/3 tries left. "
                                "Note: If you can't see the full picture, try opening it."
                            ),
                        }
                    ]
                }
            ),
            CALL_TIMEOUT,
        )
    finally:
        await agent.aclose()

    assert isinstance(response, dict)
    messages = cast(dict[str, Any], response)["messages"]
    image_results = [
        message
        for message in messages
        if isinstance(message, ToolMessage) and message.name == "view_image"
    ]
    image_types = [
        [block["type"] for block in message.content]
        for message in image_results
        if isinstance(message.content, list)
    ]
    view_index = next(
        (
            index
            for index, call in enumerate(scenario.calls)
            if call == ("view_image", {"media_id": scenario.media_id})
        ),
        None,
    )
    button_index = next(
        (index for index, (name, _) in enumerate(scenario.calls) if name == "get_message_buttons"),
        None,
    )
    clicks = [
        index for index, (name, _) in enumerate(scenario.calls) if name == "click_inline_button"
    ]
    passed = (
        _extract_structured_response(response) is not None
        and ["image_url"] in image_types
        and view_index is not None
        and button_index is not None
        and bool(clicks)
        and min(clicks) > max(view_index, button_index)
        and scenario.clicked == [answer]
    )
    return {
        "photo": photo,
        "expected": answer,
        "clicked": scenario.clicked,
        "image_types": image_types,
        "passed": passed,
        "calls": scenario.calls,
    }


@pytest.mark.usefixtures("weak_model")  # loads .env and skips when no OpenRouter key exists
async def test_agent_reads_rose_captchas_before_clicking() -> None:
    rows = []
    for photo, photo_id, options, answer in CAPTCHAS:
        try:
            rows.append(await run_case(photo, photo_id, options, answer))
        except Exception as exc:
            rows.append({"photo": photo, "expected": answer, "error": repr(exc), "passed": False})
    print("\nRose CAPTCHA:", rows)  # noqa: T201 — tool calls matter when inspecting a real run

    # A real model may misread or decline one noisy photo; two correct,
    # image-backed first clicks distinguish vision from blind guesses.
    passed = sum(row["passed"] for row in rows)
    assert passed >= 2, f"{passed}/3 капчи пройдено: {rows}"


@pytest.mark.usefixtures("weak_model")  # loads .env and skips when no OpenRouter key exists
async def test_agent_self_solves_the_captcha_when_a_chat_refuses_writes() -> None:
    """Ход из трейса 2026-10-01: отправка заперта, агент сам ищет и решает капчу.

    Раньше модель игнорировала отказ отправки, отчитывалась об успехе и ждала
    подсказки владельца, вместо того чтобы заглянуть в историю чата.
    """
    photo, photo_id, options, answer = CAPTCHAS[0]
    scenario = RoseScenario(photo, photo_id, options, answer, restricted=True)
    config = AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_session_string="sessions/real-llm",
        telegram_api_id=12345,
        telegram_api_hash="hash",
        llm_model=TRACE_MODEL,
        name="Walt Mimic",
        system_prompt=load_default_system_prompt(),
        soul_prompt="Ты обычный человек, пишешь коротко и неформально.",
    )
    agent = cast(LangChainGraphAgent, build_langchain_agent(config, tools=scenario.tools()))
    try:
        response = await asyncio.wait_for(
            agent.ainvoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "[Контекст] Ты только что вступил в обсуждение канала "
                                "yandexmusic_live: группа «Чат Яндекс Музыки без музыки», "
                                f"ID: -100{GROUP_ID}.\n\n"
                                "[Входящее сообщение]\n"
                                "Время: 2026-10-01 08:27:43\n"
                                "Чат: ЛС\n"
                                "Отправитель: Владелец (@owner, ID: 42)\n"
                                "ID сообщения: 770\n"
                                "Содержимое: вступи в чат комментариев и поздоровайся"
                            ),
                        }
                    ]
                }
            ),
            CALL_TIMEOUT,
        )
    finally:
        await agent.aclose()

    assert isinstance(response, dict)
    assert _extract_structured_response(response) is not None
    greetings = [item for item in scenario.sent if _is_group(str(item["peer"]))]
    assert scenario.clicked == [answer], f"капча не решена; вызовы: {scenario.calls}"
    assert greetings, f"приветствие так и не отправлено: {scenario.calls}"
