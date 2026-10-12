from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from mimic42.integrations.tool_image_middleware import (
    IMAGE_NEXT_MESSAGE,
    IMAGES_TITLE,
    ToolImageMiddleware,
    move_tool_images_to_user_messages,
)

PICTURE = {"type": "image_url", "image_url": {"url": "data:image/webp;base64,AAAA"}}
OTHER_PICTURE = {"type": "image_url", "image_url": {"url": "data:image/webp;base64,BBBB"}}


def _call(call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"id": call_id, "name": "view_image", "args": {"media_id": call_id}}],
    )


def _pictures_message(*pictures: dict[str, Any]) -> HumanMessage:
    return HumanMessage(content=[{"type": "text", "text": IMAGES_TITLE}, *pictures])


def test_picture_of_a_tool_result_goes_to_a_user_message_after_the_tool_block() -> None:
    question = HumanMessage(content="что на стикере?")
    call = _call("c1")
    answer = AIMessage(content="вижу")
    messages = [question, call, ToolMessage(content=[PICTURE], tool_call_id="c1"), answer]

    assert move_tool_images_to_user_messages(messages) == [
        question,
        call,
        ToolMessage(content=IMAGE_NEXT_MESSAGE, tool_call_id="c1"),
        _pictures_message(PICTURE),
        answer,
    ]


def test_pictures_of_one_tool_block_share_a_single_user_message() -> None:
    question = HumanMessage(content="сравни")
    calls = AIMessage(
        content="",
        tool_calls=[
            {"id": "c1", "name": "view_image", "args": {"media_id": "a"}},
            {"id": "c2", "name": "view_image", "args": {"media_id": "b"}},
        ],
    )
    messages = [
        question,
        calls,
        ToolMessage(content=[PICTURE], tool_call_id="c1"),
        ToolMessage(content=[OTHER_PICTURE], tool_call_id="c2"),
    ]

    assert move_tool_images_to_user_messages(messages) == [
        question,
        calls,
        ToolMessage(content=IMAGE_NEXT_MESSAGE, tool_call_id="c1"),
        ToolMessage(content=IMAGE_NEXT_MESSAGE, tool_call_id="c2"),
        _pictures_message(PICTURE, OTHER_PICTURE),
    ]


def test_list_content_without_pictures_becomes_plain_text() -> None:
    question = HumanMessage(content="скачай")
    call = _call("c1")
    messages = [
        question,
        call,
        ToolMessage(
            content=[{"type": "text", "text": "Не удалось скачать медиа."}], tool_call_id="c1"
        ),
    ]

    assert move_tool_images_to_user_messages(messages) == [
        question,
        call,
        ToolMessage(content="Не удалось скачать медиа.", tool_call_id="c1"),
    ]


def test_messages_without_list_content_are_unchanged() -> None:
    messages = [
        HumanMessage(content="q"),
        AIMessage(content="a"),
        ToolMessage(content="ok", tool_call_id="c1"),
    ]

    assert move_tool_images_to_user_messages(messages) == messages


def test_picture_of_the_last_tool_result_is_sent_after_it() -> None:
    question = HumanMessage(content="что там?")
    call = _call("c1")
    messages = [question, call, ToolMessage(content=[PICTURE], tool_call_id="c1")]

    assert move_tool_images_to_user_messages(messages) == [
        question,
        call,
        ToolMessage(content=IMAGE_NEXT_MESSAGE, tool_call_id="c1"),
        _pictures_message(PICTURE),
    ]


def test_input_messages_are_not_modified() -> None:
    tool = ToolMessage(content=[PICTURE], tool_call_id="c1")

    move_tool_images_to_user_messages([HumanMessage(content="q"), _call("c1"), tool])

    assert tool.content == [PICTURE]


class _Request:
    def __init__(self, messages: list[Any]) -> None:
        self.messages = messages

    def override(self, **changes: Any) -> _Request:
        return _Request(changes["messages"])


async def test_middleware_hands_transformed_messages_to_the_model() -> None:
    seen: list[list[Any]] = []

    async def handler(request: _Request) -> str:
        seen.append(request.messages)
        return "response"

    request = _Request(
        [HumanMessage(content="q"), _call("c1"), ToolMessage(content=[PICTURE], tool_call_id="c1")]
    )

    result = await ToolImageMiddleware().awrap_model_call(request, handler)

    assert result == "response"
    assert seen == [
        [
            HumanMessage(content="q"),
            _call("c1"),
            ToolMessage(content=IMAGE_NEXT_MESSAGE, tool_call_id="c1"),
            _pictures_message(PICTURE),
        ]
    ]
