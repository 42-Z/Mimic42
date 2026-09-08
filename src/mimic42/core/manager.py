from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentRuntimeState,
    AgentStatus,
    AgentTrigger,
    AgentTriggerResult,
    MimicAgentRuntime,
    TelegramClientLike,
)
from mimic42.core.memory import RuntimeMemoryService
from mimic42.integrations.langchain_agent import build_langchain_agent
from mimic42.integrations.telegram_tools import (
    TelethonRequestClient,
    build_telegram_langchain_tools,
)
from mimic42.integrations.telethon_client import build_telegram_client

logger = logging.getLogger("mimic42.core.manager")


class AgentNotFoundError(KeyError):
    def __init__(self, agent_id: UUID) -> None:
        super().__init__(f"Agent {agent_id} does not exist")
        self.agent_id = agent_id


RuntimeFactory = Callable[[AgentRuntimeConfig], MimicAgentRuntime]
MemoryServiceFactory = Callable[[AgentRuntimeConfig], RuntimeMemoryService]
ConfigLoader = Callable[[UUID], object]
StatusSink = Callable[[UUID, AgentRuntimeState], object]


class AgentManager:
    """In-process async registry for multiple users and their agent runtimes."""

    def __init__(
        self,
        runtime_factory: RuntimeFactory | None = None,
        memory_service_factory: MemoryServiceFactory | None = None,
        config_loader: ConfigLoader | None = None,
        status_sink: StatusSink | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._runtime_factory = runtime_factory or _build_runtime
        self._memory_service_factory = memory_service_factory
        self._config_loader = config_loader
        self._status_sink = status_sink
        self.session_factory = session_factory
        self._agents: dict[UUID, MimicAgentRuntime] = {}
        self._lock = asyncio.Lock()

    async def create_agent(
        self,
        config: AgentRuntimeConfig,
        *,
        start: bool = False,
    ) -> MimicAgentRuntime:
        async with self._lock:
            if config.agent_id in self._agents:
                raise ValueError(f"Agent {config.agent_id} already exists")
            if self._memory_service_factory is not None:
                runtime = self._build_runtime_with_memory(config)
            else:
                sig = inspect.signature(self._runtime_factory)
                if "session_factory" in sig.parameters:
                    runtime = self._runtime_factory(
                        config,
                        session_factory=self.session_factory,
                    )
                else:
                    runtime = self._runtime_factory(config)
            self._agents[config.agent_id] = runtime

        if start:
            await runtime.start()
        return runtime

    async def get_agent(self, agent_id: UUID) -> MimicAgentRuntime:
        if agent_id not in self._agents and self._config_loader is not None:
            config = await _await_result(self._config_loader(agent_id))
            if not isinstance(config, AgentRuntimeConfig):
                raise TypeError("config_loader must return AgentRuntimeConfig")
            await self.create_agent(config)
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise AgentNotFoundError(agent_id) from exc

    async def get_agent_status(self, agent_id: UUID) -> AgentStatus:
        return (await self.get_agent(agent_id)).status

    async def list_agents(self, *, owner_id: UUID | None = None) -> list[AgentStatus]:
        agents = list(self._agents.values())
        if owner_id is not None:
            agents = [agent for agent in agents if agent.config.owner_id == owner_id]
        return [agent.status for agent in agents]

    async def start_agent(self, agent_id: UUID) -> None:
        await (await self.get_agent(agent_id)).start()
        await self._save_status(agent_id, AgentRuntimeState.RUNNING)

    async def stop_agent(self, agent_id: UUID) -> None:
        await (await self.get_agent(agent_id)).stop()
        await self._save_status(agent_id, AgentRuntimeState.STOPPED)

    async def remove_agent(self, agent_id: UUID) -> None:
        """Unregister the agent runtime and stop it. Missing agents are ignored."""
        async with self._lock:
            runtime = self._agents.pop(agent_id, None)
        if runtime is None:
            return
        try:
            await runtime.stop()
        except Exception:
            logger.exception("Failed to stop runtime of removed agent %s", agent_id)

    async def trigger_message(
        self,
        agent_id: UUID,
        trigger: AgentTrigger,
    ) -> AgentTriggerResult:
        return await (await self.get_agent(agent_id)).trigger_message(trigger)

    async def shutdown(self) -> None:
        agents = list(self._agents.values())
        await asyncio.gather(*(agent.stop() for agent in agents), return_exceptions=True)

    def _build_runtime_with_memory(self, config: AgentRuntimeConfig) -> MimicAgentRuntime:
        telegram_client = cast(TelegramClientLike, build_telegram_client(config))
        if self._memory_service_factory is None:
            memory_service = RuntimeMemoryService()
        else:
            memory_service = self._memory_service_factory(config)
        return MimicAgentRuntime(
            config=config,
            telegram_client=telegram_client,
            langchain_agent=build_langchain_agent(
                config,
                tools=build_telegram_langchain_tools(
                    cast(TelethonRequestClient, telegram_client),
                    agent_id=config.agent_id,
                    session_factory=self.session_factory,
                ),
            ),
            memory_service=memory_service,
            session_factory=self.session_factory,
        )

    async def _save_status(self, agent_id: UUID, state: AgentRuntimeState) -> None:
        if self._status_sink is None:
            return
        await _await_result(self._status_sink(agent_id, state))


def _build_runtime(
    config: AgentRuntimeConfig,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> MimicAgentRuntime:
    telegram_client = cast(TelegramClientLike, build_telegram_client(config))
    return MimicAgentRuntime(
        config=config,
        telegram_client=telegram_client,
        langchain_agent=build_langchain_agent(
            config,
            tools=build_telegram_langchain_tools(
                cast(TelethonRequestClient, telegram_client),
                agent_id=config.agent_id,
                session_factory=session_factory,
            ),
        ),
        session_factory=session_factory,
    )


async def _await_result(value: object) -> object:
    if inspect.isawaitable(value):
        return await value
    return value
