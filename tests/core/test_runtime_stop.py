"""Остановка и закрытие рантайма: работа, пришедшая до stop(), его не переживает."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from mimic42.core import agent_runtime, album_grouper
from mimic42.core.agent_runtime import AgentRuntimeState, AgentTrigger, MimicAgentRuntime
from mimic42.core.send_window import SendWindow
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramClient
from tests.core.test_send_window_runtime import (
    PEER,
    FakeEvent,
    RecordingAgent,
    ScriptedTracker,
    make_config,
)


class GatedAgent(RecordingAgent):
    """Ход висит, пока тест его не отпустит: видно, что приходит во время хода.

    Агент молчит: перед отправкой ответа ход сам ещё раз проверяет окно, а
    тестам важны только проверки от сообщений, пришедших во время хода."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def ainvoke(
        self, input_data: dict[str, object], context: object | None = None
    ) -> dict[str, object]:
        self.entered.set()
        await self.release.wait()
        await super().ainvoke(input_data, context)
        return {
            "messages": [{"role": "assistant", "content": ""}],
            "structured_response": {"text": "", "send_any_message": False, "reply_to": None},
        }


class CountingTracker(ScriptedTracker):
    """Считает проверки окна: у настоящего трекера каждая — запрос в Telegram."""

    def __init__(self, window: SendWindow) -> None:
        super().__init__(window)
        self.checks = 0

    async def check(self, peer: str, chat: object = None) -> SendWindow:
        self.checks += 1
        return self.window


class GatedTracker(ScriptedTracker):
    """Проверка окна висит, пока тест её не отпустит: стоп приходит посреди подготовки хода."""

    def __init__(self) -> None:
        super().__init__(SendWindow())
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def check(self, peer: str, chat: object = None) -> SendWindow:
        self.entered.set()
        await self.release.wait()
        return self.window


class GatedConnectClient(FakeTelegramClient):
    """connect() висит, пока тест не отпустит: рантайм застревает в STARTING."""

    def __init__(self, account: FakeTelegramAccount) -> None:
        super().__init__(account)
        self.connecting = asyncio.Event()
        self.gate = asyncio.Event()
        self.gate.set()

    async def connect(self) -> None:
        self.connecting.set()
        await self.gate.wait()
        await super().connect()


def build(
    agent: RecordingAgent,
    *,
    tracker: ScriptedTracker | None = None,
    client: FakeTelegramClient | None = None,
) -> MimicAgentRuntime:
    if client is None:
        account = FakeTelegramAccount()
        account.authorized = True
        client = FakeTelegramClient(account)
    return MimicAgentRuntime(
        config=make_config(),
        telegram_client=cast(Any, client),
        langchain_agent=cast(Any, agent),
        send_window=tracker or ScriptedTracker(SendWindow()),
    )


async def queued_on(lock: asyncio.Lock) -> None:
    """Дождаться, пока кто-то встанет в очередь на замок.

    Публичного счётчика ожидающих у asyncio.Lock нет, поэтому смотрим в его
    очередь напрямую: без этого задача могла бы дойти до замка уже после stop()."""
    for _ in range(100):
        if getattr(lock, "_waiters", None):
            return
        await asyncio.sleep(0)
    raise AssertionError("никто не встал в очередь на замок")


def dispatch(runtime: MimicAgentRuntime, event: FakeEvent) -> asyncio.Task[None]:
    return asyncio.create_task(runtime._dispatch_incoming(cast(Any, [event])))


async def test_message_queued_behind_a_turn_does_not_restart_a_stopped_runtime() -> None:
    """Второе сообщение ждёт, пока идёт ход по первому, и тут агента останавливают.
    Очередь не должна поднять его обратно: он продолжил бы отвечать, а в базе
    остался бы статус «остановлен». И в Telegram с отключённым клиентом оно не ходит."""
    agent = GatedAgent()
    tracker = CountingTracker(SendWindow())
    runtime = build(agent, tracker=tracker)
    await runtime.start()
    first = dispatch(runtime, FakeEvent(1, "первое"))
    await agent.entered.wait()
    queued = dispatch(runtime, FakeEvent(2, "второе"))
    await queued_on(runtime._dispatch_lock)

    await runtime.stop()
    checks_before_stop = tracker.checks
    agent.release.set()
    await asyncio.gather(first, queued)

    assert runtime._state is AgentRuntimeState.STOPPED
    assert not [text for text in agent.texts if "второе" in text]
    assert tracker.checks == checks_before_stop


