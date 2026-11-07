from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, Field

DEFAULT_SHORT_TERM_TTL = timedelta(hours=3)
DEFAULT_MAX_CONTEXT_TOKENS = 65_536
logger = logging.getLogger("mimic42.memory")


@dataclass(frozen=True, kw_only=True)
class TurnInput:
    agent_id: UUID
    turn_id: str
    peer: str
    text: str
    raw_text: str
    created_at: datetime
    peer_name: str = ""
    agent_name: str = ""
    thread_id: UUID | None = None
    media: list[dict[str, Any]] = field(default_factory=list)
    reply: dict[str, Any] | None = None


async def settle_persistence(operation: Coroutine[Any, Any, None]) -> None:
    """Finish a finite persistence operation before propagating waiter cancellation."""
    task = asyncio.create_task(operation)
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
        except Exception:
            if cancellation is None:
                raise
    if cancellation is not None:
        if not task.cancelled() and task.exception() is not None:
            logger.warning("Persistence failed during cancellation", exc_info=task.exception())
        raise cancellation
    task.result()


class MemoryRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MemoryMessage(BaseModel):
    agent_id: UUID
    peer: str = Field(min_length=1)
    role: MemoryRole
    content: str
    created_at: datetime


class ShortTermMemoryStore(Protocol):
    async def save_input(self, incoming: TurnInput) -> None: ...

    async def load_recent_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        since: datetime,
        exclude_turn_id: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def save_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        messages: list[dict[str, Any]],
        structured_response: dict[str, Any] | None = None,
        peer_name: str = "",
        agent_name: str = "",
        turn_id: str | None = None,
        thread_id: UUID | None = None,
    ) -> None: ...


class LongTermMemoryStore(Protocol):
    async def search(self, *, agent_id: UUID, query: str) -> list[str]: ...

    async def save_turn(
        self,
        *,
        agent_id: UUID,
        user_text: str,
        assistant_text: str,
    ) -> None: ...


class LongTermMemoryLike(LongTermMemoryStore, Protocol):
    """Полный контракт долгосрочной памяти: рантайму нужны только search и
    save_turn, маршрутам API — чтение, поиск и очистка. Прод реализует его
    через Mem0, тесты — подделкой в памяти."""

    async def get_all_memories(self, agent_id: UUID) -> list[dict[str, Any]]: ...

    async def search_memories(self, agent_id: UUID, query: str) -> list[dict[str, Any]]: ...

    async def get_memory_history(self, memory_id: str) -> list[dict[str, Any]]: ...

    async def clear_all_memories(self, agent_id: UUID) -> None: ...


class MemoryServiceLike(Protocol):
    async def prepare_turn(self, incoming: TurnInput) -> list[dict[str, Any]]: ...

    async def save_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        input_messages: list[dict[str, Any]],
        output_messages: list[dict[str, Any]],
        structured_response: dict[str, Any] | None = None,
        peer_name: str = "",
        agent_name: str = "",
        turn_id: str | None = None,
        thread_id: UUID | None = None,
    ) -> None: ...


