from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from mimic42.core.activity import ActivityRecorder

logger = logging.getLogger("mimic42.activity")

ModelCallHandler = Callable[[Any], Awaitable[Any]]
ToolCallHandler = Callable[[ToolCallRequest], Awaitable[Any]]


def _turn_fields(request: Any) -> tuple[str | None, str | None]:
    """Read per-turn identity (turn_id, peer) from the agent runtime context."""
    runtime = getattr(request, "runtime", None)
    context = getattr(runtime, "context", None)
    if context is None:
        return None, None
    turn_id = getattr(context, "turn_id", None)
    peer = getattr(context, "peer", None)
    if turn_id is None and peer is None:
        return None, None
    return turn_id, peer


def _parse_tool_output(content: Any) -> dict[str, Any] | list[Any] | None:
    """Parse a ToolMessage content into a dict or a list, if possible.

    LangChain serializes dict/list tool results to a JSON string before
    storing them in ``ToolMessage.content``.
    """
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (ValueError, TypeError):
            return None
    elif isinstance(content, (dict, list)):
        parsed = content
    else:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _classify_tool_output(content: Any) -> tuple[str, str | None, dict[str, Any] | None]:
    """Return (status, error, result) based on the tool output payload.

    ``ToolMessage.status`` stays "success" even when the tool returned
    ``{"success": false}``, so the outcome must be read from the content.
    List-shaped tools report failures as ``[{"success": false, ...}]``.
    """
    parsed = _parse_tool_output(content)
    if parsed is None:
        return "succeeded", None, None

    entries = parsed if isinstance(parsed, list) else [parsed]
    for entry in entries:
        if isinstance(entry, dict) and entry.get("success") is False:
            failure = entry if isinstance(parsed, dict) else {"items": parsed}
            return "failed", str(entry.get("error", "")), failure

    result = parsed if isinstance(parsed, dict) else {"items": parsed}
    return "succeeded", None, result


class ActivityMiddleware(AgentMiddleware):
    """Records tool calls and model failures to the agent activity log."""

    def __init__(
        self,
        *,
        agent_id: Any,
        recorder: ActivityRecorder,
    ) -> None:
        self._agent_id = agent_id
        self._recorder = recorder

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: ToolCallHandler,
    ) -> Any:
        tool_name = request.tool_call.get("name", "unknown")
        event_type = f"tool.{tool_name}"
        started_at = datetime.now(UTC)
        turn_id, peer = _turn_fields(request)
        try:
            response = await handler(request)
        except Exception as exc:
            await self._recorder.record(
                agent_id=self._agent_id,
                event_type=event_type,
                status="failed",
                payload={
                    "turn_id": turn_id,
                    "peer": peer,
                    "args": request.tool_call.get("args", {}),
                    "error_code": type(exc).__name__,
                },
                error=str(exc),
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )
            raise

        message = response if isinstance(response, ToolMessage) else None
        content = message.content if message is not None else None
        status, error, result = _classify_tool_output(content)
        if error is None and message is not None and message.status == "error":
            status = "failed"
            error = content if isinstance(content, str) else str(content)

        await self._recorder.record(
            agent_id=self._agent_id,
            event_type=event_type,
            status=status,
            payload={
                "turn_id": turn_id,
                "peer": peer,
                "args": request.tool_call.get("args", {}),
            },
            result=result,
            error=error,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
        return response

    async def awrap_model_call(
        self,
        request: Any,
        handler: ModelCallHandler,
    ) -> Any:
        try:
            return await handler(request)
        except Exception as exc:
            turn_id, peer = _turn_fields(request)
            await self._recorder.record(
                agent_id=self._agent_id,
                event_type="model.failed",
                status="failed",
                payload={"turn_id": turn_id, "peer": peer, "error_code": type(exc).__name__},
                error=str(exc),
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
            raise
