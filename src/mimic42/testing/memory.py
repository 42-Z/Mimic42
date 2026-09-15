"""Поддельная долгосрочная память.

Mem0 — внешний сервис, в тестах он не поднимается. Вместо HTTP-клиента
стоит объект в памяти с тем же набором методов, который видят маршруты
памяти и ``RuntimeMemoryService``: поведение API остаётся настоящим,
подменяется только хранилище.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


class FakeLongTermMemory:
    def __init__(self) -> None:
        self._memories: dict[UUID, list[dict[str, Any]]] = {}

    async def search(self, *, agent_id: UUID, query: str) -> list[str]:
        needle = query.strip().lower()
        return [
            str(item["memory"])
            for item in self._memories.get(agent_id, [])
            if not needle or needle in str(item["memory"]).lower()
        ]

    async def save_turn(
        self,
        *,
        agent_id: UUID,
        user_text: str,
        assistant_text: str,
    ) -> None:
        if not user_text and not assistant_text:
            return
        entry = {
            "id": str(uuid4()),
            "memory": f"{user_text} ↔ {assistant_text}",
            "created_at": datetime.now(UTC).isoformat(),
        }
        self._memories.setdefault(agent_id, []).append(entry)

    async def get_all_memories(self, agent_id: UUID) -> list[dict[str, Any]]:
        return list(self._memories.get(agent_id, []))

    async def search_memories(self, agent_id: UUID, query: str) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        return [
            item
            for item in self._memories.get(agent_id, [])
            if not needle or needle in str(item["memory"]).lower()
        ]

    async def get_memory_history(self, memory_id: str) -> list[dict[str, Any]]:
        return []

    async def clear_all_memories(self, agent_id: UUID) -> None:
        self._memories.pop(agent_id, None)