class RuntimeMemoryService:
    def __init__(
        self,
        *,
        short_term: ShortTermMemoryStore | None = None,
        long_term: LongTermMemoryStore | None = None,
        short_term_ttl: timedelta = DEFAULT_SHORT_TERM_TTL,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        token_counter: Callable[[str], int] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._short_term = short_term
        self._long_term = long_term
        self._short_term_ttl = short_term_ttl
        self._max_context_tokens = max_context_tokens
        self._token_counter = token_counter or _estimate_tokens
        self._now = now or (lambda: datetime.now(UTC))

    async def prepare_turn(self, incoming: TurnInput) -> list[dict[str, Any]]:
        if self._short_term is not None:
            await settle_persistence(self._save_input(incoming))
        return await self.build_messages(
            agent_id=incoming.agent_id,
            peer=incoming.peer,
            user_text=incoming.text,
            exclude_turn_id=incoming.turn_id,
        )

    async def _save_input(self, incoming: TurnInput) -> None:
        assert self._short_term is not None
        try:
            await self._short_term.save_input(incoming)
        except Exception:
            logger.exception(
                "Failed to save incoming message (agent_id=%s, peer=%s)",
                incoming.agent_id,
                incoming.peer,
            )

    async def build_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        user_text: str,
        exclude_turn_id: str | None = None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        long_term_context = await self._load_long_term_context(agent_id=agent_id, query=user_text)
        if long_term_context:
            messages.append(
                {
                    "type": "system",
                    "role": MemoryRole.SYSTEM.value,
                    "content": "Long-term memory:\n"
                    + "\n".join(f"- {memory}" for memory in long_term_context),
                }
            )

        short_term_messages = await self._load_short_term_context(
            agent_id=agent_id, peer=peer, exclude_turn_id=exclude_turn_id
        )
        messages.extend(short_term_messages)

        # OpenRouter / Mistral fix: Mistral rejects requests where 'human' directly follows 'tool'.
        # If the last message before the new user input is a 'tool' message (meaning the agent
        # didn't get to reply after a tool execution), we inject a dummy 'ai' message to
        # satisfy the LLM constraints.
        if messages:
            last_msg_type = messages[-1].get("type", messages[-1].get("role", ""))
            if last_msg_type == "tool":
                messages.append(
                    {
                        "type": "ai",
                        "role": "assistant",
                        "content": (
                            "The tool executed, but the user interrupted before I could reply."
                        ),
                    }
                )

        messages.append({"type": "human", "role": MemoryRole.USER.value, "content": user_text})
        return self._fit_token_budget(messages)

    async def save_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        input_messages: list[dict[str, Any]],
        output_messages: list[dict[str, Any]],
        structured_response: dict[str, Any] | None = None,
        peer_name: str = "",
        agent_name: str = "",
        turn_id: str | None = None,
        thread_id: UUID | None = None,
    ) -> None:
        new_messages = [
            message
            for message in _extract_new_messages(input_messages, output_messages)
            if message.get("type", message.get("role", "")) not in ("human", "user")
        ]

        if self._short_term is not None and (new_messages or structured_response is not None):
            try:
                await self._short_term.save_messages(
                    agent_id=agent_id,
                    peer=peer,
                    messages=new_messages,
                    structured_response=structured_response,
                    peer_name=peer_name,
                    agent_name=agent_name,
                    turn_id=turn_id,
                    thread_id=thread_id,
                )
            except Exception:
                logger.exception(
                    "Failed to save messages to short-term store (agent_id=%s, peer=%s, count=%d)",
                    agent_id,
                    peer,
                    len(new_messages),
                )

        if self._long_term is not None:
            user_text = _extract_last_user_text(input_messages)
            assistant_text = _extract_last_assistant_text(new_messages)
            # With structured output the final AIMessage has empty content;
            # fall back to the structured response text so long-term memory
            # still captures the assistant reply.
            if not assistant_text and structured_response is not None:
                assistant_text = structured_response.get("text", "")
            if user_text or assistant_text:
                try:
                    await self._long_term.save_turn(
                        agent_id=agent_id,
                        user_text=user_text,
                        assistant_text=assistant_text,
                    )
                except Exception:
                    logger.warning(
                        "Failed to save turn to long-term memory (agent_id=%s)",
                        agent_id,
                        exc_info=True,
                    )

    async def _load_short_term_context(
        self,
        *,
        agent_id: UUID,
        peer: str,
        exclude_turn_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._short_term is None:
            return []
        since = self._now() - self._short_term_ttl
        return await self._short_term.load_recent_messages(
            agent_id=agent_id,
            peer=peer,
            since=since,
            exclude_turn_id=exclude_turn_id,
        )

    async def _load_long_term_context(self, *, agent_id: UUID, query: str) -> list[str]:
        if self._long_term is None:
            return []
        try:
            return await self._long_term.search(agent_id=agent_id, query=query)
        except Exception:
            logger.warning("Failed to search long-term memory", exc_info=True)
            return []

    def _fit_token_budget(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected_reversed: list[dict[str, Any]] = []
        token_total = 0
        for message in reversed(messages):
            content = message.get("content", "")
            if isinstance(content, list):
                import json

                content_str = json.dumps(content, ensure_ascii=False)
            else:
                content_str = str(content)
            # Roughly account for tool calls too
            tool_calls = message.get("tool_calls", [])
            tool_text = ""
            for tc in tool_calls:
                tool_text += tc.get("name", "") + " " + str(tc.get("args", ""))
            message_tokens = self._token_counter(content_str + tool_text)
            if selected_reversed and token_total + message_tokens > self._max_context_tokens:
                break
            selected_reversed.append(message)
            token_total += message_tokens
        return list(reversed(selected_reversed))


def _extract_new_messages(
    input_messages: list[dict[str, Any]],
    output_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Identify messages generated during this turn (not in input)."""
    import json

    def _key(msg: dict[str, Any]) -> str:
        role = msg.get("type", msg.get("role", ""))
        content = msg.get("content", "")
        tool_call_id = msg.get("tool_call_id", "")
        tool_calls = msg.get("tool_calls", [])
        return json.dumps(
            [role, content, tool_call_id, tool_calls],
            sort_keys=True,
            default=str,
        )

    input_keys = {_key(m) for m in input_messages}
    return [m for m in output_messages if _key(m) not in input_keys]


def _extract_last_user_text(messages: list[dict[str, Any]]) -> str:
    """Extract the last user message content from the full conversation."""
    for msg in reversed(messages):
        role = msg.get("type", msg.get("role", ""))
        if role in ("human", "user"):
            return msg.get("content", "")
    return ""


def _extract_last_assistant_text(messages: list[dict[str, Any]]) -> str:
    """Extract the last assistant message content (ignoring tool calls)."""
    for msg in reversed(messages):
        role = msg.get("type", msg.get("role", ""))
        if role in ("ai", "assistant"):
            return msg.get("content", "")
    return ""


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
