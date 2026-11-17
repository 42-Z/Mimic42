from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import PrivateAttr

from mimic42.core.agent_runtime import AgentRuntimeConfig
from mimic42.core.onboarding import load_default_system_prompt
from mimic42.core.system_prompt import render_system_prompt
from mimic42.core.tool_config import DEFAULT_CONVERSATIONAL_TOOLS
from mimic42.integrations import langchain_agent, tracing
from mimic42.integrations.agent_response_schema import AgentResponse
from mimic42.integrations.telegram_tools import (
    TelethonRequestClient,
    build_telegram_langchain_tools,
)


class RecordingModel(GenericFakeChatModel):
    _bound_names: set[str] = PrivateAttr(default_factory=set)

    def bind_tools(self, tools: Any, **kwargs: Any) -> RecordingModel:
        for tool in tools:
            self._bound_names.add(
                tool.name if isinstance(tool, BaseTool) else tool["function"]["name"]
            )
        return self


class RecordingMessages(BaseCallbackHandler):
    def __init__(self) -> None:
        self.messages: list[BaseMessage] = []

    def on_chat_model_start(
        self, serialized: dict[str, Any], messages: list[list[BaseMessage]], **kwargs: Any
    ) -> None:
        self.messages.extend(messages[0])


@pytest.mark.parametrize(
    "selection",
    [None, frozenset(DEFAULT_CONVERSATIONAL_TOOLS), frozenset(), frozenset({"send_reaction"})],
)
async def test_actual_graph_binds_selected_schemas_and_renders_the_same_prompt(
    monkeypatch: pytest.MonkeyPatch, selection: frozenset[str] | None
) -> None:
    recording = RecordingMessages()
    model = RecordingModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "AgentResponse",
                            "args": {"text": "Привет!", "send_any_message": True, "reply_to": 12},
                            "id": "response",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        ),
        callbacks=[recording],
    )
    monkeypatch.setattr(langchain_agent, "build_chat_model", lambda config: model)
    monkeypatch.setattr(tracing, "_enabled", False)
    config = AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_api_id=12345,
        telegram_api_hash="hash",
        system_prompt=load_default_system_prompt(),
        soul_prompt="Soul with {{tool_instructions}} and view_image",
        name="Mimic",
        enabled_tools=selection,
    )
    client = MagicMock(spec=TelethonRequestClient)
    tools = build_telegram_langchain_tools(client, enabled_tools=selection)
    agent = langchain_agent.build_langchain_agent(config, tools=tools)
    result = cast(dict[str, Any], await agent.ainvoke({"messages": [("user", "Привет")]}))
    assert isinstance(result, dict)
    assert client.mock_calls == []
    actual_names = frozenset(tool.name for tool in tools)
    assert model._bound_names == actual_names | {"AgentResponse"}
    [system] = [message for message in recording.messages if isinstance(message, SystemMessage)]
    assert system.content == render_system_prompt(
        config.system_prompt,
        available_names=actual_names,
        name=config.name,
        soul=config.soul_prompt,
    )
    assert result["structured_response"] == AgentResponse(
        text="Привет!", send_any_message=True, reply_to=12
    )


@pytest.mark.parametrize("allowed", [False, True])
async def test_actual_graph_enforces_configured_allowlist(
    monkeypatch: pytest.MonkeyPatch, allowed: bool
) -> None:
    executions: list[str] = []

    async def execute() -> str:
        executions.append("send_reaction")
        return "done"

    tool = StructuredTool.from_function(
        coroutine=execute,
        name="send_reaction",
        description="Send a reaction.",
    )
    model = RecordingModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": tool.name, "args": {}, "id": "action", "type": "tool_call"}
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "AgentResponse",
                            "args": {"text": "", "send_any_message": False},
                            "id": "response",
                            "type": "tool_call",
                        }
                    ],
                ),
            ]
        )
    )
    monkeypatch.setattr(langchain_agent, "build_chat_model", lambda config: model)
    monkeypatch.setattr(tracing, "_enabled", False)
    config = AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_api_id=12345,
        telegram_api_hash="hash",
        system_prompt=load_default_system_prompt(),
        enabled_tools=frozenset({tool.name}) if allowed else frozenset(),
    )
    agent = langchain_agent.build_langchain_agent(config, tools=[tool])

    result = cast(dict[str, Any], await agent.ainvoke({"messages": [("user", "Реакция")]}))

    assert isinstance(result, dict)
    [action] = [
        message
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.tool_call_id == "action"
    ]
    if allowed:
        assert executions == ["send_reaction"]
        assert action.content == "done"
        assert action.status == "success"
    else:
        assert executions == []
        assert action.status == "error"
        assert "отключён в настройках агента" in action.content
    assert result["structured_response"] == AgentResponse(text="", send_any_message=False)
