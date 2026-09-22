from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from mimic42.core.agent_runtime import AgentRuntimeConfig, AgentRuntimeState, MimicAgentRuntime
from mimic42.core.manager import AgentManager

from .test_agent_runtime import FakeLangChainAgent, FakeTelegramClient


class FailingStartClient(FakeTelegramClient):
    async def connect(self) -> None:
        raise RuntimeError("connect failed")


@pytest.mark.asyncio
async def test_start_agent_loads_missing_runtime_from_persistent_config() -> None:
    agent_id = uuid4()
    config = AgentRuntimeConfig(
        agent_id=agent_id,
        owner_id=uuid4(),
        telegram_api_id=12345,
        telegram_api_hash="hash",
        telegram_session_string="session",
        system_prompt="system",
        soul_prompt="soul",
    )
    updates: list[tuple[UUID, AgentRuntimeState]] = []

    async def load_config(missing_agent_id: UUID) -> AgentRuntimeConfig:
        assert missing_agent_id == agent_id
        return config

    async def save_status(saved_agent_id: UUID, state: AgentRuntimeState) -> None:
        updates.append((saved_agent_id, state))

    manager = AgentManager(
        runtime_factory=lambda runtime_config: MimicAgentRuntime(
            config=runtime_config,
            telegram_client=FakeTelegramClient(),
            langchain_agent=FakeLangChainAgent(),
        ),
        config_loader=load_config,
        status_sink=save_status,
    )

    await manager.start_agent(agent_id)

    assert await manager.get_agent_status(agent_id)
    assert updates == [(agent_id, AgentRuntimeState.RUNNING)]


@pytest.mark.asyncio
async def test_create_agent_start_failure_persists_error_status() -> None:
    agent_id = uuid4()
    config = AgentRuntimeConfig(
        agent_id=agent_id,
        owner_id=uuid4(),
        telegram_api_id=12345,
        telegram_api_hash="hash",
        telegram_session_string="session",
        system_prompt="system",
        soul_prompt="soul",
    )
    updates: list[tuple[UUID, AgentRuntimeState]] = []

    async def save_status(saved_agent_id: UUID, state: AgentRuntimeState) -> None:
        updates.append((saved_agent_id, state))

    manager = AgentManager(
        runtime_factory=lambda runtime_config: MimicAgentRuntime(
            config=runtime_config,
            telegram_client=FailingStartClient(),
            langchain_agent=FakeLangChainAgent(),
        ),
        status_sink=save_status,
    )

    with pytest.raises(RuntimeError, match="connect"):
        await manager.create_agent(config, start=True)

    assert updates == [(agent_id, AgentRuntimeState.ERROR)]
