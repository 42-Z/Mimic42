"""Очистка контента ассистента при сохранении хранительных сообщений.

Регрессия из живого теста real_tg: LLM отдаёт content='\\n' (whitespace-only)
вместе с валидным structured_response.text. Такой content truthy, подмена на
human_text не срабатывала, и в ленте рендерился пустой абзац ответа агента.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.integrations.database_memory import DatabaseShortTermMemory
from mimic42.integrations.database_models import AgentMessageModel, AgentModel
from mimic42.testing.slots import Slot


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


async def test_whitespace_only_assistant_content_replaced_by_structured_text(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    agent_id = await _create_agent(db_session_factory, owner_id)
    store = DatabaseShortTermMemory(db_session_factory)

    await store.save_messages(
        agent_id=agent_id,
        peer="12345",
        messages=[{"role": "assistant", "content": "\n"}],
        raw_user_text="Привет из реального теста",
        turn_id="turn-ws",
        structured_response={
            "text": "Привет! Рада, что реальный тест идёт гладко 😊",
            "reply_to": None,
            "send_any_message": True,
        },
    )

    async with db_session_factory() as session:
        row = await session.scalar(
            select(AgentMessageModel)
            .where(AgentMessageModel.agent_id == agent_id)
            .where(AgentMessageModel.role == "assistant")
            .order_by(AgentMessageModel.created_at.desc())
            .limit(1)
        )
        assert row is not None
        assert row.content == "Привет! Рада, что реальный тест идёт гладко 😊"


async def test_none_structured_text_stored_as_empty_not_none_literal(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """text=None не должен превращаться в строку «None» в ленте."""
    owner_id = clean_slot.persona("twofa").user_id
    agent_id = await _create_agent(db_session_factory, owner_id)
    store = DatabaseShortTermMemory(db_session_factory)

    await store.save_messages(
        agent_id=agent_id,
        peer="12345",
        messages=[{"role": "assistant", "content": ""}],
        raw_user_text="Привет",
        turn_id="turn-none",
        structured_response={
            "text": None,
            "reply_to": None,
            "send_any_message": False,
        },
    )

    async with db_session_factory() as session:
        row = await session.scalar(
            select(AgentMessageModel)
            .where(AgentMessageModel.agent_id == agent_id)
            .where(AgentMessageModel.role == "assistant")
            .order_by(AgentMessageModel.created_at.desc())
            .limit(1)
        )
        assert row is not None
        assert row.content == ""


async def test_whitespace_only_assistant_content_without_structured_skipped(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Whitespace без structured_response и tool_calls — не несёт данных."""
    owner_id = clean_slot.persona("twofa").user_id
    agent_id = await _create_agent(db_session_factory, owner_id)
    store = DatabaseShortTermMemory(db_session_factory)

    await store.save_messages(
        agent_id=agent_id,
        peer="12345",
        messages=[{"role": "assistant", "content": "   \n  "}],
        raw_user_text="Привет",
        turn_id="turn-ws2",
    )

    async with db_session_factory() as session:
        rows = list(
            await session.scalars(
                select(AgentMessageModel)
                .where(AgentMessageModel.agent_id == agent_id)
                .where(AgentMessageModel.role == "assistant")
            )
        )
        assert rows == []
