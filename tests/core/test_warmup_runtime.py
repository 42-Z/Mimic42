from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from telethon import errors

from mimic42.core.agent_runtime import MimicAgentRuntime, OpenerResult
from mimic42.core.warmup import WarmupSettings, WarmupState
from mimic42.testing.telegram import FakeTelegramClient
from tests.core.test_agent_runtime import FakeLangChainAgent, FakeRuntimeMemoryService, make_config


class StubGate:
    def __init__(self, verdict: bool | None, delay: float = 0.0, confirm: bool = True) -> None:
        self.verdict = verdict
        self.delay = delay
        self.confirm = confirm
        self.calls: list[tuple[UUID, int]] = []
        self.confirms: list[tuple[UUID, int]] = []
        self.floods: list[UUID] = []

    def claim_reply(self, receiver_id: UUID, sender_telegram_id: int) -> bool | None:
        self.calls.append((receiver_id, sender_telegram_id))
        return self.verdict

    def confirm_reply(self, receiver_id: UUID, sender_telegram_id: int) -> bool:
        self.confirms.append((receiver_id, sender_telegram_id))
        return self.confirm

    def reply_delay_seconds(self) -> float:
        return self.delay

    async def report_peer_flood(self, agent_id: UUID) -> None:
        self.floods.append(agent_id)


def make_runtime() -> tuple[MimicAgentRuntime, FakeTelegramClient, FakeLangChainAgent]:
    return make_runtime_with_memory()[:3]


def make_runtime_with_memory() -> tuple[
    MimicAgentRuntime, FakeTelegramClient, FakeLangChainAgent, FakeRuntimeMemoryService
]:
    telegram = FakeTelegramClient()
    telegram.account.username = "mimic_a"
    agent = FakeLangChainAgent(response="ответ")
    memory = FakeRuntimeMemoryService()
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram,
        langchain_agent=agent,
        memory_service=memory,
    )
    return runtime, telegram, agent, memory


@pytest.mark.asyncio
async def test_start_remembers_telegram_identity() -> None:
    runtime, _, _ = make_runtime()
    await runtime.start()
    assert runtime.telegram_user_id == 777
    assert runtime.telegram_username == "mimic_a"


@pytest.mark.asyncio
async def test_opener_goes_to_username_and_lands_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, telegram, _, memory = make_runtime_with_memory()
    await runtime.start()

    async def no_delay(_seconds: float) -> None:
        return None

    monkeypatch.setattr("mimic42.core.agent_runtime.asyncio.sleep", no_delay)

    sent = await runtime.send_warmup_opener(
        username="mimic_b",
        user_id=555,
        partner_agent_id=uuid4(),
        partner_name="Боб",
        text="привет",
        dialog_length=5,
    )

    assert sent is OpenerResult.SENT
    assert telegram.sent_messages == [("@mimic_b", "привет")]
    saved = memory.saved_messages
    assert len(saved) == 1
    assert saved[0][1] == "555"  # история ведётся по id собеседника, как у входящих
    assert saved[0][3][0]["content"] == "привет"


@pytest.mark.asyncio
async def test_opener_is_not_sent_by_stopped_runtime() -> None:
    runtime, telegram, _ = make_runtime()
    sent = await runtime.send_warmup_opener(
        username="mimic_b",
        user_id=555,
        partner_agent_id=uuid4(),
        partner_name="Боб",
        text="привет",
        dialog_length=5,
    )
    assert sent is OpenerResult.FAILED
    assert telegram.sent_messages == []


@pytest.mark.asyncio
async def test_finished_warmup_dialog_leaves_message_unanswered() -> None:
    runtime, telegram, agent = make_runtime()
    gate = StubGate(False)
    runtime.set_warmup_gate(gate)
    await runtime.start()

    await telegram.account.deliver(chat_id=555, text="ну ладно", sender_id=555)

    assert gate.calls == [(runtime.config.agent_id, 555)]
    assert agent.inputs == []
    assert telegram.sent_messages == []


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", [True, None])
async def test_open_dialog_and_ordinary_people_are_answered_normally(
    verdict: bool | None,
) -> None:
    runtime, telegram, agent = make_runtime()
    runtime.set_warmup_gate(StubGate(verdict))
    await runtime.start()

    await telegram.account.deliver(chat_id=555, text="привет", sender_id=555)

    assert len(agent.inputs) == 1


