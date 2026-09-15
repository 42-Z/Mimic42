"""Устойчивость приложения к кривым ответам модели через живой пайплайн:
настоящая база, настоящий FastAPI (build_test_app), поддельные Telegram
и LLM (ScriptedAgentFactory). Смысл — не мозг агента, а то, что
приложение не падает и честно записывает ошибку."""

from __future__ import annotations

from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.onboarding import OnboardingSession, TelegramLoginStatus
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.testing import registry
from mimic42.testing.llm import Crash, Empty, Reply
from mimic42.testing.server import build_test_app
from mimic42.testing.slots import Slot, plain_dsn
from mimic42.testing.telegram import FakeTelegramAccount

CHAT_ID = 4242


async def _running_agent(
    app: FastAPI,
    db_session_factory: async_sessionmaker[AsyncSession],
    slot: Slot,
) -> tuple[UUID, FakeTelegramAccount]:
    """Создаёт агента в базе, запускает его и возвращает (agent_id, account)."""
    owner_id = slot.persona("full").user_id
    agent_id = uuid4()
    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            # Поддельный клиент их не читает, но AgentRuntimeConfig требует
            # непустые api_id/api_hash независимо от того, что подключение
            # к настоящему Telegram здесь не происходит.
            api_id=1,
            api_hash_secret="test-api-hash",
            name="устойчивый",
            soul_prompt="спокойный помощник, отвечает коротко",
        )
    )
    config = await store.get_runtime_config(agent_id)
    await app.state.agent_manager.create_agent(config, start=True)
    return agent_id, registry.account_for(agent_id)


@pytest.mark.asyncio
async def test_reply_is_delivered_through_real_pipeline(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    app = build_test_app()
    async with app.router.lifespan_context(app):
        agent_id, account = await _running_agent(app, db_session_factory, clean_slot)
        app.state.scripted_agents.set_script(agent_id, [Reply("привет, чем помочь?")])

        await account.deliver(chat_id=CHAT_ID, text="привет")

    assert [message.text for message in account.sent] == ["привет, чем помочь?"]


@pytest.mark.asyncio
async def test_empty_answer_does_not_send_empty_message(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Пустой ответ модели не должен превращаться в пустое сообщение в телеге."""
    app = build_test_app()
    async with app.router.lifespan_context(app):
        agent_id, account = await _running_agent(app, db_session_factory, clean_slot)
        app.state.scripted_agents.set_script(agent_id, [Empty()])

        await account.deliver(chat_id=CHAT_ID, text="привет")

    assert account.sent == []


@pytest.mark.asyncio
async def test_invalid_model_output_is_recorded_as_failure_and_agent_stays_running(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    test_dsn: str,
) -> None:
    """Модель вернула ответ, не прошедший структурную валидацию (ainvoke падает):
    событие должно сохраниться со статусом «не удалось», агент не должен упасть."""
    app = build_test_app()
    async with app.router.lifespan_context(app):
        agent_id, account = await _running_agent(app, db_session_factory, clean_slot)
        app.state.scripted_agents.set_script(agent_id, [Crash()])

        await account.deliver(chat_id=CHAT_ID, text="сделай что-нибудь")

        status = await app.state.agent_manager.get_agent_status(agent_id)
        assert status.state.value == "running", "кривой ответ модели не должен ронять агента"

        connection = await asyncpg.connect(plain_dsn(test_dsn))
        try:
            rows = await connection.fetch(
                "select status from public.agent_events "
                "where agent_id = $1 and event_type = 'turn.failed'",
                agent_id,
            )
        finally:
            await connection.close()

    assert rows, "событие о провале хода вообще не записалось"
    assert {row["status"] for row in rows} == {"failed"}
    assert account.sent == []
