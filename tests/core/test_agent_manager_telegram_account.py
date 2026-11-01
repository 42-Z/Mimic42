from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    LangChainAgentLike,
    MimicAgentRuntime,
    TelegramClientLike,
)
from mimic42.core.manager import (
    AgentManager,
    TelegramRebindSequenceError,
    TelegramRebindStep,
)
from mimic42.testing.telegram import FakeTelegramClient
from tests.core.test_agent_manager_reload import ConfigStore, _build_config
from tests.core.test_agent_runtime import FakeLangChainAgent


class GatedLeaseRuntime(MimicAgentRuntime):
    def __init__(
        self,
        *,
        config: AgentRuntimeConfig,
        telegram_client: TelegramClientLike,
        langchain_agent: LangChainAgentLike,
    ) -> None:
        super().__init__(
            config=config,
            telegram_client=telegram_client,
            langchain_agent=langchain_agent,
        )
        self.lease_entered = asyncio.Event()
        self.lease_release = asyncio.Event()

    @asynccontextmanager
    async def leased_telegram_client(self) -> AsyncIterator[TelegramClientLike]:
        async with super().leased_telegram_client() as client:
            self.lease_entered.set()
            await self.lease_release.wait()
            yield client


def _runtime(config: AgentRuntimeConfig) -> MimicAgentRuntime:
    return MimicAgentRuntime(
        config=config,
        telegram_client=FakeTelegramClient(),
        langchain_agent=FakeLangChainAgent(),
    )


def _manager_for(
    config: AgentRuntimeConfig,
    *,
    gated: bool = False,
) -> tuple[AgentManager, list[MimicAgentRuntime]]:
    built: list[MimicAgentRuntime] = []

    def factory(runtime_config: AgentRuntimeConfig) -> MimicAgentRuntime:
        if gated and not built:
            runtime: MimicAgentRuntime = GatedLeaseRuntime(
                config=runtime_config,
                telegram_client=FakeTelegramClient(),
                langchain_agent=FakeLangChainAgent(),
            )
        else:
            runtime = _runtime(runtime_config)
        built.append(runtime)
        return runtime

    manager = AgentManager(
        runtime_factory=factory,
        config_loader=ConfigStore({config.agent_id: config}),
    )
    return manager, built


@pytest.mark.asyncio
async def test_account_operation_uses_the_runtime_that_is_current_after_the_lock() -> None:
    agent_id = uuid4()
    config = _build_config(agent_id)
    manager, built = _manager_for(config)
    old_runtime = await manager.create_agent(config)
    lock = manager._agent_lock(agent_id)
    await lock.acquire()

    operation = asyncio.create_task(manager.change_telegram_username(agent_id, "new_name"))
    await asyncio.sleep(0)

    replacement = _runtime(config)
    manager._agents[agent_id] = replacement
    await old_runtime.close()
    lock.release()

    assert await operation == "new_name"
    assert replacement.telegram_username == "new_name"
    assert old_runtime.telegram_username is None
    assert built == [old_runtime]


@pytest.mark.asyncio
async def test_reload_waits_for_an_account_operation_on_the_same_agent() -> None:
    agent_id = uuid4()
    config = _build_config(agent_id)
    manager, built = _manager_for(config, gated=True)
    runtime = await manager.create_agent(config)
    gated = runtime
    assert isinstance(gated, GatedLeaseRuntime)

    changing = asyncio.create_task(manager.change_telegram_username(agent_id, "new_name"))
    await gated.lease_entered.wait()

    reloading = asyncio.create_task(manager.reload_agent(agent_id))
    await asyncio.sleep(0)
    assert manager._agents[agent_id] is gated
    assert not reloading.done()

    gated.lease_release.set()
    await changing
    await reloading

    assert len(built) == 2
    assert manager._agents[agent_id] is built[1]
    assert gated.telegram_username == "new_name"


@pytest.mark.asyncio
async def test_rebind_confirmation_holds_the_lock_across_stop_apply_and_reload() -> None:
    agent_id = uuid4()
    config = _build_config(agent_id)
    manager, built = _manager_for(config)
    await manager.create_agent(config)
    applied = asyncio.Event()
    release = asyncio.Event()
    order: list[str] = []

    async def apply() -> str:
        order.append("apply")
        applied.set()
        await release.wait()
        return "applied"

    confirming = asyncio.create_task(manager.confirm_telegram_rebind(agent_id, apply))
    await applied.wait()

    changing = asyncio.create_task(manager.change_telegram_username(agent_id, "new_name"))
    await asyncio.sleep(0)
    assert not changing.done()
    assert order == ["apply"]

    release.set()
    assert await confirming == "applied"
    assert await changing == "new_name"
    assert len(built) == 2
    assert manager._agents[agent_id].telegram_username == "new_name"


@pytest.mark.asyncio
async def test_rebind_sequence_reports_the_failed_stop_step() -> None:
    agent_id = uuid4()
    config = _build_config(agent_id)
    manager, _ = _manager_for(config)
    await manager.create_agent(config)

    class FailingStopRuntime(MimicAgentRuntime):
        async def stop(self) -> None:
            raise RuntimeError("stop failed")

    manager._agents[agent_id] = FailingStopRuntime(
        config=config,
        telegram_client=FakeTelegramClient(),
        langchain_agent=FakeLangChainAgent(),
    )
    called: list[str] = []

    async def apply() -> None:
        called.append("apply")

    with pytest.raises(TelegramRebindSequenceError) as caught:
        await manager.confirm_telegram_rebind(agent_id, apply)

    assert caught.value.step is TelegramRebindStep.STOP
    assert called == []


@pytest.mark.asyncio
async def test_rebind_sequence_reports_the_failed_reload_step() -> None:
    agent_id = uuid4()
    config = _build_config(agent_id)
    builds = 0

    def factory(runtime_config: AgentRuntimeConfig) -> MimicAgentRuntime:
        nonlocal builds
        builds += 1
        if builds > 1:
            raise RuntimeError("build failed")
        return _runtime(runtime_config)

    manager = AgentManager(
        runtime_factory=factory,
        config_loader=ConfigStore({config.agent_id: config}),
    )
    await manager.create_agent(config)

    async def apply() -> None:
        return None

    with pytest.raises(TelegramRebindSequenceError) as caught:
        await manager.confirm_telegram_rebind(agent_id, apply)

    assert caught.value.step is TelegramRebindStep.RELOAD
    assert agent_id not in manager._agents
