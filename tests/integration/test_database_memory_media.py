from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.integrations.database_memory import DatabaseShortTermMemory
from mimic42.integrations.database_models import AgentMessageModel, AgentModel
from mimic42.testing.slots import Slot

MEDIA = [
    {
        "kind": "photo",
        "name": "photo.jpeg",
        "mime_type": "image/jpeg",
        "size": 3,
        "storage_path": "00000000-0000-0000-0000-000000000000/u1/photo.jpeg",
    },
]

REPLY = {"message_id": 42, "preview": "предыдущее сообщение"}


async def _create_agent(
    db_session_factory: async_sessionmaker[AsyncSession], owner_id: UUID
) -> UUID:
    agent_id = uuid4()
    async with db_session_factory() as session:
        session.add(
            AgentModel(
                id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                status=AgentRuntimeState.STOPPED.value,
                soul_prompt="Soul",
            )
        )
        await session.commit()
    return agent_id


async def test_save_messages_attaches_media_to_incoming_row(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    agent_id = await _create_agent(db_session_factory, owner_id)
    store = DatabaseShortTermMemory(db_session_factory)

    await store.save_messages(
        agent_id=agent_id,
        peer="12345",
        messages=[{"role": "assistant", "content": "Ответ"}],
        peer_name="Ivan",
        raw_user_text="Привет",
        turn_id="turn-42",
        media=MEDIA,
        reply=REPLY,
    )

    async with db_session_factory() as session:
        row = await session.scalar(
            select(AgentMessageModel)
            .where(AgentMessageModel.agent_id == agent_id)
            .where(AgentMessageModel.direction == "incoming")
            .order_by(AgentMessageModel.created_at.desc())
            .limit(1)
        )
        assert row is not None
        assert row.content == "Привет"
        assert row.payload.get("media") == MEDIA
        assert row.payload.get("reply") == REPLY
        assert row.payload.get("turn_id") == "turn-42"


async def test_save_messages_attaches_media_when_incoming_row_deduped(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    agent_id = await _create_agent(db_session_factory, owner_id)
    store = DatabaseShortTermMemory(db_session_factory)
    messages = [
        {"role": "user", "content": "Привет"},
        {"role": "assistant", "content": "Ответ"},
    ]

    await store.save_messages(
        agent_id=agent_id,
        peer="12345",
        messages=messages,
        raw_user_text="Привет",
        media=MEDIA,
    )
    # Второй вызов: raw_user_text совпадает с последним user-контентом —
    # дедуп не создаёт incoming-строку, медиа должны лечь на user-строку цикла.
    await store.save_messages(
        agent_id=agent_id,
        peer="12345",
        messages=messages,
        raw_user_text="Привет",
        media=MEDIA,
    )

    async with db_session_factory() as session:
        rows = list(
            await session.scalars(
                select(AgentMessageModel)
                .where(AgentMessageModel.agent_id == agent_id)
                .where(AgentMessageModel.direction == "incoming")
                .order_by(AgentMessageModel.created_at.asc())
            )
        )
        assert any(row.payload.get("media") == MEDIA for row in rows)


async def test_save_messages_writes_single_incoming_row_when_raw_differs(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Форматированный human в messages не должен дублировать raw-строку:
    две incoming-строки в одном turn_id ломают ленту (одинаковые id блоков)."""
    owner_id = clean_slot.persona("twofa").user_id
    agent_id = await _create_agent(db_session_factory, owner_id)
    store = DatabaseShortTermMemory(db_session_factory)
    formatted = "[Входящее сообщение]\nСодержимое: Привет"

    await store.save_messages(
        agent_id=agent_id,
        peer="12345",
        messages=[
            {"role": "user", "content": formatted},
            {"role": "assistant", "content": "Ответ"},
        ],
        raw_user_text="Привет",
        turn_id="turn-7",
    )

    async with db_session_factory() as session:
        rows = list(
            await session.scalars(
                select(AgentMessageModel)
                .where(AgentMessageModel.agent_id == agent_id)
                .where(AgentMessageModel.direction == "incoming")
            )
        )
        assert len(rows) == 1
        assert rows[0].content == "Привет"
        assert rows[0].payload.get("turn_id") == "turn-7"
