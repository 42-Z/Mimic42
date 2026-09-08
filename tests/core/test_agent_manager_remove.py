from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from mimic42.core.agent_runtime import AgentRuntimeConfig, MimicAgentRuntime
from mimic42.core.manager import AgentManager

from .test_agent_runtime import FakeLangChainAgent, FakeTelegramClient


def _build_config(agent_id: UUID) -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=agent_id,
        owner_id=uuid4(),
        telegram_session_name=agent_id.hex,
        telegram_api_id=12345,
        telegram_api_hash="hash",
        telegram_session_string="session",
        system_prompt="system",
        soul_prompt="soul",
    )


def _build_manager() -> AgentManager:
    return AgentManager(
        runtime_factory=lambda runtime_config: MimicAgentRuntime(
            config=runtime_config,
            telegram_client=FakeTelegramClient(),
            langchain_agent=FakeLangChainAgent(),
        ),
    )


@pytest.mark.asyncio
async def test_remove_agent_stops_running_runtime_and_unregisters_it() -> None:
    manager = _build_manager()
    agent_id = uuid4()
    await manager.create_agent(_build_config(agent_id), start=True)

    await manager.remove_agent(agent_id)

    with pytest.raises(KeyError):
        await manager.get_agent(agent_id)


@pytest.mark.asyncio
async def test_remove_agent_is_idempotent_for_missing_runtime() -> None:
    manager = _build_manager()

    await manager.remove_agent(uuid4())
    await manager.remove_agent(uuid4())
