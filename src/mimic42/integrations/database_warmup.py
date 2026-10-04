"""История и состояние прогрева из ``agent_events``: отдельной таблицы не нужно.

Каждый начатый диалог — событие ``warmup.opener_sent`` (или ``warmup.opener_failed``)
с текстом зачина и партнёром в payload. По ним считаются попытки за день, уже
использованные зачины и знакомые собеседники, и всё переживает рестарт.

Ограничение аккаунта и режим восстановления тоже события (``warmup.restricted``,
``warmup.recovery_started``, ``warmup.recovered``): журнал только дописывается, и форма
настроек, которая перезаписывает ``agents.settings`` целиком, не может откатить состояние.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.warmup import (
    EVENT_OPENER_FAILED,
    EVENT_OPENER_SENT,
    EVENT_RECOVERED,
    EVENT_RECOVERY_STARTED,
    EVENT_RESTRICTED,
    WarmupState,
    state_from_events,
)
from mimic42.integrations.database_models import AgentEventModel

# Хватает с запасом на любую разумную базу зачинов и круг знакомых.
HISTORY_LIMIT = 1000
ATTEMPT_EVENTS = (EVENT_OPENER_SENT, EVENT_OPENER_FAILED)
STATE_EVENTS = (EVENT_RESTRICTED, EVENT_RECOVERY_STARTED, EVENT_RECOVERED)


async def load_warmup_state(session: AsyncSession, agent_id: UUID) -> WarmupState:
    """Состояние ограничения агента по журналу событий."""
    rows = await session.execute(
        select(AgentEventModel.event_type, AgentEventModel.created_at)
        .where(AgentEventModel.agent_id == agent_id, AgentEventModel.event_type.in_(STATE_EVENTS))
        .order_by(AgentEventModel.created_at.asc())
    )
    return state_from_events((event_type, created_at) for event_type, created_at in rows)


class DatabaseWarmupHistory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def attempt_times_since(self, agent_id: UUID, since: datetime) -> list[datetime]:
        """Когда агент начинал диалоги с ``since`` (включая неудавшиеся)."""
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(AgentEventModel.created_at)
                .where(
                    AgentEventModel.agent_id == agent_id,
                    AgentEventModel.event_type.in_(ATTEMPT_EVENTS),
                    AgentEventModel.created_at >= since,
                )
                .order_by(AgentEventModel.created_at.asc())
            )
            return list(rows)

    async def received_times_since(self, agent_id: UUID, since: datetime) -> list[datetime]:
        """Когда другие агенты начинали диалоги с этим агентом с ``since``."""
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(AgentEventModel.created_at)
                .where(
                    AgentEventModel.event_type.in_(ATTEMPT_EVENTS),
                    AgentEventModel.created_at >= since,
                    AgentEventModel.payload["partner_agent_id"].as_string() == str(agent_id),
                )
                .order_by(AgentEventModel.created_at.asc())
            )
            return list(rows)

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
    """Состояние ограничения: чтение и запись событий-переходов."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load(self, agent_id: UUID) -> WarmupState:
        async with self._session_factory() as session:
            return await load_warmup_state(session, agent_id)

    async def record(
        self, agent_id: UUID, event_type: str, payload: dict[str, Any] | None = None
    ) -> None:
        """Записать переход состояния. В отличие от ленты активности ошибка не глотается."""
        async with self._session_factory() as session:
            now = datetime.now().astimezone()
            session.add(
                AgentEventModel(
                    agent_id=agent_id,
                    event_type=event_type,
                    status="succeeded",
                    payload=payload or {},
                    started_at=now,
                    completed_at=now,
                )
            )
            await session.commit()
