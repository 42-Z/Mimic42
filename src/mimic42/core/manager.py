from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Protocol, TypeVar, cast
from uuid import UUID

from langchain_core.tools import BaseTool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import (
    PROXY_CONNECT_ERRORS,
    REVOKED_SESSION_MESSAGE,
    AgentLifecycleChangedError,
    AgentRuntimeConfig,
    AgentRuntimeState,
    AgentStatus,
    AgentTrigger,
    AgentTriggerResult,
    LangChainAgentLike,
    MimicAgentRuntime,
    TelegramAuthorizationRequired,
    TelegramClientLike,
    TelegramTeardownPendingError,
    retry_previous_telegram_teardown,
)
from mimic42.core.chat_access import ChatAccess
from mimic42.core.chat_directory import ChatItem
from mimic42.core.media import MediaUploader
from mimic42.core.media_download import MediaRefCache
from mimic42.core.memory import RuntimeMemoryService
from mimic42.core.send_window import SendWindowTracker
from mimic42.core.telegram_account import (
    TelegramAccountClient,
    TelegramPasswordState,
    TelegramPasswordUpdate,
    TelegramSessionInvalidError,
    apply_password,
    apply_username,
    read_password_state,
)
from mimic42.core.warmup import WarmupState
from mimic42.core.warmup_service import (
    PairPolicy,
    WarmupHistory,
    WarmupService,
    WarmupStateStore,
    allow_everyone,
)
from mimic42.integrations.chat_directory import DirectoryClient, TelethonChatDirectory
from mimic42.integrations.langchain_agent import build_langchain_agent
from mimic42.integrations.telegram_tools import (
    TelethonRequestClient,
    build_telegram_langchain_tools,
)
from mimic42.integrations.telethon_client import build_telegram_client

logger = logging.getLogger("mimic42.agent_manager")


class AgentNotFoundError(KeyError):
    def __init__(self, agent_id: UUID) -> None:
        super().__init__(f"Agent {agent_id} does not exist")
        self.agent_id = agent_id


class TelegramRebindStep(StrEnum):
    STOP = "stop"
    RELOAD = "reload"


class TelegramRebindSequenceError(RuntimeError):
    """Шаг последовательности перепривязки упал: API называет виновный шаг."""

    def __init__(self, step: TelegramRebindStep) -> None:
        self.step = step
        super().__init__(step.value)


