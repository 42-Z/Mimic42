from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentRuntimeState,
    MimicAgentRuntime,
)
from mimic42.core.manager import AgentManager

from .test_agent_runtime import FakeLangChainAgent, FakeTelegramClient


def _build_config(agent_id: UUID, llm_model: str = "z-ai/glm-5.3-flash") -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=agent_id,
        owner_id=uuid4(),
        telegram_session_name=agent_id.hex,
        telegram_api_id=12345,
        telegram_api_hash="hash",
        telegram_session_string="session",
        system_prompt="system",
        soul_prompt="soul",
        llm_model=llm_model,
    )


class ConfigStore:
    """In-memory config loader standing in for the database store."""

    def __init__(self, configs: dict[UUID, AgentRuntimeConfig]) -> None:
        self._configs = configs

    async def __call__(self, agent_id: UUID) -> AgentRuntimeConfig:
        try:
            return self._configs[agent_id]
        except KeyError as exc:
            raise KeyError(f"Agent {agent_id} does not have a runtime config") from exc


def _build_manager(configs: dict[UUID, AgentRuntimeConfig]) -> AgentManager:
    return AgentManager(
        runtime_factory=lambda runtime_config: MimicAgentRuntime(
            config=runtime_config,
            telegram_client=FakeTelegramClient(),
            langchain_agent=FakeLangChainAgent(),
        ),
        config_loader=ConfigStore(configs),
    )


@pytest.mark.asyncio
async def test_reload_rebuilds_running_runtime_with_fresh_config() -> None:
    agent_id = uuid4()
    configs = {agent_id: _build_config(agent_id)}
    manager = _build_manager(configs)
    await manager.create_agent(configs[agent_id], start=True)
    configs[agent_id] = _build_config(agent_id, llm_model="meituan/longcat-2.0")

    await manager.reload_agent(agent_id)

    rebuilt = manager._agents[agent_id]
    assert rebuilt.config.llm_model == "meituan/longcat-2.0"
    assert rebuilt.status.state is AgentRuntimeState.RUNNING


@pytest.mark.asyncio
async def test_reload_keeps_stopped_agent_stopped() -> None:
    agent_id = uuid4()
    configs = {agent_id: _build_config(agent_id)}
    manager = _build_manager(configs)
    await manager.create_agent(configs[agent_id])
    configs[agent_id] = _build_config(agent_id, llm_model="meituan/longcat-2.0")

    await manager.reload_agent(agent_id)

    rebuilt = manager._agents[agent_id]
    assert rebuilt.config.llm_model == "meituan/longcat-2.0"
    assert rebuilt.status.state is AgentRuntimeState.STOPPED


@pytest.mark.asyncio
async def test_reload_of_unmaterialised_agent_is_noop() -> None:
    manager = _build_manager({})
    agent_id = uuid4()

    await manager.reload_agent(agent_id)

    assert agent_id not in manager._agents


@pytest.mark.asyncio
async def test_reload_propagates_stop_failures() -> None:
    class FailingDisconnectClient(FakeTelegramClient):
        async def disconnect(self) -> None:
            raise RuntimeError("disconnect failed")

    agent_id = uuid4()
    configs = {agent_id: _build_config(agent_id)}
    manager = AgentManager(
        runtime_factory=lambda runtime_config: MimicAgentRuntime(
            config=runtime_config,
            telegram_client=FailingDisconnectClient(),
            langchain_agent=FakeLangChainAgent(),
        ),
        config_loader=ConfigStore(configs),
    )
    await manager.create_agent(configs[agent_id], start=True)

    with pytest.raises(RuntimeError, match="disconnect failed"):
        await manager.reload_agent(agent_id)

    # Без тумбстоуна: агент всё ещё в БД, ре-материализация должна остаться
    # возможной при следующем get_agent.
    assert agent_id not in manager._removed
