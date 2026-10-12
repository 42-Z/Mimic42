from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage

IMAGE_NEXT_MESSAGE = "Изображение передано следующим сообщением."
IMAGES_TITLE = "Изображения из результатов инструментов:"

ModelCallHandler = Callable[[Any], Awaitable[Any]]


def _split_content(content: str | list[Any]) -> tuple[list[str], list[dict[str, Any]]]:
    if isinstance(content, str):
        return [content], []
    texts: list[str] = []
    pictures: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "image_url":
            pictures.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            texts.append(str(block.get("text", "")))
        else:
            texts.append(str(block))
    return texts, pictures


def _pictures_message(pictures: list[dict[str, Any]]) -> HumanMessage:
    return HumanMessage(content=[{"type": "text", "text": IMAGES_TITLE}, *pictures])


def move_tool_images_to_user_messages(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """Send the pictures of tool results in a user message after the tool block.

    Some OpenRouter providers ignore an image inside a tool message or reject
    list content there. Tool messages keep only text; their pictures go into one
    user message placed after the block of consecutive tool results.
    """
    moved: list[AnyMessage] = []
    pending: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, ToolMessage):
            texts, pictures = _split_content(message.content)
            if pictures or isinstance(message.content, list):
                if pictures:
                    texts.append(IMAGE_NEXT_MESSAGE)
                    pending.extend(pictures)
                message = message.model_copy(update={"content": "\n".join(texts)})
            moved.append(message)
            continue
        if pending:
            moved.append(_pictures_message(pending))
            pending = []
        moved.append(message)
    if pending:
        moved.append(_pictures_message(pending))
    return moved


class ToolImageMiddleware(AgentMiddleware):
    """Hands the model tool pictures in a user message, not in the tool message."""

    async def awrap_model_call(self, request: Any, handler: ModelCallHandler) -> Any:
        messages = move_tool_images_to_user_messages(request.messages)
        return await handler(request.override(messages=messages))
