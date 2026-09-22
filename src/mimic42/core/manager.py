from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Protocol, cast
from uuid import UUID

from langchain_core.tools import BaseTool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentRuntimeState,
    AgentStatus,
    AgentTrigger,
    AgentTriggerResult,
    LangChainAgentLike,
    MimicAgentRuntime,
    TelegramClientLike,
)
from mimic42.core.media import MediaUploader
from mimic42.core.memory import RuntimeMemoryService
from mimic42.core.send_window import SendWindowTracker
from mimic42.integrations.langchain_agent import build_langchain_agent
from mimic42.integrations.telegram_tools import (
    TelethonRequestClient,
    build_telegram_langchain_tools,
)
from mimic42.integrations.telethon_client import build_telegram_client


class AgentNotFoundError(KeyError):
    def __init__(self, agent_id: UUID) -> None:
        super().__init__(f"Agent {agent_id} does not exist")
        self.agent_id = agent_id


RuntimeFactory = Callable[[AgentRuntimeConfig], MimicAgentRuntime]
MemoryServiceFactory = Callable[[AgentRuntimeConfig], RuntimeMemoryService]
ConfigLoader = Callable[[UUID], object]
StatusSink = Callable[[UUID, AgentRuntimeState], object]
TelegramClientFactory = Callable[[AgentRuntimeConfig], TelegramClientLike]
LangChainAgentFactory = Callable[
    [AgentRuntimeConfig, list[BaseTool], "async_sessionmaker[AsyncSession] | None"],
    LangChainAgentLike,
]


class RuntimeFactoryWithSession(Protocol):
    def __call__(
        self,
        config: AgentRuntimeConfig,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None,
    ) -> MimicAgentRuntime: ...


class RuntimeFactoryWithMedia(Protocol):
    def __call__(
        self,
        config: AgentRuntimeConfig,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        media_uploader: MediaUploader | None = None,
    ) -> MimicAgentRuntime: ...


class RuntimeFactoryWithMediaOnly(Protocol):
    def __call__(
        self,
        config: AgentRuntimeConfig,
        *,
        media_uploader: MediaUploader | None = None,
    ) -> MimicAgentRuntime: ...