@pytest.mark.asyncio
async def test_reply_to_another_mimic_waits_the_random_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, telegram, agent = make_runtime()
    runtime.set_warmup_gate(StubGate(True, delay=123.0))
    await runtime.start()
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("mimic42.core.agent_runtime.asyncio.sleep", fake_sleep)

    await telegram.account.deliver(chat_id=555, text="привет", sender_id=555)

    assert 123.0 in slept
    assert len(agent.inputs) == 1


@pytest.mark.asyncio
async def test_ordinary_people_are_answered_without_extra_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, telegram, agent = make_runtime()
    runtime.set_warmup_gate(StubGate(None, delay=123.0))
    await runtime.start()
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("mimic42.core.agent_runtime.asyncio.sleep", fake_sleep)

    await telegram.account.deliver(chat_id=555, text="привет", sender_id=555)

    assert 123.0 not in slept
    assert len(agent.inputs) == 1


@pytest.mark.asyncio
async def test_peer_flood_is_reported_as_restriction_not_as_plain_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, telegram, _ = make_runtime()
    await runtime.start()

    async def no_delay(_seconds: float) -> None:
        return None

    async def flooded(*_args: object, **_kwargs: object) -> object:
        raise errors.PeerFloodError(request=None)

    monkeypatch.setattr("mimic42.core.agent_runtime.asyncio.sleep", no_delay)
    monkeypatch.setattr(telegram, "send_message", flooded)

    result = await runtime.send_warmup_opener(
        username="mimic_b",
        user_id=555,
        partner_agent_id=uuid4(),
        partner_name="Боб",
        text="привет",
        dialog_length=5,
    )

    assert result is OpenerResult.RESTRICTED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("Good news, no limits are currently applied to your account.", True),
        ("Your account is limited until 3 Oct 2026.", False),
        ("что-то непонятное", None),
        (None, None),
    ],
)
async def test_check_spambot_reads_the_bots_answer(
    monkeypatch: pytest.MonkeyPatch, reply: str | None, expected: bool | None
) -> None:
    runtime, telegram, _ = make_runtime()
    await runtime.start()

    async def no_delay(_seconds: float) -> None:
        return None

    async def get_messages(entity: object, **_kwargs: object) -> list[object]:
        assert entity == "@SpamBot"
        return [type("Message", (), {"message": reply})()] if reply is not None else []

    monkeypatch.setattr("mimic42.core.agent_runtime.asyncio.sleep", no_delay)
    monkeypatch.setattr(telegram, "get_messages", get_messages, raising=False)

    assert await runtime.check_spambot() is expected
    assert ("@SpamBot", "/start") in telegram.sent_messages


@pytest.mark.asyncio
async def test_runtime_starts_with_the_saved_restriction_state() -> None:
    config = make_config()
    config.warmup = WarmupSettings(enabled=True)
    config.warmup_state = WarmupState(
        restricted_at=datetime(2026, 10, 1, tzinfo=UTC), recovery=True
    )
    runtime = MimicAgentRuntime(
        config=config,
        telegram_client=FakeTelegramClient(),
        langchain_agent=FakeLangChainAgent(),
        memory_service=FakeRuntimeMemoryService(),
    )
    assert runtime.warmup_restricted_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert runtime.warmup_recovery is True


@pytest.mark.asyncio
async def test_spambot_reply_does_not_start_an_agent_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, telegram, agent = make_runtime()
    await runtime.start()
    spambot_id = 178220800

    async def no_delay(_seconds: float) -> None:
        return None

    async def get_input_entity(_peer: object) -> object:
        return type("InputPeerUser", (), {"user_id": spambot_id})()

    async def get_messages(_entity: object, **_kwargs: object) -> list[object]:
        return []

    monkeypatch.setattr("mimic42.core.agent_runtime.asyncio.sleep", no_delay)
    monkeypatch.setattr(telegram, "get_input_entity", get_input_entity, raising=False)
    monkeypatch.setattr(telegram, "get_messages", get_messages, raising=False)

    await runtime.check_spambot()
    await telegram.account.deliver(chat_id=spambot_id, text="Good news", sender_id=spambot_id)
    assert agent.inputs == []

    await telegram.account.deliver(chat_id=555, text="привет", sender_id=555)
    assert len(agent.inputs) == 1


