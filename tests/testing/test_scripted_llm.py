from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentRuntimeState,
    AgentTrigger,
    MimicAgentRuntime,
)
from mimic42.core.manager import AgentManager
from mimic42.core.memory import RuntimeMemoryService
from mimic42.testing.llm import Crash, Empty, Reply, ScriptedAgent, ScriptedAgentFactory, Silent
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramClient


def _make_config(agent_id: UUID | None = None, owner_id: UUID | None = None) -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=agent_id or uuid4(),
        owner_id=owner_id or uuid4(),
        telegram_session_string="sessions/test-agent",
        telegram_api_id=12345,
        telegram_api_hash="hash",
        llm_model="openrouter/free",
        system_prompt="Base system prompt",
        soul_prompt="Quiet direct style",
    )


async def _running_runtime(agent: ScriptedAgent) -> tuple[MimicAgentRuntime, FakeTelegramClient]:
    telegram = FakeTelegramClient(FakeTelegramAccount())
    telegram.account.authorized = True
    runtime = MimicAgentRuntime(
        config=_make_config(),
        telegram_client=telegram,
        langchain_agent=agent,
    )
    await runtime.start()
    return runtime, telegram


@pytest.mark.asyncio
async def test_reply_turn_sends_message() -> None:
    agent = ScriptedAgent([Reply("привет")], default_reply="готово")
    runtime, telegram = await _running_runtime(agent)

    result = await runtime.trigger_message(AgentTrigger(peer="123", text="хай"))

    assert result.response_text == "привет"
    assert telegram.sent_messages == [("123", "привет")]


@pytest.mark.asyncio
async def test_silent_turn_sends_nothing() -> None:
    agent = ScriptedAgent([Silent()], default_reply="готово")
    runtime, telegram = await _running_runtime(agent)

    await runtime.trigger_message(AgentTrigger(peer="123", text="хай"))

    assert telegram.sent_messages == []


@pytest.mark.asyncio
async def test_empty_turn_does_not_send_empty_message() -> None:
    agent = ScriptedAgent([Empty()], default_reply="готово")
    runtime, telegram = await _running_runtime(agent)

    await runtime.trigger_message(AgentTrigger(peer="123", text="хай"))

    assert telegram.sent_messages == []


@pytest.mark.asyncio
async def test_crash_turn_does_not_crash_runtime() -> None:
    agent = ScriptedAgent([Crash()], default_reply="готово")
    runtime, telegram = await _running_runtime(agent)

    with pytest.raises(RuntimeError):
        await runtime.trigger_message(AgentTrigger(peer="123", text="хай"))

    assert runtime.state is AgentRuntimeState.RUNNING
    assert telegram.sent_messages == []
    assert len(agent.calls) == 1


@pytest.mark.asyncio
async def test_script_falls_back_to_default_reply_once_exhausted() -> None:
    agent = ScriptedAgent([Reply("первый")], default_reply="дефолт")
    runtime, telegram = await _running_runtime(agent)

    await runtime.trigger_message(AgentTrigger(peer="123", text="раз"))
    await runtime.trigger_message(AgentTrigger(peer="123", text="два"))

    assert telegram.sent_messages == [("123", "первый"), ("123", "дефолт")]


@pytest.mark.asyncio
async def test_scripted_agent_factory_wires_into_agent_manager() -> None:
    factory = ScriptedAgentFactory(default_reply="готово")
    config = _make_config()
    factory.set_script(config.agent_id, [Reply("настроенный ответ")])

    def telegram_client_factory(_: AgentRuntimeConfig) -> FakeTelegramClient:
        client = FakeTelegramClient(FakeTelegramAccount())
        client.account.authorized = True
        return client

    manager = AgentManager(
        memory_service_factory=lambda _: RuntimeMemoryService(),
        telegram_client_factory=telegram_client_factory,
        langchain_agent_factory=factory,
    )

    await manager.create_agent(config, start=True)
    assert isinstance(factory.built[config.agent_id], ScriptedAgent)

    result = await manager.trigger_message(config.agent_id, AgentTrigger(peer="1", text="hi"))

    assert result.response_text == "настроенный ответ"
