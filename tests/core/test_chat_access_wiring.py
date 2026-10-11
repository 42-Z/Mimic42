"""Менеджер строит правило доступа к чатам и передаёт его и инструментам, и рантайму."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from mimic42.core import manager as manager_module
from mimic42.core.agent_runtime import AgentRuntimeConfig, ChatListUnavailableError
from mimic42.core.chat_access import ChatAccess
from mimic42.core.manager import AgentManager
from mimic42.core.memory import RuntimeMemoryService

from .test_agent_runtime import FakeLangChainAgent, FakeTelegramClient


def _config(disabled: frozenset[int] = frozenset()) -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_api_id=12345,
        telegram_api_hash="hash",
        telegram_session_string="session",
        system_prompt="system",
        soul_prompt="soul",
        llm_model="mistral-small",
        disabled_chats=disabled,
    )


def _memory_manager() -> AgentManager:
    return AgentManager(
        memory_service_factory=lambda config: RuntimeMemoryService(),
        telegram_client_factory=lambda config: FakeTelegramClient(),
        langchain_agent_factory=lambda config, tools, session_factory: FakeLangChainAgent(),
    )


def _capture_tool_builder(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def capturing_builder(client: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(manager_module, "build_telegram_langchain_tools", capturing_builder)
    return captured


def test_memory_runtime_without_disabled_chats_has_no_access_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_tool_builder(monkeypatch)

    runtime = _memory_manager()._build_runtime_with_memory(_config())

    assert captured["chat_access"] is None
    assert runtime._chat_access is None
    assert runtime._chat_directory is not None


def test_memory_runtime_shares_one_access_rule_with_the_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_tool_builder(monkeypatch)

    runtime = _memory_manager()._build_runtime_with_memory(_config(frozenset({-1001, 42})))

    access = captured["chat_access"]
    assert isinstance(access, ChatAccess)
    assert access.disabled == frozenset({-1001, 42})
    assert runtime._chat_access is access


def test_default_runtime_passes_the_access_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_tool_builder(monkeypatch)
    monkeypatch.setattr(
        manager_module, "build_telegram_client", lambda config: FakeTelegramClient()
    )
    monkeypatch.setattr(
        manager_module, "build_langchain_agent", lambda *args, **kwargs: FakeLangChainAgent()
    )

    runtime = manager_module._build_runtime(_config(frozenset({42})))

    assert isinstance(captured["chat_access"], ChatAccess)
    assert runtime._chat_access is captured["chat_access"]
    assert runtime._chat_directory is not None


@pytest.mark.asyncio
async def test_manager_lists_chats_through_the_runtime() -> None:
    manager = _memory_manager()
    config = _config()
    await manager.create_agent(config)

    # Агент не запущен: клиент не подключён, список недоступен.
    with pytest.raises(ChatListUnavailableError):
        await manager.list_chats(config.agent_id)
