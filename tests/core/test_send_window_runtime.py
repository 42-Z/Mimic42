from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from mimic42.core.agent_runtime import AgentRuntimeConfig, AgentRuntimeState, MimicAgentRuntime
from mimic42.core.send_window import SendWindow, SendWindowTracker
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramClient

PEER = "-100777"


def make_config() -> AgentRuntimeConfig:
    """Тот же набор обязательных полей, что и в tests/core/test_agent_runtime.py."""
    return AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_session_string="sessions/test-agent",
        telegram_api_id=12345,
        telegram_api_hash="hash",
        llm_model="openrouter/free",
        system_prompt="Base system prompt",
    )


class ScriptedTracker(SendWindowTracker):
    """Настоящий трекер (announce, note_*), но состояние окна задано тестом."""

    def __init__(self, window: SendWindow) -> None:
        super().__init__(client=None)
        self.window = window

    async def check(self, peer: str, chat: object = None) -> SendWindow:
        return self.window


class RecordingAgent:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def ainvoke(
        self, input_data: dict[str, object], context: object | None = None
    ) -> dict[str, object]:
        messages = cast(list[Any], input_data["messages"])
        self.texts.append(str(messages[-1]["content"]))
        return {
            "messages": [{"role": "assistant", "content": "ответ"}],
            "structured_response": {"text": "ответ", "send_any_message": True, "reply_to": None},
        }


class FakeEvent:
    def __init__(
        self, message_id: int, text: str, *, is_group: bool = True, is_private: bool = False
    ) -> None:
        self.chat_id = int(PEER)
        self.sender_id = 999
        self.id = message_id
        self.text = text
        self.raw_text = text
        self.is_private = is_private
        self.is_group = is_group
        self.grouped_id = None
        self.message = type("M", (), {"reply_to": None, "post_author": None, "date": None})()

    async def get_chat(self) -> object:
        return type("Chat", (), {"id": int(PEER), "title": "Группа", "username": None})()

    async def get_reply_message(self) -> object | None:
        return None

    async def get_input_chat(self) -> object:
        return await self.get_chat()

    async def get_sender(self) -> object:
        return type(
            "U", (), {"first_name": "Гость", "last_name": "", "username": None, "id": 999}
        )()


def slowmode_closed(seconds_left: float) -> SendWindow:
    return SendWindow(
        reason="slowmode",
        open_at=datetime.now(UTC) + timedelta(seconds=seconds_left),
        slowmode_seconds=30,
    )


def build(window: SendWindow) -> tuple[MimicAgentRuntime, RecordingAgent, ScriptedTracker]:
    account = FakeTelegramAccount()
    account.authorized = True
    agent = RecordingAgent()
    tracker = ScriptedTracker(window)
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=cast(Any, FakeTelegramClient(account)),
        langchain_agent=cast(Any, agent),
        send_window=tracker,
    )
    return runtime, agent, tracker


async def dispatch(runtime: MimicAgentRuntime, *events: FakeEvent) -> None:
    """FakeEvent повторяет форму события Telethon, но не объявляет протокол целиком."""
    if runtime._state is AgentRuntimeState.STOPPED:
        # Настоящие события приходят только у запущенного рантайма.
        await runtime.start()
    await runtime._dispatch_incoming(cast(Any, list(events)))


async def finish(runtime: MimicAgentRuntime) -> None:
    await runtime._deferred_inbox.close()
    await runtime.stop()


async def test_flush_in_flight_after_stop_does_not_restart_the_runtime() -> None:
    runtime, agent, _ = build(SendWindow())
    await dispatch(runtime, FakeEvent(1, "привет"))
    await finish(runtime)
    agent.texts.clear()

    await runtime._flush_deferred(PEER, [[FakeEvent(2, "запоздало")]], [0.0])

    assert agent.texts == []
    assert runtime._state is AgentRuntimeState.STOPPED


class GatedAgent(RecordingAgent):
    """Ход висит, пока тест его не отпустит: видно, что приходит во время хода.

    Агент молчит: перед отправкой ответа ход сам ещё раз проверяет окно, а
    тесту важны только проверки от сообщений, пришедших во время хода."""

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


