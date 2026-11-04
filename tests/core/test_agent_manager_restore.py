from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from python_socks import ProxyError

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentRuntimeState,
    MimicAgentRuntime,
    TelegramProxyConfig,
)
from mimic42.core.manager import AgentManager

from .test_agent_runtime import FakeLangChainAgent, FakeTelegramClient


class FailingStartClient(FakeTelegramClient):
    async def connect(self) -> None:
        raise RuntimeError("connect failed")


class ProxyRejectingClient(FakeTelegramClient):
    async def connect(self) -> None:
        raise ProxyError("Username and password authentication failure")


def _config(agent_id: UUID, *, with_proxy: bool) -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=agent_id,
        owner_id=uuid4(),
        telegram_api_id=12345,
        telegram_api_hash="hash",
        telegram_session_string="session",
        system_prompt="system",
        soul_prompt="soul",
        telegram_proxy=(
            TelegramProxyConfig(
                protocol="socks5",
                host="127.0.0.1",
                port=1080,
                username="user",
                password=SecretStr("secret"),
            )
            if with_proxy
            else None
        ),
    )


def _proxy_aware_factory(
    built: list[AgentRuntimeConfig],
) -> Callable[[AgentRuntimeConfig], MimicAgentRuntime]:
    def factory(runtime_config: AgentRuntimeConfig) -> MimicAgentRuntime:
        built.append(runtime_config)
        client: FakeTelegramClient = (
            ProxyRejectingClient()
            if runtime_config.telegram_proxy is not None
            else FakeTelegramClient()
        )
        return MimicAgentRuntime(
            config=runtime_config,
            telegram_client=client,
            langchain_agent=FakeLangChainAgent(),
        )

    return factory


@pytest.mark.asyncio
async def test_create_agent_retries_without_proxy_when_the_proxy_rejects() -> None:
    agent_id = uuid4()
    built: list[AgentRuntimeConfig] = []
    manager = AgentManager(
        runtime_factory=_proxy_aware_factory(built),
        proxy_direct_fallback=True,
    )

    runtime = await manager.create_agent(_config(agent_id, with_proxy=True), start=True)

    assert [item.telegram_proxy is None for item in built] == [False, True]
    assert all(item.proxy_direct_fallback is True for item in built)
    assert runtime.config.telegram_proxy is None
    assert runtime.status.state is AgentRuntimeState.RUNNING
    assert await manager.get_agent(agent_id) is runtime


@pytest.mark.asyncio
async def test_start_agent_retries_without_proxy_when_the_proxy_rejects() -> None:
    agent_id = uuid4()
    config = _config(agent_id, with_proxy=True)
    built: list[AgentRuntimeConfig] = []
    updates: list[tuple[UUID, AgentRuntimeState]] = []

    async def load_config(missing_agent_id: UUID) -> AgentRuntimeConfig:
        assert missing_agent_id == agent_id
        return config

    async def save_status(saved_agent_id: UUID, state: AgentRuntimeState) -> None:
        updates.append((saved_agent_id, state))

    manager = AgentManager(
        runtime_factory=_proxy_aware_factory(built),
        config_loader=load_config,
        status_sink=save_status,
        proxy_direct_fallback=True,
    )

    await manager.start_agent(agent_id)

    runtime = await manager.get_agent(agent_id)
    assert runtime.config.telegram_proxy is None
    assert runtime.status.state is AgentRuntimeState.RUNNING
    assert updates == [(agent_id, AgentRuntimeState.RUNNING)]


@pytest.mark.asyncio
async def test_proxy_rejection_without_a_proxy_is_not_retried() -> None:
    manager = AgentManager(
        runtime_factory=lambda runtime_config: MimicAgentRuntime(
            config=runtime_config,
            telegram_client=ProxyRejectingClient(),
            langchain_agent=FakeLangChainAgent(),
        ),
        proxy_direct_fallback=True,
    )

    with pytest.raises(ProxyError):
        await manager.create_agent(_config(uuid4(), with_proxy=False), start=True)


@pytest.mark.asyncio
async def test_proxy_rejection_does_not_fall_back_when_the_app_policy_is_off() -> None:
    agent_id = uuid4()
    built: list[AgentRuntimeConfig] = []
    manager = AgentManager(runtime_factory=_proxy_aware_factory(built))

    with pytest.raises(ProxyError):
        await manager.create_agent(_config(agent_id, with_proxy=True), start=True)

    assert [item.telegram_proxy is None for item in built] == [False]
    assert built[0].proxy_direct_fallback is False


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
