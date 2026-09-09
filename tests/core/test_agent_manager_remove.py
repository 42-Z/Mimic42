from __future__ import annotations

import asyncio
from typing import cast
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


@pytest.mark.asyncio
async def test_removed_agent_is_not_remateralised_from_config_loader() -> None:
    agent_id = uuid4()
    config = _build_config(agent_id)

    async def load_config(_agent_id: UUID) -> AgentRuntimeConfig:
        return config

    manager = AgentManager(
        runtime_factory=lambda runtime_config: MimicAgentRuntime(
            config=runtime_config,
            telegram_client=FakeTelegramClient(),
            langchain_agent=FakeLangChainAgent(),
        ),
        config_loader=load_config,
    )
    await manager.remove_agent(agent_id)

    with pytest.raises(KeyError):
        await manager.get_agent(agent_id)


@pytest.mark.asyncio
async def test_missing_config_row_raises_agent_not_found() -> None:
    async def load_config(_agent_id: UUID) -> AgentRuntimeConfig:
        raise KeyError("Agent does not have a runtime config")

    manager = AgentManager(config_loader=load_config)

    with pytest.raises(KeyError) as exc_info:
        await manager.get_agent(uuid4())

    assert type(exc_info.value).__name__ == "AgentNotFoundError"


@pytest.mark.asyncio
async def test_remove_agent_propagates_stop_failures() -> None:
    class FailingDisconnectClient(FakeTelegramClient):
        async def disconnect(self) -> None:
            raise RuntimeError("disconnect failed")

    agent_id = uuid4()
    manager = AgentManager(
        runtime_factory=lambda runtime_config: MimicAgentRuntime(
            config=runtime_config,
            telegram_client=FailingDisconnectClient(),
            langchain_agent=FakeLangChainAgent(),
        ),
    )
    await manager.create_agent(_build_config(agent_id), start=True)

    with pytest.raises(RuntimeError, match="disconnect failed"):
        await manager.remove_agent(agent_id)

    # The agent must not be tombstoned: it is still present in the database,
    # so re-materialisation has to stay possible.
    assert agent_id not in manager._removed


@pytest.mark.asyncio
async def test_get_agent_during_removal_sees_tombstone() -> None:
    """A concurrent get_agent must not re-materialise the runtime while
    remove_agent is stopping it — otherwise the leaked runtime keeps its
    Telethon connection forever."""
    entered = asyncio.Event()
    release = asyncio.Event()
    agent_id = uuid4()

    class SlowStopRuntime:
        def __init__(self, config: AgentRuntimeConfig) -> None:
            self.config = config

        async def stop(self) -> None:
            entered.set()
            await release.wait()

    def factory(
        config: AgentRuntimeConfig,
        session_factory: object = None,
    ) -> MimicAgentRuntime:
        return cast("MimicAgentRuntime", SlowStopRuntime(config))

    async def load_config(_agent_id: UUID) -> AgentRuntimeConfig:
        return _build_config(agent_id)

    manager = AgentManager(runtime_factory=factory, config_loader=load_config)
    await manager.create_agent(_build_config(agent_id))

    removal = asyncio.create_task(manager.remove_agent(agent_id))
    await entered.wait()

    with pytest.raises(KeyError):
        await manager.get_agent(agent_id)

    release.set()
    await removal

    assert manager._agents == {}
    assert agent_id in manager._removed
