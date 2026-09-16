from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from mimic42.core.agent_runtime import AgentRuntimeConfig, MimicAgentRuntime
from mimic42.core.manager import AgentManager, AgentNotFoundError

from .test_agent_runtime import FakeLangChainAgent, FakeTelegramClient


def _config() -> AgentRuntimeConfig:
    agent_id = uuid4()
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


async def test_concurrent_get_agent_builds_a_single_runtime() -> None:
    """Поллинг статуса и триггер могут прийти одновременно: второй запрос
    обязан получить уже собранный рантайм, а не упасть на «already exists»."""
    config = _config()
    built = 0

    async def load_config(missing_agent_id: object) -> AgentRuntimeConfig:
        assert missing_agent_id == config.agent_id
        # Даём второму вызову дойти до проверки реестра до регистрации.
        await asyncio.sleep(0.01)
        return config

    def runtime_factory(runtime_config: AgentRuntimeConfig) -> MimicAgentRuntime:
        nonlocal built
        built += 1
        return MimicAgentRuntime(
            config=runtime_config,
            telegram_client=FakeTelegramClient(),
            langchain_agent=FakeLangChainAgent(),
        )

    manager = AgentManager(runtime_factory=runtime_factory, config_loader=load_config)

    first, second = await asyncio.gather(
        manager.get_agent(config.agent_id),
        manager.get_agent(config.agent_id),
    )

    assert first is second
    assert built == 1


async def test_get_agent_after_removal_stays_removed() -> None:
    config = _config()
    manager = AgentManager(
        runtime_factory=lambda runtime_config: MimicAgentRuntime(
            config=runtime_config,
            telegram_client=FakeTelegramClient(),
            langchain_agent=FakeLangChainAgent(),
        ),
        config_loader=lambda agent_id: config,
    )
    await manager.get_agent(config.agent_id)
    await manager.remove_agent(config.agent_id)

    # Tombstone не должен позволять воскресить удалённого агента из конфига.
    with pytest.raises(AgentNotFoundError):
        await manager.get_agent(config.agent_id)
