from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from langchain.agents.middleware import ModelResponse
from langchain_core.messages import AIMessage

from mimic42.integrations.token_usage_middleware import TokenUsageMiddleware


class FakeRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def add(self, *, agent_id: Any, input_tokens: int, output_tokens: int) -> None:
        self.calls.append(
            {"agent_id": agent_id, "input_tokens": input_tokens, "output_tokens": output_tokens}
        )


def _ai_message(input_tokens: int, output_tokens: int) -> AIMessage:
    return AIMessage(
        content="ok",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )


async def test_middleware_sums_usage_across_messages() -> None:
    agent_id = uuid4()
    recorder = FakeRecorder()
    middleware = TokenUsageMiddleware(agent_id=agent_id, recorder=recorder)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    async def handler(request: Any) -> ModelResponse:
        return ModelResponse(result=[_ai_message(10, 2), _ai_message(5, 3)])

    await middleware.awrap_model_call(object(), handler)

    assert recorder.calls == [{"agent_id": agent_id, "input_tokens": 15, "output_tokens": 5}]


async def test_middleware_accepts_bare_ai_message() -> None:
    agent_id = uuid4()
    recorder = FakeRecorder()
    middleware = TokenUsageMiddleware(agent_id=agent_id, recorder=recorder)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    async def handler(request: Any) -> AIMessage:
        return _ai_message(7, 1)

    await middleware.awrap_model_call(object(), handler)

    assert recorder.calls == [{"agent_id": agent_id, "input_tokens": 7, "output_tokens": 1}]


async def test_middleware_skips_when_usage_metadata_absent() -> None:
    recorder = FakeRecorder()
    middleware = TokenUsageMiddleware(agent_id=uuid4(), recorder=recorder)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    async def handler(request: Any) -> ModelResponse:
        return ModelResponse(result=[AIMessage(content="ok")])

    await middleware.awrap_model_call(object(), handler)

    assert recorder.calls == []


async def test_middleware_does_not_record_model_failure() -> None:
    recorder = FakeRecorder()
    middleware = TokenUsageMiddleware(agent_id=uuid4(), recorder=recorder)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    async def failing_handler(request: Any) -> Any:
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        await middleware.awrap_model_call(object(), failing_handler)

    assert recorder.calls == []


async def test_middleware_survives_recorder_failure() -> None:
    from mimic42.core.token_usage import TokenUsageRecorder

    class BrokenFactory:
        def __call__(self) -> Any:
            raise RuntimeError("db down")

    middleware = TokenUsageMiddleware(
        agent_id=uuid4(),
        recorder=TokenUsageRecorder(BrokenFactory()),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    )

    async def handler(request: Any) -> ModelResponse:
        return ModelResponse(result=[_ai_message(3, 1)])

    response = await middleware.awrap_model_call(object(), handler)
    assert response.result[0].usage_metadata["input_tokens"] == 3
