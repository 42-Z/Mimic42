from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentRuntimeState,
    MimicAgentRuntime,
    TelegramProxyConfig,
)
from mimic42.core.manager import AgentManager, AgentNotFoundError

from .test_agent_runtime import FakeLangChainAgent, FakeTelegramClient


def _config() -> AgentRuntimeConfig:
    agent_id = uuid4()
    return AgentRuntimeConfig(
        agent_id=agent_id,
        owner_id=uuid4(),
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


@pytest.mark.parametrize("auto_start", [False, True])
async def test_saved_creation_rejects_removal_during_config_load(auto_start: bool) -> None:
    config = _config()
    loaded = asyncio.Event()
    release = asyncio.Event()
    clients: list[FakeTelegramClient] = []

    async def load_config(agent_id: UUID) -> AgentRuntimeConfig:
        assert agent_id == config.agent_id
        loaded.set()
        await release.wait()
        return config

    def runtime_factory(runtime_config: AgentRuntimeConfig) -> MimicAgentRuntime:
        client = FakeTelegramClient()
        clients.append(client)
        return MimicAgentRuntime(
            config=runtime_config, telegram_client=client, langchain_agent=FakeLangChainAgent()
        )

    manager = AgentManager(runtime_factory=runtime_factory, config_loader=load_config)
    creating = asyncio.create_task(
        manager.create_saved_agent(config.agent_id, owner_id=config.owner_id, start=auto_start)
    )
    try:
        async with asyncio.timeout(5):
            await loaded.wait()
            await manager.remove_agent(config.agent_id)
            release.set()
            with pytest.raises(AgentNotFoundError):
                await creating

        assert await manager.list_agents() == []
        assert clients == []
        with pytest.raises(AgentNotFoundError):
            await manager.get_agent(config.agent_id)
    finally:
        release.set()
        creating.cancel()
        await asyncio.gather(creating, return_exceptions=True)
        await manager.shutdown()


@pytest.mark.parametrize("operation", ["get", "start", "stop"])
async def test_reload_blocks_lifecycle_requests_until_old_runtime_is_closed(
    operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config()
    disconnecting = asyncio.Event()
    release = asyncio.Event()
    requested = asyncio.Event()
    clients: list[FakeTelegramClient] = []
    runtimes: list[MimicAgentRuntime] = []
    monkeypatch.setattr("mimic42.core.agent_runtime.STOP_STEP_TIMEOUT_SECONDS", 30)

    class GatedDisconnectClient(FakeTelegramClient):
        async def disconnect(self) -> None:
            disconnecting.set()
            await release.wait()
            await super().disconnect()

    def runtime_factory(runtime_config: AgentRuntimeConfig) -> MimicAgentRuntime:
        client = GatedDisconnectClient() if not clients else FakeTelegramClient()
        clients.append(client)
        runtime = MimicAgentRuntime(
            config=runtime_config, telegram_client=client, langchain_agent=FakeLangChainAgent()
        )
        runtimes.append(runtime)
        return runtime

    manager = AgentManager(runtime_factory=runtime_factory, config_loader=lambda agent_id: config)
    old_runtime = await manager.create_agent(config, start=True)

    async def request() -> MimicAgentRuntime | None:
        requested.set()
        if operation == "get":
            return await manager.get_agent(config.agent_id)
        if operation == "start":
            await manager.start_agent(config.agent_id)
        else:
            await manager.stop_agent(config.agent_id)
        return None

    reloading = asyncio.create_task(manager.reload_agent(config.agent_id))
    requesting: asyncio.Task[MimicAgentRuntime | None] | None = None
    try:
        async with asyncio.timeout(5):
            await disconnecting.wait()
            requesting = asyncio.create_task(request())
            await requested.wait()

            assert clients[0].connected
            assert len(clients) == 1, "replacement materialized before old runtime closed"
            assert not requesting.done(), "lifecycle request completed during reload teardown"

            release.set()
            await asyncio.gather(reloading, requesting)

        replacement = await manager.get_agent(config.agent_id)
        assert replacement is not old_runtime
        assert len(clients) == 2
        assert old_runtime.state is AgentRuntimeState.STOPPED
        assert not clients[0].connected
        assert clients[0].connect_calls == 1
        assert replacement.state is (
            AgentRuntimeState.STOPPED if operation == "stop" else AgentRuntimeState.RUNNING
        )
        assert clients[1].connected is (operation != "stop")
        if operation == "get":
            assert requesting.result() is replacement
    finally:
        release.set()
        tasks: list[asyncio.Task[object]] = [reloading]
        if requesting is not None:
            tasks.append(requesting)
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(runtime.close() for runtime in runtimes))


async def test_reload_waits_for_start_before_connect_and_does_not_restart_closed_runtime() -> None:
    config = _config()
    connecting = asyncio.Event()
    release = asyncio.Event()
    reload_requested = asyncio.Event()
    clients: list[FakeTelegramClient] = []
    models: list[FakeLangChainAgent] = []
    runtimes: list[MimicAgentRuntime] = []

    class GatedConnectClient(FakeTelegramClient):
        async def connect(self) -> None:
            connecting.set()
            await release.wait()
            await super().connect()

    def runtime_factory(runtime_config: AgentRuntimeConfig) -> MimicAgentRuntime:
        client = GatedConnectClient() if not clients else FakeTelegramClient()
        model = FakeLangChainAgent()
        clients.append(client)
        models.append(model)
        runtime = MimicAgentRuntime(
            config=runtime_config, telegram_client=client, langchain_agent=model
        )
        runtimes.append(runtime)
        return runtime

    manager = AgentManager(runtime_factory=runtime_factory, config_loader=lambda agent_id: config)
    old_runtime = await manager.create_agent(config)

    async def reload() -> None:
        reload_requested.set()
        await manager.reload_agent(config.agent_id)

    starting = asyncio.create_task(manager.start_agent(config.agent_id))
    reloading: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(5):
            await connecting.wait()
            reloading = asyncio.create_task(reload())
            await reload_requested.wait()

            assert not reloading.done()
            assert len(clients) == 1
            assert not clients[0].connected
            release.set()
            await asyncio.gather(starting, reloading)

        replacement = await manager.get_agent(config.agent_id)
        assert replacement is not old_runtime
        assert len(clients) == 2
        assert old_runtime.state is AgentRuntimeState.STOPPED
        assert models[0].closed
        assert not clients[0].connected
        assert clients[0].connect_calls == 1
        assert clients[0].disconnect_calls == 1
        assert replacement.state is AgentRuntimeState.RUNNING
        assert clients[1].connected
        assert clients[1].connect_calls == 1
        assert not models[1].closed
    finally:
        release.set()
        tasks: list[asyncio.Task[object]] = [starting]
        if reloading is not None:
            tasks.append(reloading)
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(runtime.close() for runtime in runtimes))


