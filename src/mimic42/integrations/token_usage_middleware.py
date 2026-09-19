from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware

from mimic42.core.token_usage import TokenUsageRecorder

ModelCallHandler = Callable[[Any], Awaitable[Any]]


def _usage_totals(response: Any) -> tuple[int, int]:
    """Sum input/output tokens over every message of one model call.

    Handles both shapes an ``awrap_model_call`` handler may return: a
    ``ModelResponse`` (``result`` is a list) and a bare ``AIMessage``.
    """
    result = getattr(response, "result", None)
    messages = result if isinstance(result, list) else [response]
    input_tokens = 0
    output_tokens = 0
    for message in messages:
        usage = getattr(message, "usage_metadata", None)
        if not isinstance(usage, dict):
            continue
        input_tokens += int(usage.get("input_tokens") or 0)
        output_tokens += int(usage.get("output_tokens") or 0)
    return input_tokens, output_tokens


class TokenUsageMiddleware(AgentMiddleware):
    """Adds the token usage of every model call to the agent's lifetime counter."""

    def __init__(self, *, agent_id: Any, recorder: TokenUsageRecorder) -> None:
        self._agent_id = agent_id
        self._recorder = recorder

    async def awrap_model_call(self, request: Any, handler: ModelCallHandler) -> Any:
        response = await handler(request)
        input_tokens, output_tokens = _usage_totals(response)
        if input_tokens or output_tokens:
            await self._recorder.add(
                agent_id=self._agent_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        return response
