from __future__ import annotations

from typing import Any
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
    def __init__(self, configs: dict[UUID, AgentRuntimeConfig]) -> None:
        self._configs = configs

    async def __call__(self, agent_id: UUID) -> AgentRuntimeConfig:
        try:
            return self._configs[agent_id]
        except KeyError as exc:
            raise KeyError(f"Agent {agent_id} does not have a runtime config") from exc


class FailingConnectClient(FakeTelegramClient):
    async def connect(self) -> None:
        raise RuntimeError("connect failed")


@pytest.mark.asyncio
async def test_reload_restart_failure_persists_error_status() -> None:
    agent_id = uuid4()
    configs = {agent_id: _build_config(agent_id)}
    saved: list[tuple[UUID, Any]] = []

    def status_sink(aid: UUID, state: Any) -> None:
        saved.append((aid, state))

    manager = AgentManager(
        runtime_factory=lambda runtime_config: MimicAgentRuntime(
            config=runtime_config,
            telegram_client=FailingConnectClient(),
            langchain_agent=FakeLangChainAgent(),
        ),
        config_loader=ConfigStore(configs),
        status_sink=status_sink,
    )
    # Старт успешен только у первого рантайма: подменяем клиент-фабрику так,
    # чтобы изначальный старт прошёл, а пересобранный рантайм не смог.
    started: list[bool] = []

    real_factory = manager._runtime_factory

    def factory(runtime_config: AgentRuntimeConfig) -> MimicAgentRuntime:
        client = FakeTelegramClient()
        if started:
            return MimicAgentRuntime(
                config=runtime_config,
                telegram_client=FailingConnectClient(),
                langchain_agent=FakeLangChainAgent(),
            )
        started.append(True)
        return MimicAgentRuntime(
            config=runtime_config,
            telegram_client=client,
            langchain_agent=FakeLangChainAgent(),
        )

    manager._runtime_factory = factory  # type: ignore[method-assign]
    assert real_factory is not None
    await manager.create_agent(configs[agent_id], start=True)

    with pytest.raises(RuntimeError, match="connect"):
        await manager.reload_agent(agent_id)

    assert saved[-1] == (agent_id, AgentRuntimeState.ERROR)