async def test_start_during_rebind_waits_for_the_new_telegram_session() -> None:
    config = _config()
    applying = asyncio.Event()
    release = asyncio.Event()
    start_requested = asyncio.Event()
    clients: list[FakeTelegramClient] = []
    runtimes: list[MimicAgentRuntime] = []
    connected_sessions: list[str | None] = []

    def runtime_factory(runtime_config: AgentRuntimeConfig) -> MimicAgentRuntime:
        class Client(FakeTelegramClient):
            async def connect(self) -> None:
                connected_sessions.append(runtime_config.telegram_session_string)
                await super().connect()

        client = Client()
        clients.append(client)
        runtime = MimicAgentRuntime(
            config=runtime_config, telegram_client=client, langchain_agent=FakeLangChainAgent()
        )
        runtimes.append(runtime)
        return runtime

    manager = AgentManager(runtime_factory=runtime_factory, config_loader=lambda agent_id: config)
    old_runtime = await manager.create_agent(config, start=True)

    async def apply() -> str:
        nonlocal config
        applying.set()
        await release.wait()
        config = config.model_copy(update={"telegram_session_string": "new-session"})
        return "confirmed"

    async def start() -> None:
        start_requested.set()
        await manager.start_agent(config.agent_id)

    confirming = asyncio.create_task(manager.confirm_telegram_rebind(config.agent_id, apply))
    starting: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(5):
            await applying.wait()
            starting = asyncio.create_task(start())
            await start_requested.wait()

            assert connected_sessions == ["session"], "start reconnected the session being replaced"
            assert not clients[0].connected
            assert not starting.done()
            release.set()
            result, _ = await asyncio.gather(confirming, starting)

        replacement = await manager.get_agent(config.agent_id)
        assert result == "confirmed"
        assert replacement is not old_runtime
        assert old_runtime.state is AgentRuntimeState.STOPPED
        assert not clients[0].connected
        assert replacement.config.telegram_session_string == "new-session"
        assert replacement.state is AgentRuntimeState.RUNNING
        assert connected_sessions == ["session", "new-session"]
        assert len(clients) == 2
        assert clients[1].connected
    finally:
        release.set()
        tasks: list[asyncio.Task[object]] = [confirming]
        if starting is not None:
            tasks.append(starting)
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(runtime.close() for runtime in runtimes))


