"""Отключённый инструмент не должен выполниться даже из собранного рантайма."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from mimic42.integrations.tool_access_middleware import ToolAccessMiddleware


def _request(name: str) -> Any:
    return type("Request", (), {"tool_call": {"name": name, "args": {}, "id": "call-1"}})()


@pytest.mark.asyncio
async def test_blocks_tool_outside_allowlist() -> None:
    middleware = ToolAccessMiddleware(frozenset({"send_text_message"}))
    called = False

    async def handler(request: Any) -> Any:
        nonlocal called
        called = True
        return ToolMessage(content="ok", tool_call_id="call-1")

    result = await middleware.awrap_tool_call(_request("delete_messages"), handler)

    assert called is False
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "delete_messages" in str(result.content)


@pytest.mark.asyncio
async def test_passes_allowed_tool_through() -> None:
    middleware = ToolAccessMiddleware(frozenset({"send_text_message"}))
    sentinel = ToolMessage(content="ok", tool_call_id="call-1")

    async def handler(request: Any) -> Any:
        return sentinel

    assert await middleware.awrap_tool_call(_request("send_text_message"), handler) is sentinel


@pytest.mark.asyncio
async def test_empty_allowlist_blocks_everything() -> None:
    middleware = ToolAccessMiddleware(frozenset())

    async def handler(request: Any) -> Any:
        raise AssertionError("handler must not be called")

    result = await middleware.awrap_tool_call(_request("send_text_message"), handler)

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
