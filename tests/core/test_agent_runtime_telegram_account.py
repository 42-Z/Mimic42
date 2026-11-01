from __future__ import annotations

import asyncio
from typing import cast

import pytest

from mimic42.core.agent_runtime import (
    AgentRuntimeState,
    MimicAgentRuntime,
    TelegramEventLike,
    TelegramTeardownPendingError,
)
from mimic42.core.first_comment import FirstCommentSettings, FirstCommentVariant
from mimic42.testing.telegram import (
    FakeIncomingEvent,
    FakeTelegramClient,
    IncomingMessage,
)
from tests.core.test_agent_runtime import FakeLangChainAgent, make_config

CHANNEL = -1001111111111


def _runtime(
    *, response: str = ""
) -> tuple[MimicAgentRuntime, FakeTelegramClient, FakeLangChainAgent]:
    telegram = FakeTelegramClient()
    agent = FakeLangChainAgent(response=response)
    runtime = MimicAgentRuntime(
        config=make_config(), telegram_client=telegram, langchain_agent=agent
    )
    return runtime, telegram, agent


@pytest.mark.asyncio
async def test_a_running_client_is_leased_without_disconnecting_it() -> None:
    runtime, telegram, _ = _runtime()
    await runtime.start()

    async with runtime.leased_telegram_client() as client:
        assert client is telegram
        assert telegram.connected is True

    assert telegram.disconnect_calls == 0
    assert runtime.state is AgentRuntimeState.RUNNING
    await runtime.stop()


@pytest.mark.asyncio
async def test_a_stopped_client_is_connected_only_for_the_lease() -> None:
    runtime, telegram, agent = _runtime()

    async with runtime.leased_telegram_client() as client:
        assert client is telegram
        assert telegram.connected is True
        assert runtime.state is AgentRuntimeState.STOPPED

    assert telegram.connect_calls == 1
    assert telegram.disconnect_calls == 1
    assert telegram.connected is False
    assert telegram.handlers == []
    assert runtime._scheduler_task is None
    assert agent.inputs == []


class _StuckDisconnectClient(FakeTelegramClient):
    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        await self.release.wait()
        self.connected = False


@pytest.mark.asyncio
async def test_a_pending_teardown_blocks_a_new_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mimic42.core.agent_runtime.STOP_STEP_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr("mimic42.core.agent_runtime.TELEGRAM_TEARDOWN_WAIT_SECONDS", 0.05)
    telegram = _StuckDisconnectClient()
    runtime = MimicAgentRuntime(
        config=make_config(), telegram_client=telegram, langchain_agent=FakeLangChainAgent()
    )
    await runtime.start()
    await runtime.stop()

    try:
        with pytest.raises(TelegramTeardownPendingError):
            async with runtime.leased_telegram_client():
                pytest.fail("аренда не должна была начаться")
    finally:
        telegram.release.set()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_a_cancelled_lease_disconnects_the_temporary_client() -> None:
    runtime, telegram, _ = _runtime()
    entered = asyncio.Event()
    hold = asyncio.Event()

    async def use_lease() -> None:
        async with runtime.leased_telegram_client():
            entered.set()
            await hold.wait()

    task = asyncio.create_task(use_lease())
    await entered.wait()
    assert telegram.connected is True

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert telegram.connected is False
    assert telegram.disconnect_calls == 1


@pytest.mark.asyncio
async def test_a_stopped_agent_posts_no_first_comment_during_a_short_lease() -> None:
    runtime, telegram, _ = _runtime()
    runtime.config.first_comment = FirstCommentSettings(
        enabled=True, variants=[FirstCommentVariant(text="Первый!")]
    )
    await runtime.start()
    await runtime.stop()

    async with runtime.leased_telegram_client():
        await telegram.account.deliver_post(chat_id=CHANNEL, text="Новый пост")

    assert [message for message in telegram.account.sent if "comment_to" in message.kwargs] == []


@pytest.mark.asyncio
async def test_an_incoming_message_while_starting_is_still_accepted() -> None:
    class GatedConnectClient(FakeTelegramClient):
        def __init__(self) -> None:
            super().__init__()
            self.gate = asyncio.Event()

        async def connect(self) -> None:
            await self.gate.wait()
            await super().connect()

    telegram = GatedConnectClient()
    agent = FakeLangChainAgent(response="")
    runtime = MimicAgentRuntime(
        config=make_config(), telegram_client=telegram, langchain_agent=agent
    )
    starting = asyncio.create_task(runtime.start())
    for _ in range(1000):
        if runtime.state is AgentRuntimeState.STARTING:
            break
        await asyncio.sleep(0)
    else:
        starting.cancel()
        pytest.fail("рантайм не дошёл до STARTING")

    event = cast(
        TelegramEventLike,
        FakeIncomingEvent(
            IncomingMessage(chat_id=99, message_id=1, text="привет", sender_id=99),
            client=telegram.account,
        ),
    )
    incoming = asyncio.create_task(runtime._handle_incoming_message(event))
    await asyncio.sleep(0)
    assert not incoming.done()

    telegram.gate.set()
    await starting
    await incoming

    assert len(agent.inputs) == 1
    await runtime.stop()