ResultT = TypeVar("ResultT")


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
        warmup_history: WarmupHistory | None = None,
        warmup_state_store: WarmupStateStore | None = None,
        warmup_pair_policy: PairPolicy = allow_everyone,
        proxy_direct_fallback: bool = False,
    ) -> None:
        self._runtime_factory = runtime_factory or _build_runtime
        self._memory_service_factory = memory_service_factory
        self._config_loader = config_loader
        self._status_sink = status_sink
        self.session_factory = session_factory
        self.media_uploader = media_uploader
        self._proxy_direct_fallback = proxy_direct_fallback
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
        self._removal_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        # Прогрев нужен только с постоянным хранилищем: без него нечем помнить, что уже
        # отправлено, и после рестарта агенты начали бы диалоги заново.
        self.warmup: WarmupService | None = (
            WarmupService(
                lambda: list(self._agents.values()),
                warmup_history,
                state_store=warmup_state_store,
                pair_policy=warmup_pair_policy,
            )
            if warmup_history is not None
            else None
        )
        self._agent_locks: dict[UUID, asyncio.Lock] = {}

    def _agent_lock(self, agent_id: UUID) -> asyncio.Lock:
        return self._agent_locks.setdefault(agent_id, asyncio.Lock())

    def _check_removed(self, agent_id: UUID) -> None:
        if agent_id in self._removed:
            raise AgentNotFoundError(agent_id)

    async def create_agent(
        self,
        config: AgentRuntimeConfig,
        *,
        start: bool = False,
    ) -> MimicAgentRuntime:
        if config.agent_id in self._removal_tasks:
            raise AgentNotFoundError(config.agent_id)
        async with self._agent_lock(config.agent_id):
            async with self._lock:
                if config.agent_id in self._removal_tasks:
                    raise AgentNotFoundError(config.agent_id)
                self._removed.discard(config.agent_id)
                runtime = self._register_locked(config)
            if start:
                runtime = await self._start_created_runtime(runtime)
            self._check_removed(config.agent_id)
            return runtime

    async def create_saved_agent(
        self,
        agent_id: UUID,
        *,
        owner_id: UUID,
        start: bool = False,
    ) -> MimicAgentRuntime:
        self._check_removed(agent_id)
        if self._config_loader is None:
            raise AgentNotFoundError(agent_id)
        reload_lock = self._agent_lock(agent_id)
        async with reload_lock:
            self._check_removed(agent_id)
            try:
                config = await _await_result(self._config_loader(agent_id))
            except KeyError as exc:
                raise AgentNotFoundError(agent_id) from exc
            if not isinstance(config, AgentRuntimeConfig):
                raise TypeError("config_loader must return AgentRuntimeConfig")
            if config.owner_id != owner_id:
                raise AgentNotFoundError(agent_id)
            async with self._lock:
                if agent_id in self._removed:
                    raise AgentNotFoundError(agent_id)
                runtime = self._register_locked(config)
            if start:
                runtime = await self._start_created_runtime(runtime)
            self._check_removed(agent_id)
            return runtime

    async def _start_created_runtime(self, runtime: MimicAgentRuntime) -> MimicAgentRuntime:
        try:
            return await self._start_runtime(runtime)
        except (TelegramTeardownPendingError, AgentNotFoundError, AgentLifecycleChangedError):
            raise
        except Exception:
            await self._save_status(runtime.config.agent_id, AgentRuntimeState.ERROR)
            raise

    async def _start_runtime(self, runtime: MimicAgentRuntime) -> MimicAgentRuntime:
        """Запустить рантайм; при сбое прокси повторить без него, если это разрешено.

        Политика ``proxy_direct_fallback`` задаётся приложением: по умолчанию сбой
        прокси остаётся фатальным, чтобы IP машины не уходил в Telegram без согласия.
        """
        self._check_removed(runtime.config.agent_id)
        await retry_previous_telegram_teardown(runtime)
        try:
            await runtime.start()
        except PROXY_CONNECT_ERRORS as exc:
            config = runtime.config
            if config.telegram_proxy is None or not config.proxy_direct_fallback:
                raise
            logger.warning(
                "Proxy %s:%s failed for agent %s (%s); retrying with a direct connection",
                config.telegram_proxy.host,
                config.telegram_proxy.port,
                config.agent_id,
                exc,
            )
            return await self._start_without_proxy(runtime)
        self._check_removed(runtime.config.agent_id)
        return runtime

    async def _start_without_proxy(self, runtime: MimicAgentRuntime) -> MimicAgentRuntime:
        config = runtime.config.model_copy(update={"telegram_proxy": None})
        await runtime.close()
        async with self._lock:
            self._check_removed(config.agent_id)
            replacement = self._build_runtime_for(config)
            if self.warmup is not None:
                replacement.set_warmup_gate(self.warmup)
            self._agents[config.agent_id] = replacement
        await replacement.start()
        self._check_removed(config.agent_id)
        return replacement

    def _register_locked(self, config: AgentRuntimeConfig) -> MimicAgentRuntime:
        self._check_removed(config.agent_id)
        if config.agent_id in self._agents:
            raise ValueError("Агент с этим ID уже существует")
        # Политика отката общая для приложения, а не настройка агента из базы.
        config = config.model_copy(update={"proxy_direct_fallback": self._proxy_direct_fallback})
        runtime = self._build_runtime_for(config)
        if self.warmup is not None:
            runtime.set_warmup_gate(self.warmup)
        self._agents[config.agent_id] = runtime
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
        self._check_removed(agent_id)
        async with self._agent_lock(agent_id):
            return await self._get_agent_locked(agent_id)

    async def _get_agent_locked(self, agent_id: UUID) -> MimicAgentRuntime:
        self._check_removed(agent_id)
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
        self._check_removed(agent_id)
        async with self._agent_lock(agent_id):
            await self._start_agent_locked(agent_id)

    async def _start_agent_locked(self, agent_id: UUID) -> MimicAgentRuntime:
        runtime = await self._get_agent_locked(agent_id)
        try:
            runtime = await self._start_runtime(runtime)
        except (TelegramTeardownPendingError, AgentNotFoundError, AgentLifecycleChangedError):
            raise
        except Exception:
            # Persist the failure: without this the database keeps the stale
            # status and the dashboard badge lies about the runtime state.
            await self._save_status(agent_id, AgentRuntimeState.ERROR)
            raise
        await self._save_status(agent_id, AgentRuntimeState.RUNNING)
        self._check_removed(agent_id)
        return runtime

    async def stop_agent(self, agent_id: UUID) -> None:
        self._check_removed(agent_id)
        async with self._agent_lock(agent_id):
            await self._stop_agent_locked(agent_id)

    async def _stop_agent_locked(self, agent_id: UUID) -> None:
        runtime = await self._get_agent_locked(agent_id)
        try:
            await retry_previous_telegram_teardown(runtime, wait=False)
            await runtime.stop()
        except (AgentNotFoundError, AgentLifecycleChangedError):
            raise
        except BaseException:
            await self._save_status_after_failure(runtime)
            raise
        self._check_removed(agent_id)
        await self._save_status(agent_id, AgentRuntimeState.STOPPED)

    async def reload_agent(self, agent_id: UUID) -> None:
        """Пересобрать конфигурацию, сохраняя владельца до завершения close.

        RUNNING/STARTING запускаются заново; STOPPED остаётся остановленным.
        Нематериализованный агент прочитает свежую конфигурацию при следующем get.
        """
        self._check_removed(agent_id)
        async with self._agent_lock(agent_id):
            await self._reload_agent_locked(agent_id)

    async def _reload_agent_locked(self, agent_id: UUID) -> None:
        self._check_removed(agent_id)
        async with self._lock:
            old_runtime = self._agents.get(agent_id)
        if old_runtime is None:
            # Not materialised in this process: the next get_agent/start
            # already reads the fresh config from the database.
            return
        was_active = old_runtime.status.state in (
            AgentRuntimeState.RUNNING,
            AgentRuntimeState.STARTING,
        )
        runtime = old_runtime
        try:
            await retry_previous_telegram_teardown(old_runtime)
            await old_runtime.close()
            async with self._lock:
                self._check_removed(agent_id)
                del self._agents[agent_id]
            runtime = await self._get_agent_locked(agent_id)
            if was_active:
                runtime = await self._start_runtime(runtime)
        except BaseException:
            if agent_id not in self._removed:
                await self._save_status_after_failure(self._agents.get(agent_id, runtime))
            raise
        await self._save_status(agent_id, runtime.state)

    async def confirm_telegram_rebind(
        self,
        agent_id: UUID,
        apply: Callable[[], Awaitable[ResultT]],
    ) -> ResultT:
        """Остановить, применить сессию и пересобрать рантайм под одним замком.

        Операция с аккаунтом не должна попасть в окно между stop и reload:
        иначе настройки уйдут в рантайм, который сейчас снимут.
        """
        self._check_removed(agent_id)
        async with self._agent_lock(agent_id):
            try:
                await self._stop_agent_locked(agent_id)
            except Exception as exc:
                raise TelegramRebindSequenceError(TelegramRebindStep.STOP) from exc
            self._check_removed(agent_id)
            result = await apply()
            self._check_removed(agent_id)
            try:
                await self._reload_agent_locked(agent_id)
            except Exception as exc:
                raise TelegramRebindSequenceError(TelegramRebindStep.RELOAD) from exc
            return result

    async def remove_agent(self, agent_id: UUID) -> None:
        """Сразу скрыть агента и дождаться сериализованного закрытия его владельца."""
        async with self._lock:
            cleanup = self._removal_tasks.get(agent_id)
            if cleanup is None:
                self._removed.add(agent_id)
                runtime = self._agents.pop(agent_id, None)
                if runtime is None:
                    return
                cleanup = asyncio.create_task(self._finish_removal(agent_id, runtime))
                self._removal_tasks[agent_id] = cleanup
                cleanup.add_done_callback(self._removal_finished)
        await asyncio.shield(cleanup)

    @staticmethod
    def _removal_finished(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Agent removal cleanup failed", exc_info=error)

    async def _finish_removal(self, agent_id: UUID, runtime: MimicAgentRuntime) -> None:
        async with self._agent_lock(agent_id):
            try:
                await retry_previous_telegram_teardown(runtime, wait=False)
                await runtime.close()
            except BaseException:
                async with self._lock:
                    self._agents[agent_id] = runtime
                    self._removed.discard(agent_id)
                await self._save_status_after_failure(runtime)
                raise
            finally:
                self._removal_tasks.pop(agent_id, None)

    async def trigger_message(
        self,
        agent_id: UUID,
        trigger: AgentTrigger,
    ) -> AgentTriggerResult:
        self._check_removed(agent_id)
        async with self._agent_lock(agent_id):
            runtime = await self._get_agent_locked(agent_id)
            if runtime.session_revoked:
                raise TelegramAuthorizationRequired(REVOKED_SESSION_MESSAGE)
            if runtime.state is not AgentRuntimeState.RUNNING:
                runtime = await self._start_agent_locked(agent_id)
        return await runtime._trigger_running_message(trigger)

    async def get_warmup_state(self, agent_id: UUID) -> WarmupState:
        """Ограничение аккаунта и режим восстановления: то, по чему агент работает сейчас."""
        runtime = await self.get_agent(agent_id)
        return WarmupState(
            restricted_at=runtime.warmup_restricted_at, recovery=runtime.warmup_recovery
        )

    async def start_warmup_recovery(self, agent_id: UUID) -> bool:
        """Пользователь выбрал восстановление. False — агент не ограничен."""
        await self.get_agent(agent_id)
        if self.warmup is None:
            return False
        return await self.warmup.start_recovery(agent_id)

    async def list_chats(self, agent_id: UUID) -> list[ChatItem]:
        """Диалоги аккаунта агента; у остановленного рантайма — ChatListUnavailableError."""
        return await (await self.get_agent(agent_id)).list_chats()

    async def get_telegram_password_state(self, agent_id: UUID) -> TelegramPasswordState:
        self._check_removed(agent_id)
        async with self._agent_lock(agent_id):
            runtime = await self._get_agent_locked(agent_id)
            return await self._lease_account(runtime, read_password_state)

    async def change_telegram_username(self, agent_id: UUID, username: str) -> str:
        self._check_removed(agent_id)
        async with self._agent_lock(agent_id):
            runtime = await self._get_agent_locked(agent_id)
            confirmed = await self._lease_account(
                runtime, lambda client: apply_username(client, username)
            )
            await runtime.persist_telegram_username(confirmed)
            return confirmed

    async def change_telegram_password(
        self, agent_id: UUID, change: TelegramPasswordUpdate
    ) -> None:
        self._check_removed(agent_id)
        async with self._agent_lock(agent_id):
            runtime = await self._get_agent_locked(agent_id)
            await self._lease_account(runtime, lambda client: apply_password(client, change))

    async def _lease_account(
        self,
        runtime: MimicAgentRuntime,
        operation: Callable[[TelegramAccountClient], Awaitable[ResultT]],
    ) -> ResultT:
        try:
            async with runtime.leased_telegram_client() as client:
                return await operation(cast(TelegramAccountClient, client))
        except TelegramAuthorizationRequired as exc:
            await runtime.mark_telegram_session_revoked()
            raise TelegramSessionInvalidError() from exc
        except TelegramSessionInvalidError:
            await runtime.mark_telegram_session_revoked()
            raise

    async def shutdown(self) -> None:
        if self.warmup is not None:
            await self.warmup.stop()
        await asyncio.gather(
            *(self._close_agent(agent_id) for agent_id in list(self._agents)),
            *(asyncio.shield(task) for task in list(self._removal_tasks.values())),
            return_exceptions=True,
        )

    async def _close_agent(self, agent_id: UUID) -> None:
        async with self._agent_lock(agent_id):
            runtime = self._agents.get(agent_id)
            if runtime is not None:
                await retry_previous_telegram_teardown(runtime, wait=False)
                await runtime.close()

    def _build_runtime_with_memory(self, config: AgentRuntimeConfig) -> MimicAgentRuntime:
        telegram_client = self._telegram_client_factory(config)
        send_window = SendWindowTracker(telegram_client)
        if self._memory_service_factory is None:
            memory_service = RuntimeMemoryService()
        else:
            memory_service = self._memory_service_factory(config)
        media_refs = MediaRefCache()
        directory = _chat_directory_for(telegram_client)
        chat_access = _chat_access_for(config, directory)
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
                    media_refs=media_refs,
                    enabled_tools=config.enabled_tools,
                    chat_access=chat_access,
                ),
                self.session_factory,
            ),
            memory_service=memory_service,
            session_factory=self.session_factory,
            media_uploader=self.media_uploader,
            send_window=send_window,
            media_refs=media_refs,
            chat_access=chat_access,
            chat_directory=directory,
        )

    async def _save_status_after_failure(self, runtime: MimicAgentRuntime) -> None:
        try:
            await self._save_status(runtime.config.agent_id, runtime.state)
        except Exception:
            logger.exception(
                "Failed to persist state after agent %s lifecycle failure", runtime.config.agent_id
            )

    async def _save_status(self, agent_id: UUID, state: AgentRuntimeState) -> None:
        if self._status_sink is None:
            return
        await _await_result(self._status_sink(agent_id, state))


