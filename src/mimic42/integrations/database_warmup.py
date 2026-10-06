"""История и состояние прогрева.

История — это ``agent_events``: каждый начатый диалог — событие ``warmup.opener_sent`` (или
``warmup.opener_failed``) с текстом зачина и партнёром в payload. По ним считаются попытки за
день, уже использованные зачины и знакомые собеседники, и всё переживает рестарт.

Состояние ограничения аккаунта живёт в колонках ``agents.warmup_restricted_at`` и
``agents.warmup_recovery``, а не в ``agents.settings``: форма настроек перезаписывает
``settings`` целиком и затёрла бы то, что ведёт только сервер. Переходы состояния дополнительно
пишутся событиями (``warmup.restricted`` и др.) для ленты активности.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.warmup import (
    EVENT_OPENER_FAILED,
    EVENT_OPENER_SENT,
    EVENT_RECOVERED,
    EVENT_RECOVERY_STARTED,
    EVENT_RESTRICTED,
    WarmupState,
)
from mimic42.integrations.database_models import AgentEventModel, AgentModel

# Хватает с запасом на любую разумную базу зачинов и круг знакомых.
HISTORY_LIMIT = 1000
ATTEMPT_EVENTS = (EVENT_OPENER_SENT, EVENT_OPENER_FAILED)


async def load_warmup_state(session: AsyncSession, agent_id: UUID) -> WarmupState:
    """Состояние ограничения агента из колонок ``agents``."""
    row = (
        await session.execute(
            select(AgentModel.warmup_restricted_at, AgentModel.warmup_recovery).where(
                AgentModel.id == agent_id
            )
        )
    ).first()
    if row is None:
        return WarmupState()
    return WarmupState(restricted_at=row.warmup_restricted_at, recovery=row.warmup_recovery)


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
    """Переходы состояния: колонки ``agents`` и событие для ленты в одной транзакции."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load(self, agent_id: UUID) -> WarmupState:
        async with self._session_factory() as session:
            return await load_warmup_state(session, agent_id)

    async def record(
        self, agent_id: UUID, event_type: str, payload: dict[str, Any] | None = None
    ) -> None:
        """Применить переход. В отличие от ленты активности ошибка не глотается.

        Переход идемпотентен: повтор того же перехода (гонка двух отправок, повторное
        нажатие) не меняет колонки и не пишет второе событие.
        """
        async with self._session_factory() as session:
            changed = await self._apply(session, agent_id, event_type)
            if changed:
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

    @staticmethod
    async def _apply(session: AsyncSession, agent_id: UUID, event_type: str) -> bool:
        now = datetime.now().astimezone()
        target = AgentModel.id == agent_id
        if event_type == EVENT_RESTRICTED:
            statement = (
                update(AgentModel)
                .where(target, AgentModel.warmup_restricted_at.is_(None))
                .values(warmup_restricted_at=now, warmup_recovery=False)
            )
        elif event_type == EVENT_RECOVERY_STARTED:
            statement = (
                update(AgentModel)
                .where(
                    target,
                    AgentModel.warmup_restricted_at.is_not(None),
                    AgentModel.warmup_recovery.is_(False),
                )
                .values(warmup_recovery=True)
            )
        elif event_type == EVENT_RECOVERED:
            statement = (
                update(AgentModel)
                .where(target, AgentModel.warmup_restricted_at.is_not(None))
                .values(warmup_restricted_at=None, warmup_recovery=False)
            )
        else:
            raise ValueError(f"Неизвестный переход состояния прогрева: {event_type}")
        result = await session.execute(statement)
        return cast("CursorResult[Any]", result).rowcount > 0