async def test_message_queued_behind_a_turn_does_not_restart_a_stopped_runtime() -> None:
    """Второе сообщение ждёт, пока идёт ход по первому, и тут агента останавливают.
    Очередь не должна поднять его обратно: он продолжил бы отвечать, а в базе
    остался бы статус «остановлен». И в Telegram с отключённым клиентом оно не ходит."""
    account = FakeTelegramAccount()
    account.authorized = True
    agent = GatedAgent()
    tracker = CountingTracker(SendWindow())
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=cast(Any, FakeTelegramClient(account)),
        langchain_agent=cast(Any, agent),
        send_window=tracker,
    )
    await runtime.start()
    first = asyncio.create_task(runtime._dispatch_incoming(cast(Any, [FakeEvent(1, "первое")])))
    await agent.entered.wait()
    queued = asyncio.create_task(runtime._dispatch_incoming(cast(Any, [FakeEvent(2, "второе")])))

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
    account = FakeTelegramAccount()
    account.authorized = True
    agent = RecordingAgent()
    tracker = GatedTracker()
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=cast(Any, FakeTelegramClient(account)),
        langchain_agent=cast(Any, agent),
        send_window=tracker,
    )
    await runtime.start()
    post = asyncio.create_task(
        runtime._dispatch_incoming(cast(Any, [FakeEvent(1, "пост канала", is_group=False)]))
    )
    await tracker.entered.wait()

    await runtime.stop()
    tracker.release.set()
    await post

    assert runtime._state is AgentRuntimeState.STOPPED
    assert agent.texts == []


async def test_open_window_runs_the_turn_immediately() -> None:
    runtime, agent, _ = build(SendWindow())
    await dispatch(runtime, FakeEvent(1, "привет"))
    assert len(agent.texts) == 1
    await finish(runtime)


async def test_slowmode_header_is_shown_even_for_a_single_message() -> None:
    runtime, agent, _ = build(SendWindow(slowmode_seconds=30))
    await dispatch(runtime, FakeEvent(1, "привет"))
    assert "медленный режим" in agent.texts[0].lower()
    assert "30" in agent.texts[0]
    await finish(runtime)


async def test_closed_window_buffers_instead_of_running_a_turn() -> None:
    runtime, agent, _ = build(slowmode_closed(30))
    await dispatch(runtime, FakeEvent(1, "первое"))
    await dispatch(runtime, FakeEvent(2, "второе"))
    assert agent.texts == []
    await finish(runtime)


async def test_buffered_messages_collapse_into_one_turn() -> None:
    runtime, agent, tracker = build(slowmode_closed(0.2))
    await dispatch(runtime, FakeEvent(1, "первое"))
    await dispatch(runtime, FakeEvent(2, "второе"))
    tracker.window = SendWindow(slowmode_seconds=30)
    await asyncio.sleep(1.2)

    assert len(agent.texts) == 1
    assert "первое" in agent.texts[0]
    assert "второе" in agent.texts[0]
    assert "reply_to" in agent.texts[0]
    await finish(runtime)


async def test_flush_rechecks_the_window_and_defers_again() -> None:
    """Слот мог снова закрыться, пока копилось: ход на закрытом окне — пустая трата."""
    runtime, agent, tracker = build(slowmode_closed(0.2))
    await dispatch(runtime, FakeEvent(1, "первое"))
    tracker.window = slowmode_closed(30)
    await asyncio.sleep(1.2)
    assert agent.texts == []
    await finish(runtime)


async def test_forbidden_chat_notifies_once_and_then_stays_silent() -> None:
    runtime, agent, _ = build(SendWindow(reason="restricted", forever=True))
    await dispatch(runtime, FakeEvent(1, "первое"))
    await dispatch(runtime, FakeEvent(2, "второе"))

    assert len(agent.texts) == 1
    assert "право писать" in agent.texts[0]
    assert "первое" not in agent.texts[0]
    # RecordingAgent на уведомление отвечает текстом (слабая модель делает так всегда):
    # предохранитель обязан не выпустить этот ответ в чат, где писать нельзя.
    assert cast(Any, runtime._telegram_client).account.sent == []
    await finish(runtime)


async def test_a_second_closure_is_announced_again_after_reopening() -> None:
    runtime, agent, tracker = build(SendWindow(reason="restricted", forever=True))
    await dispatch(runtime, FakeEvent(1, "закрыто"))
    tracker.window = SendWindow()
    await dispatch(runtime, FakeEvent(2, "открыто"))
    tracker.window = SendWindow(reason="restricted", forever=True)
    await dispatch(runtime, FakeEvent(3, "снова закрыто"))

    notices = [text for text in agent.texts if "право писать" in text]
    assert len(notices) == 2
    await finish(runtime)