def _chat_directory_for(telegram_client: TelegramClientLike) -> TelethonChatDirectory:
    return TelethonChatDirectory(cast(DirectoryClient, telegram_client))


def _chat_access_for(
    config: AgentRuntimeConfig, directory: TelethonChatDirectory
) -> ChatAccess | None:
    """Правило доступа есть только у агента с отключёнными чатами."""
    if not config.disabled_chats:
        return None
    return ChatAccess(config.disabled_chats, directory.discussion_of)


def _build_runtime(
    config: AgentRuntimeConfig,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    media_uploader: MediaUploader | None = None,
) -> MimicAgentRuntime:
    telegram_client = cast(TelegramClientLike, build_telegram_client(config))
    send_window = SendWindowTracker(telegram_client)
    media_refs = MediaRefCache()
    directory = _chat_directory_for(telegram_client)
    chat_access = _chat_access_for(config, directory)
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
                media_refs=media_refs,
                enabled_tools=config.enabled_tools,
                chat_access=chat_access,
            ),
            session_factory=session_factory,
        ),
        session_factory=session_factory,
        media_uploader=media_uploader,
        send_window=send_window,
        media_refs=media_refs,
        chat_access=chat_access,
        chat_directory=directory,
    )


async def _await_result(value: object) -> object:
    if inspect.isawaitable(value):
        return await value
    return value
