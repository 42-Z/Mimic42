"""История прогрева из ``agent_events``: отдельной таблицы не нужно.

Каждый начатый диалог — событие ``warmup.opener_sent`` (или ``warmup.opener_failed``)
с текстом зачина и партнёром в payload. По ним считаются диалоги за день,
уже использованные зачины и знакомые собеседники, и всё переживает рестарт.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.warmup import EVENT_OPENER_FAILED, EVENT_OPENER_SENT
from mimic42.integrations.database_models import AgentEventModel, AgentModel

# Хватает с запасом на любую разумную базу зачинов и круг знакомых.
HISTORY_LIMIT = 1000


class DatabaseWarmupHistory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def attempts_since(self, agent_id: UUID, since: datetime) -> int:
        async with self._session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(AgentEventModel)
                .where(
                    AgentEventModel.agent_id == agent_id,
                    AgentEventModel.event_type.in_((EVENT_OPENER_SENT, EVENT_OPENER_FAILED)),
                    AgentEventModel.created_at >= since,
                )
            )
        return int(count or 0)

    async def received_since(self, agent_id: UUID, since: datetime) -> int:
        async with self._session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(AgentEventModel)
                .where(
                    AgentEventModel.event_type == EVENT_OPENER_SENT,
                    AgentEventModel.created_at >= since,
                    AgentEventModel.payload["partner_agent_id"].as_string() == str(agent_id),
                )
            )
        return int(count or 0)

    async def used_openers(self, agent_id: UUID) -> list[str]:
        payloads = await self._sent_payloads(agent_id)
        return [text for p in payloads if isinstance(text := p.get("text"), str)]

    async def recent_partners(self, agent_id: UUID) -> list[UUID]:
        partners: list[UUID] = []
        for payload in await self._sent_payloads(agent_id):
            raw = payload.get("partner_agent_id")
            try:
                partners.append(UUID(str(raw)))
            except ValueError:
                continue
        return partners[-20:]

    async def _sent_payloads(self, agent_id: UUID) -> list[dict[str, object]]:
        """Payload отправленных зачинов, от старых к новым."""
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(AgentEventModel.payload)
                .where(
                    AgentEventModel.agent_id == agent_id,
                    AgentEventModel.event_type == EVENT_OPENER_SENT,
                )
                .order_by(AgentEventModel.created_at.desc())
                .limit(HISTORY_LIMIT)
            )
            return [dict(payload or {}) for payload in reversed(list(rows))]


class DatabaseWarmupStateStore:
    """Состояние ограничения живёт в ``agents.settings["warmup"]`` рядом с остальным прогревом."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save_state(
        self, agent_id: UUID, *, restricted_at: datetime | None, recovery: bool
    ) -> None:
        async with self._session_factory() as session:
            # Блокировка строки: дашборд сохраняет настройки в тот же JSON.
            settings = await session.scalar(
                select(AgentModel.settings).where(AgentModel.id == agent_id).with_for_update()
            )
            merged: dict[str, Any] = dict(settings or {})
            warmup: dict[str, Any] = dict(merged.get("warmup") or {})
            warmup["recovery"] = recovery
            if restricted_at is None:
                warmup.pop("restricted_at", None)
            else:
                warmup["restricted_at"] = restricted_at.isoformat()
            merged["warmup"] = warmup
            await session.execute(
                update(AgentModel).where(AgentModel.id == agent_id).values(settings=merged)
            )
            await session.commit()
