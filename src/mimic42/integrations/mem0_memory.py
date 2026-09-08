from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, cast
from uuid import UUID

from mem0 import AsyncMemoryClient


class Mem0ClientLike(Protocol):
    async def search(self, query: str, **kwargs: object) -> dict[str, Any]: ...

    async def add(self, messages: object, **kwargs: object) -> dict[str, Any]: ...

    async def get_all(self, **kwargs: object) -> dict[str, Any]: ...

    async def delete(self, memory_id: str) -> dict[str, Any]: ...

    async def delete_all(self, **kwargs: object) -> dict[str, Any]: ...

    async def history(self, memory_id: str) -> list[dict[str, Any]]: ...


class Mem0LongTermMemory:
    def __init__(self, client: Mem0ClientLike) -> None:
        self._client = client

    async def search(self, *, agent_id: UUID, query: str) -> list[str]:
        result = await self._client.search(query, filters={"user_id": str(agent_id)})
        memories = _extract_results(result)
        return [memory for memory in memories if memory]

    async def save_turn(
        self,
        *,
        agent_id: UUID,
        user_text: str,
        assistant_text: str,
    ) -> None:
        await self._client.add(
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": assistant_text},
            ],
            user_id=str(agent_id),
        )

    async def get_all_memories(self, agent_id: UUID) -> list[dict[str, Any]]:
        result = await self._client.get_all(filters={"user_id": str(agent_id)})
        if isinstance(result, dict):
            return result.get("results", [])
        return []

    async def search_memories(self, agent_id: UUID, query: str) -> list[dict[str, Any]]:
        result = await self._client.search(query, filters={"user_id": str(agent_id)})
        if isinstance(result, dict):
            return result.get("results", [])
        return []

    async def get_memory_history(self, memory_id: str) -> list[dict[str, Any]]:
        result = await self._client.history(memory_id)
        if isinstance(result, list):
            return result
        return []

    async def clear_all_memories(self, agent_id: UUID) -> None:
        await self._client.delete_all(user_id=str(agent_id))


def build_mem0_memory(api_key: str | None) -> Mem0LongTermMemory | None:
    if not api_key:
        return None
    return Mem0LongTermMemory(AsyncMemoryClient(api_key=api_key))


def _extract_results(result: object) -> list[str]:
    if not isinstance(result, Mapping):
        return []
    result_map = cast("Mapping[str, Any]", result)
    raw_results = result_map.get("results")
    if not isinstance(raw_results, list):
        return []

    memories: list[str] = []
    for item in raw_results:
        if isinstance(item, str):
            memories.append(item)
        elif isinstance(item, Mapping):
            item_map = cast("Mapping[str, Any]", item)
            memory = item_map.get("memory")
            if isinstance(memory, str):
                memories.append(memory)
    return memories