class AgentManager:
    """In-process async registry for multiple users and their agent runtimes."""

    def __init__(
        self,
        runtime_factory: RuntimeFactory | None = None,
        memory_service_factory: MemoryServiceFactory | None = None,
        config_loader: ConfigLoader | None = None,
        status_sink: StatusSink | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        telegram_client_factory: TelegramClientFactory | None = None,
        langchain_agent_factory: LangChainAgentFactory | None = None,
        media_uploader: MediaUploader | None = None,
    ) -> None:
        self._runtime_factory = runtime_factory or _build_runtime
        self._memory_service_factory = memory_service_factory
        self._config_loader = config_loader
        self._status_sink = status_sink
        self.session_factory = session_factory
        self.media_uploader = media_uploader
        self._telegram_client_factory: TelegramClientFactory = telegram_client_factory or (
            lambda config: cast(TelegramClientLike, build_telegram_client(config))
        )
        self._langchain_agent_factory: LangChainAgentFactory = langchain_agent_factory or (
            lambda config, tools, session_factory: build_langchain_agent(
                config, tools=tools, session_factory=session_factory
            )
        )
        self._agents: dict[UUID, MimicAgentRuntime] = {}
        self._removed: set[UUID] = set()
        self._lock = asyncio.Lock()

    async def create_agent(
        self,
        config: AgentRuntimeConfig,
        *,
        start: bool = False,
    ) -> MimicAgentRuntime:
        async with self._lock:
            runtime = self._register_locked(config)
        if start:
            await runtime.start()
        return runtime

    def _register_locked(self, config: AgentRuntimeConfig) -> MimicAgentRuntime:
        """Собрать и положить рантайм в реестр. Вызывать только под ``_lock``."""
        if config.agent_id in self._agents:
            raise ValueError("Агент с этим ID уже существует")
        runtime = self._build_runtime_for(config)
        self._agents[config.agent_id] = runtime
        self._removed.discard(config.agent_id)
        return runtime

    def _build_runtime_for(self, config: AgentRuntimeConfig) -> MimicAgentRuntime:
        if self._memory_service_factory is not None:
            return self._build_runtime_with_memory(config)
        sig = inspect.signature(self._runtime_factory)
        accepts_session = "session_factory" in sig.parameters
        accepts_media = "media_uploader" in sig.parameters
        if accepts_media:
            if accepts_session:
                factory_with_media = cast(RuntimeFactoryWithMedia, self._runtime_factory)
                return factory_with_media(
                    config,
                    session_factory=self.session_factory,
                    media_uploader=self.media_uploader,
                )
            factory_with_media_only = cast(RuntimeFactoryWithMediaOnly, self._runtime_factory)
            return factory_with_media_only(config, media_uploader=self.media_uploader)
        if accepts_session:
            factory_with_session = cast(RuntimeFactoryWithSession, self._runtime_factory)
            return factory_with_session(
                config,
                session_factory=self.session_factory,
            )
        return self._runtime_factory(config)

    async def get_agent(self, agent_id: UUID) -> MimicAgentRuntime:
        if agent_id in self._removed:
            # The agent was deleted during this process lifetime: never
            # re-materialise it from the persistent config.
            raise AgentNotFoundError(agent_id)
        agent = self._agents.get(agent_id)
        if agent is not None:
            return agent
        if self._config_loader is None:
            raise AgentNotFoundError(agent_id)
        try:
            config = await _await_result(self._config_loader(agent_id))
        except KeyError as exc:
            # The config loader signals a missing agent row with KeyError.
            raise AgentNotFoundError(agent_id) from exc
        if not isinstance(config, AgentRuntimeConfig):
            raise TypeError("config_loader must return AgentRuntimeConfig")
        async with self._lock:
            # Повторная проверка под локом: конкурентные обращения к одному
            # агенту (например, поллинг статуса и триггер) не должны оба
            # собирать рантайм — второй получал бы «already exists».
            if agent_id in self._removed:
                raise AgentNotFoundError(agent_id)
            existing = self._agents.get(agent_id)
            if existing is not None:
                return existing
            return self._register_locked(config)

    async def get_agent_status(self, agent_id: UUID) -> AgentStatus:
        return (await self.get_agent(agent_id)).status

    async def list_agents(self, *, owner_id: UUID | None = None) -> list[AgentStatus]:
        agents = list(self._agents.values())
        if owner_id is not None:
            agents = [agent for agent in agents if agent.config.owner_id == owner_id]
        return [agent.status for agent in agents]

    async def start_agent(self, agent_id: UUID) -> None:
        try:
            await (await self.get_agent(agent_id)).start()
        except Exception:
            # Persist the failure: without this the database keeps the stale
            # status and the dashboard badge lies about the runtime state.
            await self._save_status(agent_id, AgentRuntimeState.ERROR)
            raise
        await self._save_status(agent_id, AgentRuntimeState.RUNNING)

    async def stop_agent(self, agent_id: UUID) -> None:
        await (await self.get_agent(agent_id)).stop()
        await self._save_status(agent_id, AgentRuntimeState.STOPPED)

    async def reload_agent(self, agent_id: UUID) -> None:
        """Rebuild the runtime from the persistent config.

        The runtime is built once and never hot-reloads its config, so
        settings changes (model, prompts) require a rebuild: stop the old
        runtime, drop it from the registry and re-materialise from the
        config loader. No tombstone is set — the agent still exists in the
        database. A runtime that was RUNNING is started again.
        """
        async with self._lock:
            old_runtime = self._agents.pop(agent_id, None)
        if old_runtime is None:
            # Not materialised in this process: the next get_agent/start
            # already reads the fresh config from the database.
            return
        was_running = old_runtime.status.state is AgentRuntimeState.RUNNING
        await old_runtime.close()
        runtime = await self.get_agent(agent_id)
        if was_running:
            try:
                await runtime.start()
            except Exception:
                # Persist the failure like start_agent does: without this the
                # database keeps RUNNING while the rebuilt runtime is ERROR.
                await self._save_status(agent_id, AgentRuntimeState.ERROR)
                raise

    async def remove_agent(self, agent_id: UUID) -> None:
        """Unregister the agent runtime and stop it. Missing agents are ignored.

        Failures of ``stop`` propagate to the caller so the deletion flow can
        abort before removing the database rows. On failure the tombstone is
        lifted: the agent row is still in the database, so the next
        ``get_agent`` re-creates the runtime from scratch (a fresh object).
        """
        async with self._lock:
            # Tombstone and pop must happen under one lock: a concurrent
            # get_agent landing in the window between them would re-materialise
            # the runtime from the persistent config and leak it.
            self._removed.add(agent_id)
            runtime = self._agents.pop(agent_id, None)
        try:
            if runtime is not None:
                await runtime.close()
        except Exception:
            async with self._lock:
                self._removed.discard(agent_id)
            raise

    async def trigger_message(
        self,
        agent_id: UUID,
        trigger: AgentTrigger,
    ) -> AgentTriggerResult:
        return await (await self.get_agent(agent_id)).trigger_message(trigger)

    async def shutdown(self) -> None:
        agents = list(self._agents.values())
        await asyncio.gather(*(agent.close() for agent in agents), return_exceptions=True)

    def _build_runtime_with_memory(self, config: AgentRuntimeConfig) -> MimicAgentRuntime:
        telegram_client = self._telegram_client_factory(config)
        send_window = SendWindowTracker(telegram_client)
        if self._memory_service_factory is None:
            memory_service = RuntimeMemoryService()
        else:
            memory_service = self._memory_service_factory(config)
        return MimicAgentRuntime(
            config=config,
            telegram_client=telegram_client,
            langchain_agent=self._langchain_agent_factory(
                config,
                build_telegram_langchain_tools(
                    cast(TelethonRequestClient, telegram_client),
                    agent_id=config.agent_id,
                    session_factory=self.session_factory,
                    media_uploader=self.media_uploader,
                    send_window=send_window,
                ),
                self.session_factory,
            ),
            memory_service=memory_service,
            session_factory=self.session_factory,
            media_uploader=self.media_uploader,
            send_window=send_window,
        )

    async def _save_status(self, agent_id: UUID, state: AgentRuntimeState) -> None:
        if self._status_sink is None:
            return
        await _await_result(self._status_sink(agent_id, state))


def _build_runtime(
    config: AgentRuntimeConfig,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    media_uploader: MediaUploader | None = None,
) -> MimicAgentRuntime:
    telegram_client = cast(TelegramClientLike, build_telegram_client(config))
    send_window = SendWindowTracker(telegram_client)
    return MimicAgentRuntime(
        config=config,
        telegram_client=telegram_client,
        langchain_agent=build_langchain_agent(
            config,
            tools=build_telegram_langchain_tools(
                cast(TelethonRequestClient, telegram_client),
                agent_id=config.agent_id,
                session_factory=session_factory,
                media_uploader=media_uploader,
                send_window=send_window,
            ),
            session_factory=session_factory,
        ),
        session_factory=session_factory,
        media_uploader=media_uploader,
        send_window=send_window,
    )


async def _await_result(value: object) -> object:
    if inspect.isawaitable(value):
        return await value
    return value
