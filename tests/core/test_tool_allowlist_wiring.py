"""Менеджер передаёт allowlist в сборщик инструментов в обоих путях сборки."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from mimic42.core import manager as manager_module
from mimic42.core.agent_runtime import AgentRuntimeConfig
from mimic42.core.manager import AgentManager
from mimic42.core.memory import RuntimeMemoryService

from .test_agent_runtime import FakeLangChainAgent, FakeTelegramClient


def _config() -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_api_id=12345,
        telegram_api_hash="hash",
        telegram_session_string="session",
        system_prompt="system",
        soul_prompt="soul",
        llm_model="mistral-small",
    )


def test_memory_runtime_passes_allowlist_to_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def capturing_builder(client: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(manager_module, "build_telegram_langchain_tools", capturing_builder)
    manager = AgentManager(
        memory_service_factory=lambda config: RuntimeMemoryService(),
        telegram_client_factory=lambda config: FakeTelegramClient(),
        langchain_agent_factory=lambda config, tools, session_factory: FakeLangChainAgent(),
    )
    config = _config()
    config.enabled_tools = frozenset({"send_text_message"})

    manager._build_runtime_with_memory(config)

    assert captured["enabled_tools"] == frozenset({"send_text_message"})


def test_default_runtime_passes_allowlist_to_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def capturing_builder(client: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(manager_module, "build_telegram_langchain_tools", capturing_builder)
    monkeypatch.setattr(
        manager_module, "build_telegram_client", lambda config: FakeTelegramClient()
    )
    monkeypatch.setattr(
        manager_module, "build_langchain_agent", lambda *args, **kwargs: FakeLangChainAgent()
    )
    config = _config()
    config.enabled_tools = frozenset({"view_image"})

    manager_module._build_runtime(config)

    assert captured["enabled_tools"] == frozenset({"view_image"})


def test_runtime_without_allowlist_passes_none(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def capturing_builder(client: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(manager_module, "build_telegram_langchain_tools", capturing_builder)
    manager = AgentManager(
        memory_service_factory=lambda config: RuntimeMemoryService(),
        telegram_client_factory=lambda config: FakeTelegramClient(),
        langchain_agent_factory=lambda config, tools, session_factory: FakeLangChainAgent(),
    )

    manager._build_runtime_with_memory(_config())

    assert captured["enabled_tools"] is None
