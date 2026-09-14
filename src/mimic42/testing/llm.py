"""Заготовленные ответы модели: правильные и намеренно кривые.

Живая модель сюда не входит — она проверяется отдельным набором.

Форма возвращаемого значения ``ainvoke`` повторяет то, что реально отдаёт
``create_agent`` с ``response_format=AgentResponse``
(``src/mimic42/integrations/langchain_agent.py``,
``src/mimic42/integrations/agent_response_schema.py``): всегда есть
``structured_response`` с полями ``text``/``send_any_message``/``reply_to``.
Инструменты (``ToolCall``/неизвестный инструмент) исполняются внутри
LangGraph и этому фейку не видны, поэтому здесь не эмулируются — сценарии
ограничены тем, что ``MimicAgentRuntime`` реально наблюдает на выходе
``ainvoke``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass
class Reply:
    """Обычный ответ модели."""

    text: str
    send_any_message: bool = True
    reply_to: int | None = None


@dataclass
class Silent:
    """Модель явно решает промолчать (``send_any_message=False``)."""


@dataclass
class Empty:
    """Модель вернула пустой текст — не должно превратиться в пустое сообщение."""


@dataclass
class Crash:
    """Структурированный ответ не прошёл валидацию: ``ainvoke`` бросает исключение."""

    message: str = "структурированный ответ модели не прошёл валидацию"


ScriptedTurn = Reply | Silent | Empty | Crash


class ScriptedAgent:
    def __init__(self, script: list[ScriptedTurn], default_reply: str) -> None:
        self._script = list(script)
        self._default_reply = default_reply
        self.calls: list[dict[str, object]] = []

    async def ainvoke(
        self,
        input_data: dict[str, object],
        context: object | None = None,
    ) -> dict[str, object]:
        self.calls.append(input_data)
        turn: ScriptedTurn = self._script.pop(0) if self._script else Reply(self._default_reply)
        return _render(turn)


def _render(turn: ScriptedTurn) -> dict[str, object]:
    if isinstance(turn, Crash):
        raise RuntimeError(turn.message)
    if isinstance(turn, Silent):
        structured: dict[str, Any] = {"text": "", "send_any_message": False, "reply_to": None}
        content = ""
    elif isinstance(turn, Empty):
        structured = {"text": "", "send_any_message": True, "reply_to": None}
        content = ""
    elif isinstance(turn, Reply):
        structured = {
            "text": turn.text,
            "send_any_message": turn.send_any_message,
            "reply_to": turn.reply_to,
        }
        content = turn.text
    else:  # pragma: no cover - защита от расширения ScriptedTurn без обновления _render
        raise TypeError(f"Unknown scripted turn: {turn!r}")
    return {
        "messages": [{"role": "assistant", "content": content}],
        "structured_response": structured,
    }


@dataclass
class ScriptedAgentFactory:
    """Подставляется в ``langchain_agent_factory`` вместо ``build_langchain_agent``."""

    default_reply: str = "готово"
    scripts: dict[UUID, list[ScriptedTurn]] = field(default_factory=dict)
    built: dict[UUID, ScriptedAgent] = field(default_factory=dict)

    def set_script(self, agent_id: UUID, script: list[ScriptedTurn]) -> None:
        self.scripts[agent_id] = script

    def __call__(
        self,
        config: Any,
        tools: Any,
        session_factory: Any,
    ) -> ScriptedAgent:
        agent = ScriptedAgent(list(self.scripts.get(config.agent_id, [])), self.default_reply)
        self.built[config.agent_id] = agent
        return agent
