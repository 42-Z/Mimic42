"""План выборки событий хода должен идти по индексу ``payload->>'turn_id'``.

Лента (``DatabaseAgentStore.get_conversation``) выбирает события ходов
выражением ``agent_id = ... and payload->>'turn_id' in (...)``. Без индекса
PostgreSQL перебирает все события агента, а эндпоинт дергается
realtime-инвалидацией почти раз в секунду по всем загруженным страницам.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import insert, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.integrations.database_models import AgentEventModel, AgentModel
from mimic42.testing.slots import Slot

INDEX_NAME = "agent_events_agent_id_turn_id_idx"
TURN_COUNT = 40
EVENTS_PER_TURN = 100


async def _seed_turn_events(
    db_session_factory: async_sessionmaker[AsyncSession],
    owner_id: UUID,
) -> UUID:
    """Один агент с плотным журналом событий: нужен объём, чтобы перебор
    всех событий был заведомо дороже индексного доступа."""
    agent_id = uuid4()
    now = datetime.now(UTC)
    async with db_session_factory() as session:
        session.add(
            AgentModel(
                id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                soul_prompt="soul",
            )
        )
        await session.commit()
    async with db_session_factory() as session:
        await session.execute(
            insert(AgentEventModel),
            [
                {
                    "id": uuid4(),
                    "agent_id": agent_id,
                    "event_type": "tool.get_dialogs",
                    "status": "succeeded",
                    "payload": {"turn_id": f"t{i % TURN_COUNT}"},
                    "created_at": now - timedelta(seconds=i),
                }
                for i in range(TURN_COUNT * EVENTS_PER_TURN)
            ],
        )
        await session.commit()
    return agent_id


async def test_turn_events_query_uses_turn_id_index(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    agent_id = await _seed_turn_events(db_session_factory, clean_slot.persona("full").user_id)

    turn_ids = ["t0", "t1"]
    statement = (
        select(AgentEventModel)
        .where(AgentEventModel.agent_id == agent_id)
        .where(AgentEventModel.payload["turn_id"].as_string().in_(turn_ids))
        .order_by(AgentEventModel.created_at.asc(), AgentEventModel.id.asc())
    )
    compiled = statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )

    async with db_session_factory() as session:
        # Свежая статистика: план должен считаться по реальному объёму, а не
        # по пустой таблице.
        await session.execute(text(f"analyze public.{AgentEventModel.__tablename__}"))
        # Выключаем seqscan, чтобы тест не зависел от того, насколько велика
        # общая таблица на Dev и как её оценил планировщик: проверяется именно
        # пригодность выражения-индекса под этот предикат. Если выражение не
        # совпадёт, план уйдёт на индекс по agent_id без Index Cond по turn_id.
        await session.execute(text("set local enable_seqscan = off"))
        plan_rows = (await session.execute(text(f"explain {compiled}"))).scalars().all()

    plan = "\n".join(plan_rows)
    assert INDEX_NAME in plan, plan
    assert "payload ->> 'turn_id'" in plan, plan