async def test_stop_while_a_turn_is_prepared_does_not_restart_the_runtime() -> None:
    """Стоп пришёл, когда очередь уже пройдена и ход собирается: запускать агента
    заново ради этого хода нельзя."""
    agent = RecordingAgent()
    tracker = GatedTracker()
    runtime = build(agent, tracker=tracker)
    await runtime.start()
    post = dispatch(runtime, FakeEvent(1, "пост канала", is_group=False))
    await tracker.entered.wait()

    await runtime.stop()
    tracker.release.set()
    await post

    assert runtime._state is AgentRuntimeState.STOPPED
    assert agent.texts == []


async def test_turn_waiting_behind_a_dashboard_turn_is_dropped_after_stop() -> None:
    """Ход по сообщению ждал, пока закончится ход из дашборда, и тут агента
    остановили. Проснувшись, он не должен звать модель и инструменты: иначе
    остановленный агент ещё успел бы, например, завести себе таймер."""
    agent = GatedAgent()
    runtime = build(agent)
    await runtime.start()
    dashboard = asyncio.create_task(
        runtime.trigger_message(AgentTrigger(peer=PEER, text="из дашборда"))
    )
    await agent.entered.wait()
    waiting = asyncio.create_task(
        runtime._trigger_while_running(AgentTrigger(peer=PEER, text="из очереди"))
    )
    await queued_on(runtime._trigger_lock)

    await runtime.stop()
    agent.release.set()
    await asyncio.gather(dashboard, waiting)

    assert not [text for text in agent.texts if "из очереди" in text]


async def test_message_arriving_while_the_agent_restarts_is_processed() -> None:
    """Telethon доставляет апдейты ещё внутри connect(), пока start() не закончен.
    После Стоп → Старт такое сообщение ждёт конца запуска, а не теряется."""
    account = FakeTelegramAccount()
    account.authorized = True
    client = GatedConnectClient(account)
    agent = RecordingAgent()
    runtime = build(agent, client=client)
    await runtime.start()
    await runtime.stop()

    client.connecting.clear()
    client.gate.clear()
    restart = asyncio.create_task(runtime.start())
    await client.connecting.wait()
    message = dispatch(runtime, FakeEvent(1, "привет"))
    await queued_on(runtime._lifecycle_lock)

    client.gate.set()
    await asyncio.gather(restart, message)

    assert [text for text in agent.texts if "привет" in text]
    await runtime.stop()


async def album_turn_in_flight(
    monkeypatch: pytest.MonkeyPatch, agent: GatedAgent
) -> MimicAgentRuntime:
    """Запущенный рантайм, у которого ход по альбому висит в модели."""
    monkeypatch.setattr(album_grouper, "QUIET_WINDOW", 0.01)
    monkeypatch.setattr(album_grouper, "MAX_WINDOW", 0.02)
    runtime = build(agent)
    await runtime.start()
    event = FakeEvent(1, "фото с подписью", is_group=False)
    event.grouped_id = 42
    await runtime._handle_incoming_message(cast(Any, event))
    await agent.entered.wait()
    return runtime


async def test_close_cancels_an_album_turn_that_outlives_the_grace_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """После close() закрываются клиент модели и пул базы: ход, оставшийся в
    полёте, открыл бы соединение, которое уже никто не закроет."""
    monkeypatch.setattr(agent_runtime, "CLOSE_GRACE_SECONDS", 0.05)
    runtime = await album_turn_in_flight(monkeypatch, GatedAgent())
    (flush,) = runtime._album_grouper.in_flight

    await asyncio.wait_for(runtime.close(), timeout=2)

    assert flush.cancelled()
    assert runtime._album_grouper.in_flight == frozenset()


async def test_close_lets_an_album_turn_finish_within_the_grace_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Успевший за отведённое время ход доводится до конца: его запись не теряется."""
    monkeypatch.setattr(agent_runtime, "CLOSE_GRACE_SECONDS", 2.0)
    agent = GatedAgent()
    runtime = await album_turn_in_flight(monkeypatch, agent)
    (flush,) = runtime._album_grouper.in_flight

    closing = asyncio.create_task(runtime.close())
    await asyncio.sleep(0.01)
    agent.release.set()
    await asyncio.wait_for(closing, timeout=2)

    assert not flush.cancelled()
    assert [text for text in agent.texts if "фото с подписью" in text]
