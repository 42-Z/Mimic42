from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from mimic42.core.memory import (
    MemoryMessage,
    MemoryRole,
    RuntimeMemoryService,
)


class FakeShortTermMemory:
    def __init__(self, messages: list[MemoryMessage]) -> None:
        self._messages = messages
        self.saved_messages: list[list[dict[str, Any]]] = []

    async def load_recent_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        since: datetime,
    ) -> list[dict[str, Any]]:
        return [
            {
                "type": "human" if message.role == MemoryRole.USER else "ai",
                "role": message.role.value,
                "content": message.content,
            }
            for message in self._messages
            if message.agent_id == agent_id and message.peer == peer and message.created_at >= since
        ]

    async def save_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        messages: list[dict[str, Any]],
        structured_response: dict[str, Any] | None = None,
        turn_id: str | None = None,
        thread_id: UUID | None = None,
    ) -> None:
        self.saved_messages.append(messages)


class FakeLongTermMemory:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str]] = []

    async def search(self, *, agent_id: UUID, query: str) -> list[str]:
        return [f"remembered:{query}"]

    async def save_turn(self, *, agent_id, user_text: str, assistant_text: str) -> None:  # noqa: ANN001
        self.saved.append((str(agent_id), user_text, assistant_text))


@pytest.mark.asyncio
async def test_memory_service_filters_three_hour_context_and_adds_long_term_context() -> None:
    agent_id = uuid4()
    now = datetime(2026, 5, 19, 20, 0, tzinfo=UTC)
    short_term = FakeShortTermMemory(
        [
            MemoryMessage(
                agent_id=agent_id,
                peer="chat",
                role=MemoryRole.USER,
                content="old",
                created_at=now - timedelta(hours=4),
            ),
            MemoryMessage(
                agent_id=agent_id,
                peer="chat",
                role=MemoryRole.ASSISTANT,
                content="recent",
                created_at=now - timedelta(minutes=10),
            ),
        ]
    )
    service = RuntimeMemoryService(
        short_term=short_term,
        long_term=FakeLongTermMemory(),
        now=lambda: now,
    )

    messages = await service.build_messages(
        agent_id=agent_id,
        peer="chat",
        user_text="hello",
    )

    assert messages == [
        {
            "type": "system",
            "role": "system",
            "content": "Long-term memory:\n- remembered:hello",
        },
        {"type": "ai", "role": "assistant", "content": "recent"},
        {"type": "human", "role": "user", "content": "hello"},
    ]


@pytest.mark.asyncio
async def test_memory_service_enforces_token_limit_from_newest_messages() -> None:
    agent_id = uuid4()
    now = datetime(2026, 5, 19, 20, 0, tzinfo=UTC)
    short_term = FakeShortTermMemory(
        [
            MemoryMessage(
                agent_id=agent_id,
                peer="chat",
                role=MemoryRole.USER,
                content="first",
                created_at=now - timedelta(minutes=3),
            ),
            MemoryMessage(
                agent_id=agent_id,
                peer="chat",
                role=MemoryRole.ASSISTANT,
                content="second",
                created_at=now - timedelta(minutes=2),
            ),
        ]
    )
    service = RuntimeMemoryService(
        short_term=short_term,
        long_term=None,
        max_context_tokens=2,
        token_counter=lambda text: 1,
        now=lambda: now,
    )

    messages = await service.build_messages(
        agent_id=agent_id,
        peer="chat",
        user_text="current",
    )

    assert messages == [
        {"type": "ai", "role": "assistant", "content": "second"},
        {"type": "human", "role": "user", "content": "current"},
    ]


@pytest.mark.asyncio
async def test_memory_service_saves_turn_to_short_and_long_term() -> None:
    agent_id = uuid4()
    short_term = FakeShortTermMemory([])
    long_term = FakeLongTermMemory()
    service = RuntimeMemoryService(short_term=short_term, long_term=long_term)

    input_msgs = [{"role": "user", "content": "hello"}]
    output_msgs = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    await service.save_messages(
        agent_id=agent_id,
        peer="chat",
        input_messages=input_msgs,
        output_messages=output_msgs,
    )

    # The incoming user message is persisted explicitly; the assistant
    # reply comes from the new-messages diff.
    assert len(short_term.saved_messages) == 1
    assert short_term.saved_messages[0] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    assert long_term.saved == [(str(agent_id), "hello", "hi")]


class FailingLongTermMemory:
    async def search(self, *, agent_id: UUID, query: str) -> list[str]:
        return []

    async def save_turn(self, *, agent_id, user_text: str, assistant_text: str) -> None:  # noqa: ANN001
        raise RuntimeError("Mem0 is down")


@pytest.mark.asyncio
async def test_memory_service_gracefully_handles_long_term_error() -> None:
    agent_id = uuid4()
    short_term = FakeShortTermMemory([])
    service = RuntimeMemoryService(
        short_term=short_term,
        long_term=FailingLongTermMemory(),
    )

    input_msgs = [{"role": "user", "content": "hello"}]
    output_msgs = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    # Should not raise — short-term memory still saved
    await service.save_messages(
        agent_id=agent_id,
        peer="chat",
        input_messages=input_msgs,
        output_messages=output_msgs,
    )

    assert len(short_term.saved_messages) == 1
