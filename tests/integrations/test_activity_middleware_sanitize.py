from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from langchain_core.messages import ToolMessage

from mimic42.integrations.activity_middleware import ActivityMiddleware, _sanitize_result


def test_data_urls_are_replaced_with_marker() -> None:
    result: dict[str, Any] = {
        "items": [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + "A" * 500}},
            {"type": "media_ref", "storage_path": "ag/1/x.jpeg"},
        ]
    }

    cleaned = _sanitize_result(result)

    assert cleaned is not None
    item = cleaned["items"][0]
    assert "_omitted" in item["image_url"]["url"]
    assert cleaned["items"][1] == {"type": "media_ref", "storage_path": "ag/1/x.jpeg"}


def test_short_strings_and_non_base64_are_kept() -> None:
    result: dict[str, Any] = {"text": "привет", "small": "data:x"}

    assert _sanitize_result(result) == result


def test_none_result_stays_none() -> None:
    assert _sanitize_result(None) is None


async def test_middleware_records_image_archive_without_logging_base64() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.events: list[dict[str, Any]] = []

        async def record(self, **kwargs: Any) -> None:
            self.events.append(kwargs)

    recorder = Recorder()
    middleware = ActivityMiddleware(agent_id=uuid4(), recorder=recorder)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    request: Any = SimpleNamespace(
        tool_call={"name": "view_image", "args": {"media_id": "photo:id"}, "id": "call-1"},
        runtime=SimpleNamespace(context=None),
    )
    image = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + "A" * 500}}
    ref = {
        "type": "media_ref",
        "kind": "photo",
        "storage_path": "ag/1/photo.jpeg",
        "mime_type": "image/jpeg",
    }

    async def handler(request: Any) -> ToolMessage:
        return ToolMessage(content=[image], artifact={"items": [ref]}, tool_call_id="call-1")

    response = await middleware.awrap_tool_call(request, handler)

    assert response.content == [image]
    event = recorder.events[0]
    assert event["status"] == "succeeded"
    assert event["result"]["items"][0] == ref
    assert "data:image/jpeg;base64," not in str(event["result"])
