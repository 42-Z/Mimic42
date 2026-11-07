from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.memory import TurnInput
from mimic42.integrations.database_models import AgentMessageModel, AgentModel


class DatabaseShortTermMemory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save_input(self, incoming: TurnInput) -> None:
        payload: dict[str, Any] = {"peer": incoming.peer, "turn_id": incoming.turn_id}
        if incoming.peer_name:
            payload["peer_name"] = incoming.peer_name
        if incoming.agent_name:
            payload["agent_name"] = incoming.agent_name
        if incoming.media:
            payload["media"] = incoming.media
        if incoming.reply:
            payload["reply"] = incoming.reply
        statement = (
            insert(AgentMessageModel)
            .values(
                id=UUID(incoming.turn_id),
                agent_id=incoming.agent_id,
                thread_id=incoming.thread_id,
                direction="incoming",
                role="user",
                content=incoming.raw_text if incoming.raw_text.strip() else incoming.text,
                payload=payload,
            )
            .on_conflict_do_nothing(index_elements=[AgentMessageModel.id])
        )
        async with self._session_factory() as db_session:
            await db_session.execute(statement)
            await db_session.commit()

    async def load_recent_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        since: datetime,
        exclude_turn_id: str | None = None,
    ) -> list[dict[str, Any]]:
        # A context reset from the dashboard moves the lower bound: older rows
        # stay in the transcript but no longer reach the model.
        reset_at = (
            select(AgentModel.context_reset_at).where(AgentModel.id == agent_id).scalar_subquery()
        )
        statement = (
            select(AgentMessageModel)
            .where(
                AgentMessageModel.agent_id == agent_id,
                AgentMessageModel.payload["peer"].as_string() == peer,
                AgentMessageModel.created_at >= since,
                or_(reset_at.is_(None), AgentMessageModel.created_at > reset_at),
            )
            .order_by(AgentMessageModel.created_at.asc())
        )
        if exclude_turn_id is not None:
            stored_turn_id = AgentMessageModel.payload["turn_id"].as_string()
            statement = statement.where(
                or_(stored_turn_id.is_(None), stored_turn_id != exclude_turn_id)
            )
        async with self._session_factory() as db_session:
            result = await db_session.scalars(statement)
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
                if role == "assistant" and not content.strip():
                    # Старая запись с пустым ответом хранит текст в схеме:
                    # модели он нужен, а не пробельный ход в истории.
                    structured = model.payload.get("structured_response")
                    if isinstance(structured, dict):
                        text = structured.get("text", "")
                        if isinstance(text, str):
                            content = text

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
        turn_id: str | None = None,
        thread_id: UUID | None = None,
    ) -> None:
        """Persist generated messages and structured output, never the turn input."""
        now = func.now()
        async with self._session_factory() as db_session:
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

                if role in ("human", "user"):
                    continue
                elif role in ("ai", "assistant"):
                    role = "assistant"
                elif role == "tool":
                    # Skip tool-result messages entirely — they clutter the UI.
                    # Tool usage will be surfaced via agent_events in a later phase.
                    continue

                if role == "assistant":
                    # Structured output often leaves content empty or dumps the
                    # raw repr.  Prefer the human-readable text.  Content can be
                    # whitespace-only ("\n") — truthy, but renders as an empty
                    # paragraph in the feed, so treat it as empty too.
                    human_text = ""
                    if structured_response is not None:
                        raw_text = structured_response.get("text")
                        # None — пустой текст: str(None) дал бы «None» в ленте.
                        if raw_text is None:
                            human_text = ""
                        elif not isinstance(raw_text, str):
                            human_text = str(raw_text)
                        else:
                            human_text = raw_text
                        human_text = human_text.strip()

                    if content.startswith("Returning structured response:") or not content.strip():
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

                # The CHECK constraint (migration ..._relax_agent_messages_content_check)
                # allows empty content ONLY when payload contains tool_calls,
                # structured_response, or tool_call_id.  If none of those keys are
                # present, an empty content="" would violate the constraint and roll
                # back the entire save_messages transaction (silent data loss).
                # Skip such empty assistant strings — they carry no useful data.
                if not content:
                    allowed = (
                        "tool_calls" in payload
                        or "structured_response" in payload
                        or "tool_call_id" in payload
                    )
                    if allowed:
                        content = ""
                    else:
                        continue

                direction = "dashboard_trigger" if role == "system" else "agent_response"

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