class _Entity:
    """Разрешённый Telethon-ом получатель: InputPeerUser с user_id."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id

    def __str__(self) -> str:
        return f"user:{self.user_id}"


async def _no_delay(_seconds: float) -> None:
    return None


async def _send_opener(runtime: MimicAgentRuntime, *, user_id: int = 555) -> OpenerResult:
    return await runtime.send_warmup_opener(
        username="mimic_b",
        user_id=user_id,
        partner_agent_id=uuid4(),
        partner_name="Боб",
        text="привет",
        dialog_length=5,
    )


@pytest.mark.asyncio
async def test_reply_is_dropped_if_the_dialog_was_cancelled_while_the_agent_was_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, telegram, agent = make_runtime()
    gate = StubGate(True, delay=60.0, confirm=False)
    runtime.set_warmup_gate(gate)
    await runtime.start()
    monkeypatch.setattr("mimic42.core.agent_runtime.asyncio.sleep", _no_delay)

    await telegram.account.deliver(chat_id=555, text="привет", sender_id=555)

    assert gate.confirms == [(runtime.config.agent_id, 555)]
    assert agent.inputs == []
    assert telegram.sent_messages == []


@pytest.mark.asyncio
async def test_opener_goes_only_to_the_account_with_the_expected_telegram_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, telegram, _ = make_runtime()
    await runtime.start()
    monkeypatch.setattr("mimic42.core.agent_runtime.asyncio.sleep", _no_delay)

    async def stranger(_peer: object) -> object:
        return _Entity(999)

    monkeypatch.setattr(telegram, "get_input_entity", stranger, raising=False)
    assert await _send_opener(runtime) is OpenerResult.FAILED
    assert telegram.sent_messages == []

    async def expected(_peer: object) -> object:
        return _Entity(555)

    monkeypatch.setattr(telegram, "get_input_entity", expected, raising=False)
    assert await _send_opener(runtime) is OpenerResult.SENT
    assert telegram.sent_messages == [("user:555", "привет")]


@pytest.mark.asyncio
async def test_delivered_opener_is_recorded_before_and_regardless_of_saving_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, _, memory = make_runtime_with_memory()
    await runtime.start()
    monkeypatch.setattr("mimic42.core.agent_runtime.asyncio.sleep", _no_delay)
    recorded: list[str] = []

    async def record_event(**kwargs: object) -> None:
        recorded.append(str(kwargs["event_type"]))

    async def broken_memory(**_kwargs: object) -> None:
        recorded.append("memory")
        raise RuntimeError("память недоступна")

    monkeypatch.setattr(runtime, "_record_event", record_event)
    monkeypatch.setattr(memory, "save_messages", broken_memory)

    assert await _send_opener(runtime) is OpenerResult.SENT
    assert recorded == ["warmup.opener_sent", "memory"]


@pytest.mark.asyncio
async def test_peer_flood_on_opener_is_recorded_as_a_failed_attempt_with_the_partner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, telegram, _ = make_runtime()
    await runtime.start()
    monkeypatch.setattr("mimic42.core.agent_runtime.asyncio.sleep", _no_delay)
    events: list[dict[str, object]] = []

    async def record_event(**kwargs: object) -> None:
        events.append(dict(kwargs))

    async def flooded(*_args: object, **_kwargs: object) -> object:
        raise errors.PeerFloodError(request=None)

    monkeypatch.setattr(runtime, "_record_event", record_event)
    monkeypatch.setattr(telegram, "send_message", flooded)

    assert await _send_opener(runtime) is OpenerResult.RESTRICTED
    assert [e["event_type"] for e in events] == ["warmup.opener_failed"]
    payload = events[0]["payload"]
    assert isinstance(payload, dict) and "partner_agent_id" in payload


@pytest.mark.asyncio
async def test_peer_flood_from_any_send_is_reported_to_the_warmup_gate() -> None:
    telegram = FakeTelegramClient()
    flood_aware = cast(Any, telegram)
    flood_aware.peer_flood_handler = None
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(),
        memory_service=FakeRuntimeMemoryService(),
    )
    gate = StubGate(None)
    runtime.set_warmup_gate(gate)

    handler = flood_aware.peer_flood_handler
    assert handler is not None
    await handler()

    assert gate.floods == [runtime.config.agent_id]


@pytest.mark.asyncio
async def test_dead_session_during_spambot_check_revokes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, telegram, _ = make_runtime()
    await runtime.start()

    async def dead(*_args: object, **_kwargs: object) -> object:
        raise errors.AuthKeyDuplicatedError(request=None)

    monkeypatch.setattr(telegram, "send_message", dead)
    monkeypatch.setattr(telegram, "get_messages", dead, raising=False)

    assert await runtime.check_spambot() is None
    assert runtime.state.value == "error"
    assert telegram.connected is False
