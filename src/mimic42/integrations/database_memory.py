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
        peer_name: str = "",
        agent_name: str = "",
        raw_user_text: str = "",
        turn_id: str | None = None,
        thread_id: UUID | None = None,
    ) -> None:
        """Save a list of LangChain message dicts to the database.

        Normalizes roles, filters tool-result dumps, and stores UI metadata.
        Also persists the incoming user message so the UI can display the full
        conversation thread (incoming + outgoing).
        """
        from datetime import datetime, timedelta

        now = datetime.now(UTC)
        async with self._session_factory() as db_session:
            # ── Persist incoming user message first ──────────────────────────
            # Avoid duplicate if raw_user_text matches the last user message
            # already present in the messages list (e.g. formatted text).
            # Compare normalized text: LangChain dicts may carry the role in
            # either "role" or "type" ("human"/"user"), and whitespace
            # differences must not cause duplicate rows.
            last_user_content = ""
            for msg in reversed(messages):
                msg_role = str(msg.get("role", msg.get("type", "")))
                if msg_role in ("user", "human"):
                    raw_content = msg.get("content", "")
                    if isinstance(raw_content, list):
                        import json as _json

                        raw_content = _json.dumps(raw_content, ensure_ascii=False)
                    elif not isinstance(raw_content, str):
                        raw_content = str(raw_content)
                    last_user_content = raw_content.strip()
                    break

            if raw_user_text and raw_user_text.strip() != last_user_content:
                user_payload: dict[str, Any] = {"peer": peer}
                if peer_name:
                    user_payload["peer_name"] = peer_name
                if agent_name:
                    user_payload["agent_name"] = agent_name
                db_session.add(
                    AgentMessageModel(
                        agent_id=agent_id,
                        direction="incoming",
                        role="user",
                        content=raw_user_text,
                        payload=user_payload,
                        created_at=now,
                    )
                )

            row_count = 0
            for i, msg in enumerate(messages):
                row_count = i + 1
                payload: dict[str, Any] = {"peer": peer}
                if peer_name:
                    payload["peer_name"] = peer_name
                if agent_name:
                    payload["agent_name"] = agent_name
                if turn_id is not None:
                    payload["turn_id"] = turn_id
                role = msg.get("role", msg.get("type", ""))
                content = msg.get("content", "")

                import json

                if isinstance(content, list):
                    content = json.dumps(content, ensure_ascii=False)
                elif not isinstance(content, str):
                    content = str(content)

                # ── Normalize roles ─────────────────────────────────────────────
                if role in ("human", "user"):
                    role = "user"
                elif role in ("ai", "assistant"):
                    role = "assistant"
                elif role == "tool":
                    # Skip tool-result messages entirely — they clutter the UI.
                    # Tool usage will be surfaced via agent_events in a later phase.
                    continue

                # ── Clean assistant content ──────────────────────────────────────
                if role == "assistant":
                    # Structured output often leaves content empty or dumps the
                    # raw repr.  Prefer the human-readable text.
                    human_text = ""
                    if structured_response is not None:
                        human_text = structured_response.get("text", "")

                    if content.startswith("Returning structured response:") or not content:
                        content = human_text

                    # If this is an intermediate AIMessage that only contains
                    # tool_calls with no human-readable text, skip it entirely.
                    # It will be surfaced as an agent_event in Phase 2.
                    if not content and msg.get("tool_calls"):
                        continue

                    # Store the full structured response for the first assistant msg
                    if structured_response is not None:
                        payload["structured_response"] = structured_response
                        structured_response = None

                # The CHECK constraint on content was dropped
                # (migration ..._remove_agent_messages_content_not_blank), so
                # empty content is stored as "" and the UI renders a fallback.
                if not content:
                    content = ""

                # Map to database direction enum
                direction = self._resolve_direction(role, msg)

                # Preserve LangChain-specific fields in payload
                if "tool_calls" in msg:
                    payload["tool_calls"] = msg["tool_calls"]
                if "tool_call_id" in msg:
                    payload["tool_call_id"] = msg["tool_call_id"]
                if "name" in msg:
                    payload["name"] = msg["name"]
                if "id" in msg:
                    payload["id"] = msg["id"]

                db_session.add(
                    AgentMessageModel(
                        agent_id=agent_id,
                        thread_id=thread_id,
                        direction=direction,
                        role=role,
                        content=content,
                        payload=payload,
                        created_at=now + timedelta(microseconds=i * 1000),
                    )
                )

            # With response_format the turn ends on a synthetic tool message:
            # no assistant row exists, so the reply text would be lost. Persist
            # it as its own agent_response row for the dashboard and KPIs.
            if structured_response is not None:
                text = structured_response.get("text", "")
                if text:
                    response_payload: dict[str, Any] = {
                        "peer": peer,
                        "structured_response": structured_response,
                    }
                    if turn_id is not None:
                        response_payload["turn_id"] = turn_id
                    db_session.add(
                        AgentMessageModel(
                            agent_id=agent_id,
                            thread_id=thread_id,
                            direction="agent_response",
                            role="assistant",
                            content=text,
                            payload=response_payload,
                            created_at=now + timedelta(microseconds=(row_count + 1) * 1000),
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
            # Assistant messages are always user-facing responses.
            # Tool calls live in payload and are surfaced via agent_events.
            return "agent_response"
        if role == "system":
            return "dashboard_trigger"
        return "agent_response"