async def test_channel_posts_bypass_the_gate() -> None:
    """Пост канала — не группа: агент не админ, но комментировать под ним может."""
    runtime, agent, _ = build(SendWindow(reason="restricted", forever=True))
    await dispatch(runtime, FakeEvent(1, "пост канала", is_group=False))
    assert len(agent.texts) == 1
    assert "право писать" not in agent.texts[0]
    await finish(runtime)


async def test_private_chats_bypass_the_gate() -> None:
    runtime, agent, _ = build(slowmode_closed(30))
    await dispatch(runtime, FakeEvent(1, "привет", is_group=False, is_private=True))
    assert len(agent.texts) == 1
    await finish(runtime)


async def test_notification_mute_still_wins() -> None:
    runtime, agent, _ = build(SendWindow())
    runtime._chat_mute_cache[PEER] = (True, time.time() + 100)
    await dispatch(runtime, FakeEvent(1, "привет"))
    assert agent.texts == []
    await finish(runtime)


async def test_runtime_without_a_window_behaves_as_before() -> None:
    account = FakeTelegramAccount()
    account.authorized = True
    agent = RecordingAgent()
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=cast(Any, FakeTelegramClient(account)),
        langchain_agent=cast(Any, agent),
    )
    await dispatch(runtime, FakeEvent(1, "привет"))
    assert len(agent.texts) == 1
    await finish(runtime)


def _capture_events(runtime: MimicAgentRuntime) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []

    async def record(*, event_type: str, status: str, **_: Any) -> None:
        events.append((event_type, status))

    runtime._record_event = record  # ty: ignore[invalid-assignment]
    return events


async def test_window_events_do_not_count_as_errors() -> None:
    """Дашборд считает ошибкой всякое failed: кд и запрет писать — не поломка агента."""
    runtime, _, _ = build(SendWindow(reason="restricted", forever=True))
    events = _capture_events(runtime)
    await dispatch(runtime, FakeEvent(1, "первое"))
    assert ("message.write_forbidden", "cancelled") in events
    assert all(status != "failed" for _, status in events)
    await finish(runtime)


async def test_deferral_is_recorded_once_per_closure() -> None:
    runtime, _, _ = build(slowmode_closed(30))
    events = _capture_events(runtime)
    await dispatch(runtime, FakeEvent(1, "первое"))
    await dispatch(runtime, FakeEvent(2, "второе"))
    assert [event for event in events if event[0] != "agent.started"] == [
        ("message.deferred", "succeeded")
    ]
    await finish(runtime)


class SlotConsumingTracker(ScriptedTracker):
    """После успешной отправки закрывает окно на 30 с — как медленный режим."""

    def note_sent(self, peer: str) -> None:
        self.window = slowmode_closed(30)


class SlowAgent(RecordingAgent):
    async def ainvoke(
        self, input_data: dict[str, object], context: object | None = None
    ) -> dict[str, object]:
        await asyncio.sleep(0.1)  # генерация занимает время: именно тут окно и закрывается
        return await super().ainvoke(input_data, context)


async def test_messages_arriving_during_a_turn_are_deferred_not_lost() -> None:
    """Сообщения 2 и 3 пришли, пока шёл ход по первому: окно тогда было открыто, но к
    моменту их хода слот уже потрачен. Без сериализации проверки и хода они прошли бы гейт
    и были отменены предохранителем, а их содержимое потерялось бы вместо отсрочки."""
    account = FakeTelegramAccount()
    account.authorized = True
    agent = SlowAgent()
    tracker = SlotConsumingTracker(SendWindow(slowmode_seconds=30))
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=cast(Any, FakeTelegramClient(account)),
        langchain_agent=cast(Any, agent),
        send_window=tracker,
    )
    events = _capture_events(runtime)

    await asyncio.gather(
        dispatch(runtime, FakeEvent(1, "первое")),
        dispatch(runtime, FakeEvent(2, "второе")),
        dispatch(runtime, FakeEvent(3, "третье")),
    )

    assert len(agent.texts) == 1, "ход на закрытом окне — пустая трата"
    assert "message.blocked" not in [name for name, _ in events]
    assert ("message.deferred", "succeeded") in events
    await finish(runtime)
