"""Страховка исполнения: вызов инструмента вне allowlist отклоняется."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

ToolCallHandler = Callable[[ToolCallRequest], Awaitable[Any]]


class ToolAccessMiddleware(AgentMiddleware):
    """Отклоняет вызовы инструментов, которых нет в allowlist агента.

    Каталог инструментов фильтруется ещё при сборке рантайма; эта проверка —
    второй барьер инварианта: имя вне allowlist не исполняется, даже если оно
    пришло не из отфильтрованного списка (например, модель назвала
    несуществующий инструмент или появился путь сборки без фильтра).
    """

    def __init__(self, enabled_tools: frozenset[str]) -> None:
        super().__init__()
        self._enabled_tools = enabled_tools

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: ToolCallHandler,
    ) -> Any:
        tool_name = request.tool_call.get("name", "unknown")
        if tool_name not in self._enabled_tools:
            return ToolMessage(
                content=f"Инструмент «{tool_name}» отключён в настройках агента.",
                name=tool_name,
                tool_call_id=request.tool_call.get("id") or "",
                status="error",
            )
        return await handler(request)
