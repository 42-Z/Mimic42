from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.integrations.database_models import AgentMessageModel


class DatabaseShortTermMemory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load_recent_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        since: datetime,
    ) -> list[dict[str, Any]]:
        async with self._session_factory() as db_session:
            result = await db_session.scalars(
                select(AgentMessageModel)
                .where(
                    AgentMessageModel.agent_id == agent_id,
                    AgentMessageModel.payload["peer"].as_string() == peer,
                    AgentMessageModel.created_at >= since,
                )
                .order_by(AgentMessageModel.created_at.asc())
            )
            messages: list[dict[str, Any]] = []
            for model in result:
                # Normalize stored role to OpenAI/LangChain format
                role = model.role
                # Translate to LangChain expected types
                msg_type = role
                if role == "user":
                    msg_type = "human"
                if role == "assistant":
                    msg_type = "ai"

                content = model.content

                msg: dict[str, Any] = {"type": msg_type, "content": content}
                if msg_type == "tool" or role == "tool":
                    tool_call_id = model.payload.get("tool_call_id")
                    if tool_call_id:
                        msg["tool_call_id"] = tool_call_id
                    name = model.payload.get("name")
                    if name:
                        msg["name"] = name
                elif msg_type == "ai" or role in ("assistant", "ai"):
                    tool_calls = model.payload.get("tool_calls")
                    if tool_calls:
                        msg["tool_calls"] = tool_calls
                messages.append(msg)
            return messages

    async def save_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        messages: list[dict[str, Any]],
        structured_response: dict[str, Any] | None = None,
    ) -> None:
        """Save a list of LangChain message dicts to the database."""
        from datetime import datetime, timedelta

        now = datetime.now(UTC)
        async with self._session_factory() as db_session:
            for i, msg in enumerate(messages):
                payload: dict[str, Any] = {"peer": peer}
                role = msg.get("role", msg.get("type", ""))
                content = msg.get("content", "")

                import json

                if isinstance(content, list):
                    content = json.dumps(content, ensure_ascii=False)
                elif not isinstance(content, str):
                    content = str(content)

                # Map to database direction enum
                direction = self._resolve_direction(role, msg)

                # Populate empty assistant content from structured response
                # to satisfy database CHECK (btrim(content) <> '')
                if not content and role in ("assistant", "ai") and structured_response is not None:
                    content = structured_response.get("text", "") or "[empty]"

                # Ensure content never violates NOT NULL / CHECK constraints
                if not content:
                    content = "[empty]"

                # Preserve LangChain-specific fields in payload
                if "tool_calls" in msg:
                    payload["tool_calls"] = msg["tool_calls"]
                if "tool_call_id" in msg:
                    payload["tool_call_id"] = msg["tool_call_id"]
                if "name" in msg:
                    payload["name"] = msg["name"]
                if "id" in msg:
                    payload["id"] = msg["id"]

                # Attach structured response to the first assistant message
                if structured_response is not None:
                    if direction == "agent_response":
                        payload["structured_response"] = structured_response
                        structured_response = None

                db_session.add(
                    AgentMessageModel(
                        agent_id=agent_id,
                        direction=direction,
                        role=role,
                        content=content,
                        payload=payload,
                        created_at=now + timedelta(microseconds=i * 1000),
                    )
                )
            await db_session.commit()

    @staticmethod
    def _resolve_direction(role: str, msg: dict[str, Any]) -> str:
        if role in ("user", "human"):
            return "incoming"
        if role == "tool":
            return "tool_result"
        if role in ("assistant", "ai"):
            return "tool_call" if msg.get("tool_calls") else "agent_response"
        if role == "system":
            return "dashboard_trigger"
        return "agent_response"