@pytest.mark.parametrize("auto_start", [False, True])
async def test_saved_creation_rechecks_removal_when_registration_lock_is_released(
    auto_start: bool,
) -> None:
    config = _config()
    removing_entered = asyncio.Event()
    loaded = asyncio.Event()
    clients: list[FakeTelegramClient] = []

    async def load_config(agent_id: UUID) -> AgentRuntimeConfig:
        assert agent_id == config.agent_id
        loaded.set()
        return config

    def runtime_factory(runtime_config: AgentRuntimeConfig) -> MimicAgentRuntime:
        client = FakeTelegramClient()
        clients.append(client)
        return MimicAgentRuntime(
            config=runtime_config, telegram_client=client, langchain_agent=FakeLangChainAgent()
        )

    manager = AgentManager(runtime_factory=runtime_factory, config_loader=load_config)

    async def remove_agent() -> None:
        removing_entered.set()
        await manager.remove_agent(config.agent_id)

    creating: asyncio.Task[MimicAgentRuntime] | None = None
    removing: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(5):
            async with manager._lock:
                removing = asyncio.create_task(remove_agent())
                await removing_entered.wait()
                creating = asyncio.create_task(
                    manager.create_saved_agent(
                        config.agent_id, owner_id=config.owner_id, start=auto_start
                    )
                )
                await loaded.wait()
            await removing
            with pytest.raises(AgentNotFoundError):
                await creating

        assert await manager.list_agents() == []
        assert clients == []
        with pytest.raises(AgentNotFoundError):
            await manager.get_agent(config.agent_id)
    finally:
        if creating is not None:
            creating.cancel()
            await asyncio.gather(creating, return_exceptions=True)
        if removing is not None:
            removing.cancel()
            await asyncio.gather(removing, return_exceptions=True)
        await manager.shutdown()


@pytest.mark.parametrize("auto_start", [False, True])
async def test_saved_creation_rejects_removal_while_old_runtime_is_closing(
    auto_start: bool,
) -> None:
    config = _config()
    closing = asyncio.Event()
    release = asyncio.Event()
    clients: list[FakeTelegramClient] = []

    class SlowCloseRuntime(MimicAgentRuntime):
        async def close(self) -> None:
            closing.set()
            await release.wait()
            await super().close()

    def runtime_factory(runtime_config: AgentRuntimeConfig) -> MimicAgentRuntime:
        client = FakeTelegramClient()
        clients.append(client)
        return SlowCloseRuntime(
            config=runtime_config, telegram_client=client, langchain_agent=FakeLangChainAgent()
        )

    manager = AgentManager(runtime_factory=runtime_factory, config_loader=lambda agent_id: config)
    old_runtime = await manager.create_agent(config, start=True)
    removing = asyncio.create_task(manager.remove_agent(config.agent_id))
    try:
        async with asyncio.timeout(5):
            await closing.wait()
            assert old_runtime.state is AgentRuntimeState.RUNNING
            assert clients[0].connected
            with pytest.raises(AgentNotFoundError):
                await manager.create_saved_agent(
                    config.agent_id, owner_id=config.owner_id, start=auto_start
                )

            assert not removing.done()
            assert await manager.list_agents() == []
            assert len(clients) == 1
            release.set()
            await removing

        assert old_runtime.state is AgentRuntimeState.STOPPED
        assert not clients[0].connected
        assert await manager.list_agents() == []
        with pytest.raises(AgentNotFoundError):
            await manager.get_agent(config.agent_id)
    finally:
        release.set()
        await removing
        await manager.shutdown()


