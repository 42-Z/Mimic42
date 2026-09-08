from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from mimic42.integrations.mem0_memory import Mem0LongTermMemory


class FakeMem0Client:
    def __init__(self) -> None:
        self.added: list[tuple[object, dict[str, Any]]] = []
        self.deleted: list[str] = []
        self.deleted_all: list[dict[str, Any]] = []
        self.get_all_called_with: list[dict[str, Any]] = []

    async def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "results": [
                {"id": "mem-1", "memory": f"preference for {query}"},
                {"id": "mem-2", "ignored": "missing memory key"},
            ]
        }

    async def add(self, messages: object, **kwargs: Any) -> dict[str, Any]:
        self.added.append((messages, kwargs))
        return {"results": []}

    async def get_all(self, **kwargs: Any) -> dict[str, Any]:
        self.get_all_called_with.append(kwargs)
        return {
            "results": [
                {"id": "mem-1", "memory": "fact 1"},
                {"id": "mem-2", "memory": "fact 2"},
            ]
        }

    async def delete(self, memory_id: str) -> dict[str, Any]:
        self.deleted.append(memory_id)
        return {"message": "deleted"}

    async def delete_all(self, **kwargs: Any) -> dict[str, Any]:
        self.deleted_all.append(kwargs)
        return {"message": "deleted all"}

    async def history(self, memory_id: str) -> list[dict[str, Any]]:
        return [
            {"id": "hist-1", "memory_id": memory_id, "new_value": "new"},
            {"id": "hist-2", "memory_id": memory_id, "prev_value": "old"},
        ]


@pytest.mark.asyncio
async def test_mem0_memory_searches_and_saves_by_agent_id() -> None:
    client = FakeMem0Client()
    memory = Mem0LongTermMemory(client)
    agent_id = uuid4()

    memories = await memory.search(agent_id=agent_id, query="tea")
    await memory.save_turn(agent_id=agent_id, user_text="hello", assistant_text="hi")

    assert memories == ["preference for tea"]
    assert client.added == [
        (
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
            {"user_id": str(agent_id)},
        )
    ]


@pytest.mark.asyncio
async def test_mem0_memory_crud_methods() -> None:
    client = FakeMem0Client()
    memory = Mem0LongTermMemory(client)
    agent_id = uuid4()

    # Test get_all_memories
    all_mems = await memory.get_all_memories(agent_id)
    assert len(all_mems) == 2
    assert all_mems[0]["memory"] == "fact 1"
    assert client.get_all_called_with == [{"filters": {"user_id": str(agent_id)}}]

    # Test search_memories
    search_mems = await memory.search_memories(agent_id, "coffee")
    assert len(search_mems) == 2
    assert search_mems[0]["memory"] == "preference for coffee"

    # Test get_memory_history
    hist = await memory.get_memory_history("mem-1")
    assert len(hist) == 2
    assert hist[0]["new_value"] == "new"
