from __future__ import annotations

from typing import Any
from uuid import uuid4

from mimic42.core.token_usage import TokenUsageRecorder


async def test_token_usage_recorder_swallows_write_failure() -> None:
    class BrokenFactory:
        def __call__(self) -> Any:
            raise RuntimeError("db down")

    recorder = TokenUsageRecorder(BrokenFactory())  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    await recorder.add(agent_id=uuid4(), input_tokens=10, output_tokens=5)
