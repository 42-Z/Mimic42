"""Проводка сервиса атак в менеджер: хуки жизненного цикла, статус и сверка.

Сервис атак на этих проверках подменён: менеджер обязан звать его хуки в
нужном порядке, отдавать рантайм без замка агента и не падать, если сервис
сломался. Настоящий жизненный цикл участий проверяет test_attack_service.py.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentRuntimeState,
    MimicAgentRuntime,
)
from mimic42.core.attack import AttackView
from mimic42.core.attack_service import (
    SWEEP_TASK_NAME,
    AttackService,
)
from mimic42.core.manager import AgentManager, AgentNotFoundError

from .test_agent_runtime import FakeLangChainAgent, FakeTelegramClient, make_config
from .test_attack_service import FakeActivity, FakeManager, FakeRepo


class LoggedRuntime(MimicAgentRuntime):
    """Рантайм, который отмечает реальную остановку в общем журнале теста."""

    def __init__(self, *, log: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.log = log

    async def stop(self) -> None:
        self.log.append("stop")
        await super().stop()


class FakeAttacks:
    """Хуки сервиса атак: журнал вызовов и проверки замка менеджера."""

    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.manager: AgentManager | None = None
        self.attack_id: UUID | None = None
        self.runtime: MimicAgentRuntime | None = None
        self.lock_free: dict[str, bool] = {}
        self.registered: dict[str, bool] = {}
        self.error: Exception | None = None

    def _manager(self) -> AgentManager:
        assert self.manager is not None
        return self.manager

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    async def on_runtime_ready(self, agent_id: UUID) -> None:
        self._raise()
        self.log.append("ready")
        manager = self._manager()
        self.runtime = await manager.get_runtime(agent_id)
        self.lock_free["ready"] = not manager._agent_lock(agent_id).locked()

    async def on_runtime_changed(self, agent_id: UUID) -> None:
        self._raise()
        self.log.append("changed")
        manager = self._manager()
        self.runtime = await manager.get_runtime(agent_id)
        self.lock_free["changed"] = not manager._agent_lock(agent_id).locked()
        if self.attack_id is not None:
            self.runtime.enter_attack(self.attack_id)

    async def on_agent_stopped(self, agent_id: UUID) -> None:
        self._raise()
        self.log.append("stopped")
        manager = self._manager()
        self.runtime = await manager.get_runtime(agent_id)
        self.lock_free["stopped"] = not manager._agent_lock(agent_id).locked()
        self.runtime.exit_attack()

    async def on_agent_removed(self, agent_id: UUID) -> None:
        self._raise()
        self.log.append("removed")
        manager = self._manager()
        self.runtime = await manager.get_runtime(agent_id)
        self.registered["removed"] = agent_id in manager._agents
        self.runtime.exit_attack()


def _build_manager(
    config: AgentRuntimeConfig,
    attacks: FakeAttacks,
    log: list[str],
) -> AgentManager:
    async def load_config(agent_id: UUID) -> AgentRuntimeConfig:
        assert agent_id == config.agent_id
        return config

    def runtime_factory(runtime_config: AgentRuntimeConfig) -> MimicAgentRuntime:
        return LoggedRuntime(
            config=runtime_config,
            telegram_client=FakeTelegramClient(),
            langchain_agent=FakeLangChainAgent(),
            log=log,
        )

    manager = AgentManager(
        runtime_factory=runtime_factory,
        config_loader=load_config,
        attacks=cast(AttackService, attacks),
    )
    attacks.manager = manager
    return manager


@pytest.mark.asyncio
async def test_ready_hook_runs_after_start_and_outside_the_agent_lock() -> None:
    config = make_config()
    log: list[str] = []
    attacks = FakeAttacks(log)
    manager = _build_manager(config, attacks, log)

    runtime = await manager.create_agent(config, start=True)

    assert log == ["ready"]
    assert attacks.runtime is runtime
    assert attacks.lock_free["ready"] is True
    assert runtime.state is AgentRuntimeState.RUNNING


@pytest.mark.asyncio
async def test_start_agent_notifies_the_attack_service() -> None:
    config = make_config()
    log: list[str] = []
    attacks = FakeAttacks(log)
    manager = _build_manager(config, attacks, log)
    await manager.create_agent(config)

    await manager.start_agent(config.agent_id)

    assert log == ["ready"]
    assert attacks.lock_free["ready"] is True


@pytest.mark.asyncio
async def test_status_reports_the_attack_id() -> None:
    config = make_config()
    log: list[str] = []
    attacks = FakeAttacks(log)
    manager = _build_manager(config, attacks, log)
    attack_id = uuid4()

    runtime = await manager.create_agent(config, start=True)
    runtime.enter_attack(attack_id)

    status = await manager.get_agent_status(config.agent_id)

    assert status.attack_id == attack_id
    assert runtime.status.attack_id == attack_id
    assert [item.attack_id for item in await manager.list_agents()] == [attack_id]


@pytest.mark.asyncio
async def test_stop_exits_the_attack_before_the_runtime_stops() -> None:
    config = make_config()
    log: list[str] = []
    attacks = FakeAttacks(log)
    manager = _build_manager(config, attacks, log)
    attack_id = uuid4()

    runtime = await manager.create_agent(config, start=True)
    runtime.enter_attack(attack_id)

    await manager.stop_agent(config.agent_id)

    assert log == ["ready", "stopped", "stop"]
    assert attacks.runtime is runtime
    assert attacks.lock_free["stopped"] is False
    assert runtime.attack_id is None
    assert runtime.state is AgentRuntimeState.STOPPED


@pytest.mark.asyncio
async def test_reload_reattaches_the_new_runtime_to_the_attack() -> None:
    config = make_config()
    log: list[str] = []
    attacks = FakeAttacks(log)
    manager = _build_manager(config, attacks, log)
    attack_id = uuid4()

    old = await manager.create_agent(config, start=True)
    old.enter_attack(attack_id)
    attacks.attack_id = attack_id

    await manager.reload_agent(config.agent_id)

    fresh = await manager.get_agent(config.agent_id)
    assert fresh is not old
    assert fresh.attack_id == attack_id
    assert attacks.runtime is fresh
    assert attacks.lock_free["changed"] is True
    assert log == ["ready", "stop", "changed"]


@pytest.mark.asyncio
async def test_remove_writes_the_note_while_the_runtime_is_still_registered() -> None:
    config = make_config()
    log: list[str] = []
    attacks = FakeAttacks(log)
    manager = _build_manager(config, attacks, log)
    attack_id = uuid4()

    runtime = await manager.create_agent(config, start=True)
    runtime.enter_attack(attack_id)

    await manager.remove_agent(config.agent_id)

    assert log == ["ready", "removed", "stop"]
    assert attacks.registered["removed"] is True
    assert attacks.runtime is runtime
    assert runtime.attack_id is None
    with pytest.raises(AgentNotFoundError):
        await manager.get_agent(config.agent_id)


@pytest.mark.asyncio
async def test_attack_hook_failure_does_not_break_the_agent_lifecycle() -> None:
    config = make_config()
    log: list[str] = []
    attacks = FakeAttacks(log)
    manager = _build_manager(config, attacks, log)
    attacks.error = RuntimeError("сервис атак недоступен")

    runtime = await manager.create_agent(config, start=True)
    await manager.stop_agent(config.agent_id)

    assert runtime.state is AgentRuntimeState.STOPPED


class CountingRepo(FakeRepo):
    def __init__(self) -> None:
        super().__init__()
        self.running_loads = 0

    async def load_running(self) -> list[AttackView]:
        self.running_loads += 1
        return await super().load_running()


class GateSleep:
    """Сон, который держит сверку на паузе до отмены задачи."""

    def __init__(self) -> None:
        self.calls = 0
        self.gate = asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.calls += 1
        await self.gate.wait()


@pytest.mark.asyncio
async def test_attack_service_start_reconciles_once_and_close_cancels_the_sweep() -> None:
    repo = CountingRepo()
    service = AttackService(FakeManager([]), repo, FakeActivity(), sleep=GateSleep())

    await service.start()
    await service.start()

    assert repo.running_loads == 1
    assert any(task.get_name() == SWEEP_TASK_NAME for task in asyncio.all_tasks())

    await service.close()
    await service.start()

    assert repo.running_loads == 1
    assert not any(task.get_name() == SWEEP_TASK_NAME for task in asyncio.all_tasks())
