from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mimic42.core.agent_runtime import (
    AgentLifecycleChangedError,
    AgentRuntimeConfig,
    AgentRuntimeState,
    AgentTrigger,
    AgentTriggerResult,
    MimicAgentRuntime,
    TelegramTeardownPendingError,
)
from mimic42.core.manager import AgentManager, AgentNotFoundError, TelegramRebindSequenceError

from .test_agent_runtime import FakeLangChainAgent, FakeTelegramClient, make_config


async def test_cancelled_reload_keeps_owner_and_blocks_another_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mimic42.core.agent_runtime.TELEGRAM_TEARDOWN_WAIT_SECONDS", 0.01)
    disconnecting = asyncio.Event()
    release = asyncio.Event()
    config = make_config()

    class Client(FakeTelegramClient):
        async def disconnect(self) -> None:
            disconnecting.set()
            await release.wait()
            await super().disconnect()

    client = Client()
    manager = AgentManager(
        runtime_factory=lambda saved: MimicAgentRuntime(
            config=saved, telegram_client=client, langchain_agent=FakeLangChainAgent()
        ),
        config_loader=lambda agent_id: config,
    )
    owner = await manager.create_agent(config, start=True)
    other_client = FakeTelegramClient()
    other = MimicAgentRuntime(
        config=config, telegram_client=other_client, langchain_agent=FakeLangChainAgent()
    )
    reloading = asyncio.create_task(manager.reload_agent(config.agent_id))
    try:
        async with asyncio.timeout(5):
            await disconnecting.wait()
            reloading.cancel()
            with pytest.raises(asyncio.CancelledError):
                await reloading
            with pytest.raises(TelegramTeardownPendingError):
                await other.start()
            assert other_client.connect_calls == 0
            assert await manager.get_agent(config.agent_id) is owner
            release.set()
            await manager.reload_agent(config.agent_id)
    finally:
        release.set()
        await asyncio.gather(reloading, return_exceptions=True)
        await owner.close()
        await other.close()
        await manager.shutdown()