async def test_saved_creation_start_failure_persists_error_status() -> None:
    config = _config()
    updates: list[tuple[UUID, AgentRuntimeState]] = []

    class FailingStartClient(FakeTelegramClient):
        async def connect(self) -> None:
            raise RuntimeError("connect failed")

    manager = AgentManager(
        runtime_factory=lambda runtime_config: MimicAgentRuntime(
            config=runtime_config,
            telegram_client=FailingStartClient(),
            langchain_agent=FakeLangChainAgent(),
        ),
        config_loader=lambda agent_id: config,
        status_sink=lambda agent_id, state: updates.append((agent_id, state)),
    )
    try:
        with pytest.raises(RuntimeError, match="connect failed"):
            await manager.create_saved_agent(config.agent_id, owner_id=config.owner_id, start=True)

        assert updates == [(config.agent_id, AgentRuntimeState.ERROR)]
        assert (await manager.get_agent(config.agent_id)).state is AgentRuntimeState.ERROR
    finally:
        await manager.shutdown()


@pytest.mark.parametrize(
    ("pause_at", "auto_start"), [("load", False), ("load", True), ("start", True)]
)
async def test_saved_creation_serializes_config_load_and_start_with_admin_reload(
    pause_at: str, auto_start: bool
) -> None:
    config = _config()
    old_proxy = TelegramProxyConfig(protocol="socks5", host="old.invalid", port=1080)
    new_proxy = TelegramProxyConfig(protocol="socks5", host="new.invalid", port=1080)
    config.telegram_proxy = old_proxy
    paused = asyncio.Event()
    release = asyncio.Event()
    reload_entered = asyncio.Event()
    connected_routes: list[TelegramProxyConfig | None] = []

    async def load_config(agent_id: UUID) -> AgentRuntimeConfig:
        assert agent_id == config.agent_id
        snapshot = config
        if pause_at == "load" and not paused.is_set():
            paused.set()
            await release.wait()
        return snapshot

    def runtime_factory(runtime_config: AgentRuntimeConfig) -> MimicAgentRuntime:
        class Client(FakeTelegramClient):
            async def connect(self) -> None:
                if pause_at == "start" and not paused.is_set():
                    paused.set()
                    await release.wait()
                connected_routes.append(runtime_config.telegram_proxy)
                await super().connect()

        return MimicAgentRuntime(
            config=runtime_config, telegram_client=Client(), langchain_agent=FakeLangChainAgent()
        )

    manager = AgentManager(runtime_factory=runtime_factory, config_loader=load_config)

    async def admin_reload() -> None:
        reload_entered.set()
        await manager.reload_agent(config.agent_id)

    creating = asyncio.create_task(
        manager.create_saved_agent(config.agent_id, owner_id=config.owner_id, start=auto_start)
    )
    reloading: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(5):
            await paused.wait()
            config = config.model_copy(update={"telegram_proxy": new_proxy})
            reloading = asyncio.create_task(admin_reload())
            await reload_entered.wait()
            assert not reloading.done()
            release.set()
            await asyncio.gather(creating, reloading)

        runtime = await manager.get_agent(config.agent_id)
        assert runtime.config.telegram_proxy == new_proxy
        assert runtime.state == (
            AgentRuntimeState.RUNNING if auto_start else AgentRuntimeState.STOPPED
        )
        assert connected_routes == ([old_proxy, new_proxy] if auto_start else [])
    finally:
        release.set()
        creating.cancel()
        if reloading is not None:
            reloading.cancel()
            await asyncio.gather(reloading, return_exceptions=True)
        await asyncio.gather(creating, return_exceptions=True)
        await manager.shutdown()
