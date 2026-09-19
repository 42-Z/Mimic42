from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import func

from mimic42.integrations.database_models import AgentTokenUsageModel

logger = logging.getLogger("mimic42.token_usage")


class TokenUsageRecorder:
    """Adds model token usage to the lifetime per-agent counters.

    The recorder must never break an agent turn: every write runs in its own
    session and every failure is downgraded to a warning.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, *, agent_id: UUID, input_tokens: int, output_tokens: int) -> None:
        try:
            stmt = pg_insert(AgentTokenUsageModel).values(
                agent_id=agent_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[AgentTokenUsageModel.agent_id],
                set_={
                    "input_tokens": AgentTokenUsageModel.input_tokens + stmt.excluded.input_tokens,
                    "output_tokens": AgentTokenUsageModel.output_tokens
                    + stmt.excluded.output_tokens,
                    "updated_at": func.now(),
                },
            )
            async with self._session_factory() as db_session:
                await db_session.execute(stmt)
                await db_session.commit()
        except Exception:
            logger.warning(
                "Failed to record token usage for agent %s",
                agent_id,
                exc_info=True,
            )