@pytest.mark.parametrize("retry_operation", ["reload", "start"])
@pytest.mark.parametrize("cancel_disconnect", [False, True])
async def test_reload_recovers_same_client_after_late_disconnect_failure(
    monkeypatch: pytest.MonkeyPatch,
    retry_operation: str,
    cancel_disconnect: bool,
) -> None:
    monkeypatch.setattr("mimic42.core.agent_runtime.STOP_STEP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr("mimic42.core.agent_runtime.TELEGRAM_TEARDOWN_WAIT_SECONDS", 0.01)
    disconnecting = asyncio.Event()
    release = asyncio.Event()
    failed = asyncio.Event()
    config = make_config()
    clients: list[FakeTelegramClient] = []

    class Client(FakeTelegramClient):
        async def connect(self) -> None:
            assert not any(client.connected for client in clients if client is not self)
            await super().connect()

        async def disconnect(self) -> None:
            self.disconnect_calls += 1
            if self is clients[0] and self.disconnect_calls == 1:
                disconnecting.set()
                await release.wait()
                failed.set()
                if cancel_disconnect:
                    raise asyncio.CancelledError()
                raise RuntimeError("late disconnect failed")
            self.connected = False

    def factory(saved: AgentRuntimeConfig) -> MimicAgentRuntime:
        client = Client()
        clients.append(client)
        return MimicAgentRuntime(
            config=saved, telegram_client=client, langchain_agent=FakeLangChainAgent()
        )

    manager = AgentManager(runtime_factory=factory, config_loader=lambda agent_id: config)
    owner = await manager.create_agent(config, start=True)
    reloading = asyncio.create_task(manager.reload_agent(config.agent_id))
    try:
        async with asyncio.timeout(5):
            await disconnecting.wait()
            with pytest.raises(TelegramTeardownPendingError):
                await reloading
            assert await manager.get_agent(config.agent_id) is not owner
            assert len(clients) == 2
            assert clients[0].connected
            assert clients[1].connect_calls == 0
            with pytest.raises(TelegramTeardownPendingError):
                await manager.reload_agent(config.agent_id)
            assert len(clients) == 2
            release.set()
            await failed.wait()
            with pytest.raises(TelegramTeardownPendingError):
                await (await manager.get_agent(config.agent_id)).start()
            assert clients[0].disconnect_calls == 1
            assert clients[0].connected
            assert clients[1].connect_calls == 0
            await getattr(manager, f"{retry_operation}_agent")(config.agent_id)
            if retry_operation == "reload":
                await manager.start_agent(config.agent_id)
            assert clients[0].disconnect_calls == 2
            assert not clients[0].connected
            assert (await manager.get_agent(config.agent_id)).state is AgentRuntimeState.RUNNING
            assert sum(client.connect_calls for client in clients[1:]) == 1
            await manager.start_agent(config.agent_id)
            assert sum(client.connect_calls for client in clients[1:]) == 1
    finally:
        release.set()
        await asyncio.gather(reloading, return_exceptions=True)
        await owner.close()
        await manager.shutdown()


@pytest.mark.parametrize("cancel_disconnect", [False, True])
async def test_unsuccessful_disconnect_blocks_connect_until_same_owner_retries(
    cancel_disconnect: bool,
) -> None:
    class Client(FakeTelegramClient):
        async def disconnect(self) -> None:
            self.disconnect_calls += 1
            if self.disconnect_calls == 1:
                if cancel_disconnect:
                    raise asyncio.CancelledError()
                raise RuntimeError("disconnect failed")
            self.connected = False

    config = make_config()
    client = Client()
    owner = MimicAgentRuntime(
        config=config, telegram_client=client, langchain_agent=FakeLangChainAgent()
    )
    other_client = FakeTelegramClient()
    other = MimicAgentRuntime(
        config=config, telegram_client=other_client, langchain_agent=FakeLangChainAgent()
    )
    await owner.start()
    try:
        with pytest.raises(asyncio.CancelledError if cancel_disconnect else RuntimeError):
            await owner.close()
        with pytest.raises(TelegramTeardownPendingError):
            await other.start()
        assert other_client.connect_calls == 0
        assert client.connected
        await owner.close()
        assert client.disconnect_calls == 2
        assert not client.connected
        await other.start()
        assert other_client.connect_calls == 1
    finally:
        await owner.close()
        await other.close()


@pytest.mark.parametrize("operation", ["stop", "remove", "shutdown"])
async def test_pending_previous_teardown_keeps_manager_cleanup_bounded(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    monkeypatch.setattr("mimic42.core.agent_runtime.STOP_STEP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr("mimic42.core.agent_runtime.TELEGRAM_TEARDOWN_WAIT_SECONDS", 0.01)
    release = asyncio.Event()
    config = make_config()

    class Client(FakeTelegramClient):
        async def disconnect(self) -> None:
            await release.wait()
            await super().disconnect()

    client = Client()
    clients: list[FakeTelegramClient] = [client]

    def factory(saved: AgentRuntimeConfig) -> MimicAgentRuntime:
        current = clients.pop() if clients else FakeTelegramClient()
        return MimicAgentRuntime(
            config=saved, telegram_client=current, langchain_agent=FakeLangChainAgent()
        )

    manager = AgentManager(runtime_factory=factory, config_loader=lambda agent_id: config)
    owner = await manager.create_agent(config, start=True)
    try:
        with pytest.raises(TelegramTeardownPendingError):
            await manager.reload_agent(config.agent_id)
        monkeypatch.setattr("mimic42.core.agent_runtime.TELEGRAM_TEARDOWN_WAIT_SECONDS", 30)
        async with asyncio.timeout(1):
            if operation == "shutdown":
                await manager.shutdown()
            else:
                await getattr(manager, f"{operation}_agent")(config.agent_id)
        assert client.connected
    finally:
        release.set()
        await owner.close()
        await manager.shutdown()


@pytest.mark.parametrize("pause_at", ["connect", "started_event"])
async def test_cancelled_start_cleans_partially_connected_client(pause_at: str) -> None:
    paused = asyncio.Event()
    release = asyncio.Event()

    class Client(FakeTelegramClient):
        async def connect(self) -> None:
            await super().connect()
            if pause_at == "connect":
                paused.set()
                await release.wait()

    class Runtime(MimicAgentRuntime):
        async def _record_event(self, **kwargs: Any) -> None:
            if pause_at == "started_event" and kwargs.get("event_type") == "agent.started":
                paused.set()
                await release.wait()

    client = Client()
    runtime = Runtime(
        config=make_config(), telegram_client=client, langchain_agent=FakeLangChainAgent()
    )
    starting = asyncio.create_task(runtime.start())
    try:
        async with asyncio.timeout(5):
            await paused.wait()
            assert client.connected
            starting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await starting
        assert not client.connected
        assert client.disconnect_calls == 1
        assert runtime.state is AgentRuntimeState.STOPPED
    finally:
        release.set()
        starting.cancel()
        await asyncio.gather(starting, return_exceptions=True)
        await runtime.close()


@pytest.mark.parametrize("operation", ["stop", "reload", "remove"])
async def test_trigger_does_not_restart_runtime_changed_after_manager_admission(
    operation: str,
) -> None:
    admitted = asyncio.Event()
    release = asyncio.Event()
    config = make_config()
    clients: list[FakeTelegramClient] = []

    class Runtime(MimicAgentRuntime):
        async def _trigger_running_message(
            self, trigger: AgentTrigger, *, timer: Any = None
        ) -> AgentTriggerResult:
            admitted.set()
            await release.wait()
            return await super()._trigger_running_message(trigger, timer=timer)

    def factory(saved: AgentRuntimeConfig) -> MimicAgentRuntime:
        client = FakeTelegramClient()
        clients.append(client)
        return Runtime(config=saved, telegram_client=client, langchain_agent=FakeLangChainAgent())

    manager = AgentManager(runtime_factory=factory, config_loader=lambda agent_id: config)
    owner = await manager.create_agent(config)
    triggering = asyncio.create_task(
        manager.trigger_message(config.agent_id, AgentTrigger(peer="chat", text="hello"))
    )
    try:
        async with asyncio.timeout(5):
            await admitted.wait()
            assert clients[0].connect_calls == 1
            await getattr(manager, f"{operation}_agent")(config.agent_id)
            release.set()
            with pytest.raises(AgentLifecycleChangedError):
                await triggering
        assert clients[0].connect_calls == 1
        assert not clients[0].connected
        assert owner.state is AgentRuntimeState.STOPPED
    finally:
        release.set()
        await asyncio.gather(triggering, return_exceptions=True)
        await manager.shutdown()


async def test_stop_does_not_wait_for_a_direct_turn_and_close_settles_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mimic42.core.agent_runtime.CLOSE_GRACE_SECONDS", 0.01)
    entered = asyncio.Event()
    release = asyncio.Event()
    config = make_config()
    model = FakeLangChainAgent()
    client = FakeTelegramClient()

    class Runtime(MimicAgentRuntime):
        async def _take_turn(self, trigger: AgentTrigger) -> AgentTriggerResult:
            entered.set()
            await release.wait()
            return AgentTriggerResult(
                agent_id=self.config.agent_id,
                peer=trigger.peer,
                input_text=trigger.text,
                response_text="done",
            )

    manager = AgentManager(
        runtime_factory=lambda saved: Runtime(
            config=saved, telegram_client=client, langchain_agent=model
        )
    )
    owner = await manager.create_agent(config)
    triggering = asyncio.create_task(
        manager.trigger_message(config.agent_id, AgentTrigger(peer="chat", text="hello"))
    )
    try:
        async with asyncio.timeout(5):
            await entered.wait()
            await manager.stop_agent(config.agent_id)
            assert not triggering.done()
            assert not model.closed
            await manager.remove_agent(config.agent_id)
        assert triggering.cancelled()
        assert model.closed
        with pytest.raises(AgentLifecycleChangedError):
            await owner.start()
        with pytest.raises(AgentLifecycleChangedError):
            await owner.trigger_message(AgentTrigger(peer="chat", text="stale"))
        with pytest.raises(AgentLifecycleChangedError):
            async with owner.leased_telegram_client():
                pytest.fail("retired runtime leased its client")
        assert client.connect_calls == 1
    finally:
        release.set()
        await asyncio.gather(triggering, return_exceptions=True)
        await manager.shutdown()


async def test_cancelled_removal_keeps_cleanup_and_duplicate_removal_waits() -> None:
    disconnecting = asyncio.Event()
    release = asyncio.Event()
    requested = asyncio.Event()
    config = make_config()

    class Client(FakeTelegramClient):
        async def disconnect(self) -> None:
            disconnecting.set()
            await release.wait()
            await super().disconnect()

    client = Client()
    manager = AgentManager(
        runtime_factory=lambda saved: MimicAgentRuntime(
            config=saved, telegram_client=client, langchain_agent=FakeLangChainAgent()
        ),
        config_loader=lambda agent_id: config,
    )
    await manager.create_agent(config, start=True)
    removing = asyncio.create_task(manager.remove_agent(config.agent_id))

    async def remove_again() -> None:
        requested.set()
        await manager.remove_agent(config.agent_id)

    again: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(5):
            await disconnecting.wait()
            removing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await removing
            again = asyncio.create_task(remove_again())
            await requested.wait()
            assert not again.done()
            with pytest.raises(AgentNotFoundError):
                await manager.get_agent(config.agent_id)
            with pytest.raises(AgentNotFoundError):
                await manager.create_agent(config, start=True)
            with pytest.raises(AgentNotFoundError):
                await manager.create_saved_agent(config.agent_id, owner_id=config.owner_id)
            release.set()
            await again
        assert not client.connected
        assert client.disconnect_calls == 1
        assert await manager.list_agents() == []
    finally:
        release.set()
        await asyncio.gather(
            removing, *([again] if again is not None else []), return_exceptions=True
        )
        await manager.shutdown()


@pytest.mark.parametrize("operation", ["reload", "remove"])
async def test_failed_close_retains_owner_for_explicit_retry(operation: str) -> None:
    config = make_config()
    clients: list[FakeTelegramClient] = []

    class Client(FakeTelegramClient):
        async def disconnect(self) -> None:
            self.disconnect_calls += 1
            if self.disconnect_calls == 1:
                raise RuntimeError("disconnect failed")
            self.connected = False

    def factory(saved: AgentRuntimeConfig) -> MimicAgentRuntime:
        client = Client() if not clients else FakeTelegramClient()
        clients.append(client)
        return MimicAgentRuntime(
            config=saved, telegram_client=client, langchain_agent=FakeLangChainAgent()
        )

    manager = AgentManager(runtime_factory=factory, config_loader=lambda agent_id: config)
    owner = await manager.create_agent(config, start=True)
    try:
        with pytest.raises(RuntimeError, match="disconnect failed"):
            await getattr(manager, f"{operation}_agent")(config.agent_id)
        assert await manager.get_agent(config.agent_id) is owner
        assert clients[0].connected
        with pytest.raises(AgentLifecycleChangedError):
            await manager.start_agent(config.agent_id)
        assert len(clients) == 1
        await getattr(manager, f"{operation}_agent")(config.agent_id)
        assert not clients[0].connected
        assert clients[0].disconnect_calls == 2
    finally:
        await manager.shutdown()


@pytest.mark.parametrize(
    ("operation", "failure_at"),
    [
        ("reload", "model_close"),
        ("reload", "config_load"),
        ("reload", "config_missing"),
        ("remove", "model_close"),
        ("stop", "disconnect"),
        ("rebind", "disconnect"),
    ],
)
async def test_lifecycle_failure_persists_observed_stopped_state_and_retry(
    operation: str,
    failure_at: str,
) -> None:
    config = make_config()
    updates = [AgentRuntimeState.RUNNING]
    clients: list[FakeTelegramClient] = []
    failed = False
    applied: list[bool] = []

    class Client(FakeTelegramClient):
        async def disconnect(self) -> None:
            nonlocal failed
            if failure_at == "disconnect" and not failed:
                failed = True
                raise RuntimeError("disconnect failed")
            await super().disconnect()

    class Model(FakeLangChainAgent):
        async def aclose(self) -> None:
            nonlocal failed
            if failure_at == "model_close" and not failed:
                failed = True
                raise RuntimeError("model close failed")
            await super().aclose()

    def load_config(agent_id: object) -> AgentRuntimeConfig:
        nonlocal failed
        if failure_at in {"config_load", "config_missing"} and not failed:
            failed = True
            if failure_at == "config_missing":
                raise KeyError(agent_id)
            raise RuntimeError("config load failed")
        return config

    def factory(saved: AgentRuntimeConfig) -> MimicAgentRuntime:
        client = Client()
        clients.append(client)
        return MimicAgentRuntime(config=saved, telegram_client=client, langchain_agent=Model())

    manager = AgentManager(
        runtime_factory=factory,
        config_loader=load_config,
        status_sink=lambda agent_id, state: updates.append(state),
    )
    owner = await manager.create_agent(config, start=True)

    async def apply() -> None:
        applied.append(True)

    async def invoke() -> None:
        if operation == "rebind":
            await manager.confirm_telegram_rebind(config.agent_id, apply)
        else:
            await getattr(manager, f"{operation}_agent")(config.agent_id)

    try:
        with pytest.raises(
            AgentNotFoundError if failure_at == "config_missing" else RuntimeError
        ) as caught:
            await invoke()
        if operation == "rebind":
            assert isinstance(caught.value, TelegramRebindSequenceError)
            assert isinstance(caught.value.__cause__, RuntimeError)
            assert applied == []
        assert owner.state is AgentRuntimeState.STOPPED
        assert clients[0].connected is (failure_at == "disconnect")
        assert updates[-1] is AgentRuntimeState.STOPPED
        await invoke()
        assert not clients[0].connected
        if operation == "remove":
            assert await manager.list_agents() == []
            assert updates[-1] is AgentRuntimeState.STOPPED
            return
        if operation == "stop":
            assert await manager.get_agent(config.agent_id) is owner
            assert updates[-1] is owner.state
            return
        if operation == "rebind":
            assert applied == [True]
        replacement = await manager.get_agent(config.agent_id)
        assert replacement is not owner
        assert replacement.state is AgentRuntimeState.STOPPED
        assert updates[-1] is replacement.state
        assert all(client.connect_calls == 0 for client in clients[1:])
    finally:
        await manager.shutdown()


@pytest.mark.parametrize("active", [False, True])
async def test_reload_persists_completed_replacement_state(active: bool) -> None:
    config = make_config()
    updates = [AgentRuntimeState.STOPPED if active else AgentRuntimeState.RUNNING]
    manager = AgentManager(
        runtime_factory=lambda saved: MimicAgentRuntime(
            config=saved,
            telegram_client=FakeTelegramClient(),
            langchain_agent=FakeLangChainAgent(),
        ),
        config_loader=lambda agent_id: config,
        status_sink=lambda agent_id, state: updates.append(state),
    )
    await manager.create_agent(config, start=active)
    try:
        await manager.reload_agent(config.agent_id)
        replacement = await manager.get_agent(config.agent_id)
        assert replacement.state is (
            AgentRuntimeState.RUNNING if active else AgentRuntimeState.STOPPED
        )
        assert updates[-1] is replacement.state
    finally:
        await manager.shutdown()


@pytest.mark.parametrize("operation", ["reload", "remove", "stop"])
async def test_lifecycle_preserves_error_when_status_persistence_fails(
    operation: str,
) -> None:
    config = make_config()
    failure = ValueError("model close failed")

    class Client(FakeTelegramClient):
        async def disconnect(self) -> None:
            if operation == "stop":
                raise failure
            await super().disconnect()

    class Model(FakeLangChainAgent):
        async def aclose(self) -> None:
            raise failure

    def save_status(agent_id: object, state: AgentRuntimeState) -> None:
        raise RuntimeError("status persistence failed")

    manager = AgentManager(
        runtime_factory=lambda saved: MimicAgentRuntime(
            config=saved, telegram_client=Client(), langchain_agent=Model()
        ),
        config_loader=lambda agent_id: config,
        status_sink=save_status,
    )
    await manager.create_agent(config, start=True)
    try:
        with pytest.raises(ValueError) as caught:
            await getattr(manager, f"{operation}_agent")(config.agent_id)
        assert caught.value is failure
    finally:
        await manager.shutdown()


async def test_optional_start_during_pending_teardown_stays_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mimic42.core.agent_runtime.STOP_STEP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr("mimic42.core.agent_runtime.TELEGRAM_TEARDOWN_WAIT_SECONDS", 0.01)
    release = asyncio.Event()
    config = make_config()
    updates: list[AgentRuntimeState] = []

    class Client(FakeTelegramClient):
        async def disconnect(self) -> None:
            await release.wait()
            await super().disconnect()

    owner = MimicAgentRuntime(
        config=config, telegram_client=Client(), langchain_agent=FakeLangChainAgent()
    )
    client = FakeTelegramClient()
    manager = AgentManager(
        runtime_factory=lambda saved: MimicAgentRuntime(
            config=saved, telegram_client=client, langchain_agent=FakeLangChainAgent()
        ),
        config_loader=lambda agent_id: config,
        status_sink=lambda agent_id, state: updates.append(state),
    )
    await owner.start()
    await owner.stop()
    try:
        with pytest.raises(TelegramTeardownPendingError):
            await manager.create_saved_agent(config.agent_id, owner_id=config.owner_id, start=True)
        assert (await manager.get_agent(config.agent_id)).state is AgentRuntimeState.STOPPED
        assert updates == []
        assert client.connect_calls == 0
    finally:
        release.set()
        await owner.close()
        await manager.shutdown()


async def test_queued_manual_trigger_is_not_admitted_by_a_later_restart() -> None:
    config = make_config()
    requested = asyncio.Event()
    turns: list[str] = []

    class Runtime(MimicAgentRuntime):
        async def _take_turn(self, trigger: AgentTrigger) -> AgentTriggerResult:
            turns.append(trigger.text)
            return AgentTriggerResult(
                agent_id=self.config.agent_id,
                peer=trigger.peer,
                input_text=trigger.text,
                response_text="done",
            )

    client = FakeTelegramClient()
    manager = AgentManager(
        runtime_factory=lambda saved: Runtime(
            config=saved, telegram_client=client, langchain_agent=FakeLangChainAgent()
        )
    )
    runtime = await manager.create_agent(config, start=True)

    async def trigger() -> AgentTriggerResult:
        requested.set()
        return await manager.trigger_message(config.agent_id, AgentTrigger(peer="chat", text="old"))

    triggering: asyncio.Task[AgentTriggerResult] | None = None
    try:
        async with asyncio.timeout(5):
            async with runtime._trigger_lock:
                triggering = asyncio.create_task(trigger())
                await requested.wait()
                await manager.stop_agent(config.agent_id)
                await manager.start_agent(config.agent_id)
            with pytest.raises(AgentLifecycleChangedError):
                await triggering
        assert turns == []
        result = await manager.trigger_message(
            config.agent_id, AgentTrigger(peer="chat", text="new")
        )
        assert result.response_text == "done"
        assert turns == ["new"]
        assert client.connect_calls == 2
    finally:
        if triggering is not None:
            await asyncio.gather(triggering, return_exceptions=True)
        await manager.shutdown()
