from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import DEFAULT_LLM_MODEL, AgentRuntimeConfig, AgentRuntimeState
from mimic42.core.agent_store import (
    AgentActivity,
    AgentMessageRecord,
    AgentRecord,
    ConversationPage,
    ConversationTurn,
    ToolCallRecord,
    reply_target_of,
)
from mimic42.core.onboarding import OnboardingSession, SecretCipher
from mimic42.integrations.database_models import (
    AgentEventModel,
    AgentMessageModel,
    AgentModel,
    AgentOnboardingSessionModel,
    TelegramSessionModel,
)

logger = logging.getLogger("mimic42.agent_store")


def _cursor_condition(model: Any, before: datetime, before_id: UUID | None) -> Any:
    """Keyset cursor: strictly older than ``before``; when several rows share
    the boundary timestamp, the id breaks the tie so nothing is skipped."""
    condition = model.created_at < before
    if before_id is not None:
        condition = or_(
            condition,
            and_(model.created_at == before, model.id < before_id),
        )
    return condition


def _payload_turn_id(row: Any) -> str | None:
    payload = row.payload or {}
    value = payload.get("turn_id")
    return str(value) if value else None


class DatabaseAgentStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        cipher: SecretCipher | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher
        self._llm_model = DEFAULT_LLM_MODEL

    async def create_from_onboarding(self, session: OnboardingSession) -> AgentRecord:
        if not session.name or not session.soul_prompt:
            raise ValueError("Onboarding session is missing agent profile fields")

        async with self._session_factory() as db_session:
            # Acquire row-level lock to prevent TOCTOU race on concurrent finalization
            agent = await db_session.scalar(
                select(AgentModel).where(AgentModel.id == session.onboarding_id).with_for_update()
            )
            if agent is None:
                agent = AgentModel(id=session.onboarding_id)
                db_session.add(agent)

            agent.owner_id = session.owner_id
            agent.name = session.name
            agent.status = AgentRuntimeState.STOPPED.value
            agent.soul_prompt = session.soul_prompt

            telegram_session = await db_session.scalar(
                select(TelegramSessionModel)
                .where(TelegramSessionModel.agent_id == session.onboarding_id)
                .with_for_update()
            )
            if telegram_session is None:
                telegram_session = TelegramSessionModel(agent_id=session.onboarding_id)
                db_session.add(telegram_session)

            telegram_session.session_name = session.onboarding_id.hex
            telegram_session.phone_number = session.phone_number
            telegram_session.api_id = session.api_id
            telegram_session.api_hash_ciphertext = session.api_hash_secret
            telegram_session.session_ciphertext = session.session_secret
            telegram_session.authorization_status = "authorized"
            telegram_session.last_authorized_at = _now()

            await db_session.commit()
            return _agent_record(agent)

    async def rebind_telegram_session(self, agent_id: UUID, session: OnboardingSession) -> None:
        """Обновляется только авторизация (auth key).

        Номер, приложение и остальные данные агента не меняются. Строковая
        блокировка защищает от гонки с параллельным финалом онбординга того же
        агента.
        """
        if (
            session.api_id is None
            or session.api_hash_secret is None
            or session.session_secret is None
        ):
            raise ValueError("Onboarding session is missing Telegram credentials")

        async with self._session_factory() as db_session:
            telegram_session = await db_session.scalar(
                select(TelegramSessionModel)
                .where(TelegramSessionModel.agent_id == agent_id)
                .with_for_update()
            )
            if telegram_session is None:
                raise KeyError(f"Agent {agent_id} does not have a telegram session")
            telegram_session.session_ciphertext = session.session_secret
            telegram_session.authorization_status = "authorized"
            telegram_session.last_authorized_at = _now()
            telegram_session.last_error = None
            await db_session.commit()

    async def get_runtime_config(self, agent_id: UUID) -> AgentRuntimeConfig:
        async with self._session_factory() as db_session:
            row = await db_session.execute(
                select(AgentModel, TelegramSessionModel)
                .join(TelegramSessionModel, TelegramSessionModel.agent_id == AgentModel.id)
                .where(AgentModel.id == agent_id)
            )
            item = row.first()
            if item is None:
                raise KeyError(f"Agent {agent_id} does not have a runtime config")
            agent, telegram_session = item
            from mimic42.core.onboarding import load_default_system_prompt

            return AgentRuntimeConfig(
                agent_id=agent.id,
                owner_id=agent.owner_id,
                telegram_api_id=telegram_session.api_id or 0,
                telegram_api_hash=(
                    self._cipher.decrypt(telegram_session.api_hash_ciphertext)
                    if self._cipher and telegram_session.api_hash_ciphertext
                    else telegram_session.api_hash_ciphertext or ""
                ),
                telegram_session_string=(
                    self._cipher.decrypt(telegram_session.session_ciphertext)
                    if self._cipher and telegram_session.session_ciphertext
                    else telegram_session.session_ciphertext
                ),
                telegram_session_token=telegram_session.session_ciphertext,
                llm_model=(
                    agent.settings.get("model", self._llm_model)
                    if agent.settings
                    else self._llm_model
                ),
                reasoning_effort=agent.settings.get("reasoning_effort", "high")
                if agent.settings
                else "high",
                system_prompt=load_default_system_prompt(),
                soul_prompt=agent.soul_prompt,
                name=agent.name,
            )

    async def list_agents(self, *, owner_id: UUID | None = None) -> list[AgentRecord]:
        statement = select(AgentModel).order_by(AgentModel.created_at.desc())
        if owner_id is not None:
            statement = statement.where(AgentModel.owner_id == owner_id)
        async with self._session_factory() as db_session:
            return [_agent_record(agent) for agent in await db_session.scalars(statement)]

    async def update_status(self, agent_id: UUID, state: AgentRuntimeState) -> None:
        async with self._session_factory() as db_session:
            agent = await db_session.get(AgentModel, agent_id)
            if agent is None:
                return
            agent.status = state.value
            if state is AgentRuntimeState.RUNNING:
                agent.last_started_at = _now()
            if state is AgentRuntimeState.STOPPED:
                agent.last_stopped_at = _now()
            await db_session.commit()

    async def delete_agent(self, agent_id: UUID) -> None:
        async with self._session_factory() as db_session:
            # Remove leftover onboarding drafts first: the FK is `on delete set null`,
            # so without this the wizard would pick up an abandoned session.
            # `id == agent_id` covers the originating session even when the
            # frontend failed to mark completed_agent_id after finalization.
            await db_session.execute(
                delete(AgentOnboardingSessionModel).where(
                    or_(
                        AgentOnboardingSessionModel.completed_agent_id == agent_id,
                        AgentOnboardingSessionModel.id == agent_id,
                    )
                )
            )
            # telegram_sessions, message_threads, agent_messages, agent_events
            # and agent_timers are removed by ON DELETE CASCADE.
            await db_session.execute(delete(AgentModel).where(AgentModel.id == agent_id))
            await db_session.commit()

    async def list_messages(
        self, *, agent_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[AgentMessageRecord]:
        async with self._session_factory() as db_session:
            messages = await db_session.scalars(
                select(AgentMessageModel)
                .where(AgentMessageModel.agent_id == agent_id)
                .order_by(AgentMessageModel.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            records = []
            for message in messages:
                content = message.content
                # With structured output the assistant message content is empty.
                # Present the human-readable text from the stored schema instead.
                if not content and message.role == "assistant":
                    structured = message.payload.get("structured_response")
                    if isinstance(structured, dict):
                        content = structured.get("text", "")
                records.append(
                    AgentMessageRecord(
                        id=message.id,
                        agent_id=message.agent_id,
                        peer=str(message.payload.get("peer", "")),
                        peer_name=str(message.payload.get("peer_name", "")),
                        agent_name=str(message.payload.get("agent_name", "")),
                        role=message.role,
                        content=content,
                        direction=message.direction,
                        payload=message.payload or {},
                        thread_id=message.thread_id,
                        created_at=message.created_at,
                    )
                )
            return records

    async def list_activities(
        self, *, agent_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[AgentActivity]:
        async with self._session_factory() as db_session:
            activities = await db_session.scalars(
                select(AgentEventModel)
                .where(AgentEventModel.agent_id == agent_id)
                .order_by(AgentEventModel.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            return [
                AgentActivity(
                    id=activity.id,
                    agent_id=activity.agent_id,
                    event_type=activity.event_type,
                    status=activity.status,
                    created_at=activity.created_at,
                    payload=activity.payload or {},
                    result=activity.result,
                    error=activity.error,
                    started_at=activity.started_at,
                    completed_at=activity.completed_at,
                )
                for activity in activities
            ]

    async def get_conversation(
        self,
        *,
        agent_id: UUID,
        limit: int = 50,
        before: datetime | None = None,
        before_id: UUID | None = None,
    ) -> ConversationPage:
        # Turn-aligned pagination. A turn may hold dozens of tool events, so a
        # fixed event window would cut its history; instead the message window
        # is fetched first and then *all* events of the turns in it. The oldest
        # fetched turn is dropped when the message read was saturated: it may
        # continue below the window and a partial turn must never reach a page.
        # The cursor is a keyset pair (created_at, id): equal timestamps cannot
        # lose or duplicate a turn the way a plain ``<`` on the timestamp does.
        msg_fetch = limit * 4 + 60
        evt_fetch = limit * 4 + 60
        async with self._session_factory() as db_session:
            msg_query = (
                select(AgentMessageModel)
                .where(AgentMessageModel.agent_id == agent_id)
                .order_by(AgentMessageModel.created_at.desc(), AgentMessageModel.id.desc())
                .limit(msg_fetch)
            )
            if before is not None:
                msg_query = msg_query.where(_cursor_condition(AgentMessageModel, before, before_id))
            messages = list(reversed(list(await db_session.scalars(msg_query))))

            boundary_turn_id: str | None = None
            if len(messages) >= msg_fetch:
                boundary_turn_id = _payload_turn_id(messages[0])
            turn_ids = {turn for turn in map(_payload_turn_id, messages) if turn}
            if boundary_turn_id is not None:
                turn_ids.discard(boundary_turn_id)

            turn_events = (
                list(
                    await db_session.scalars(
                        select(AgentEventModel)
                        .where(AgentEventModel.agent_id == agent_id)
                        .where(AgentEventModel.payload["turn_id"].as_string().in_(sorted(turn_ids)))
                        .order_by(AgentEventModel.created_at.asc(), AgentEventModel.id.asc())
                    )
                )
                if turn_ids
                else []
            )

            # Everything else: lifecycle events, legacy rows and events of turns
            # whose messages are outside this window (orphan/failed turns). Each
            # is a whole block on its own, so a bounded window is safe here.
            if turn_ids:
                residual_condition = or_(
                    AgentEventModel.payload["turn_id"].as_string().is_(None),
                    AgentEventModel.payload["turn_id"].as_string().not_in(sorted(turn_ids)),
                )
            else:
                residual_condition = AgentEventModel.payload["turn_id"].as_string().is_(None)
            standalone_query = (
                select(AgentEventModel)
                .where(AgentEventModel.agent_id == agent_id)
                .where(residual_condition)
                .order_by(AgentEventModel.created_at.desc(), AgentEventModel.id.desc())
                .limit(evt_fetch)
            )
            if before is not None:
                standalone_query = standalone_query.where(
                    _cursor_condition(AgentEventModel, before, before_id)
                )
            standalone_events = list(reversed(list(await db_session.scalars(standalone_query))))
            fetched_event_ids = {evt.id for evt in turn_events}
            residual_events = [evt for evt in standalone_events if evt.id not in fetched_event_ids]

        # Build unified timeline, oldest first.
        timeline: list[tuple[str, datetime, Any]] = []
        for msg in messages:
            if boundary_turn_id is not None and _payload_turn_id(msg) == boundary_turn_id:
                continue
            timeline.append(("msg", msg.created_at, msg))
        for evt in [*turn_events, *residual_events]:
            timeline.append(("evt", evt.created_at, evt))
        timeline.sort(key=lambda x: (x[1], x[2].id))

        def _message_content(msg: AgentMessageModel) -> str:
            content = msg.content
            if not content and msg.role == "assistant":
                structured = msg.payload.get("structured_response")
                if isinstance(structured, dict):
                    content = structured.get("text", "")
            return content

        def _reply_id(value: Any) -> int | None:
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
            return None

        def _incoming_reply_of(msg: AgentMessageModel) -> dict[str, Any] | None:
            value = msg.payload.get("reply")
            return value if isinstance(value, dict) else None

        def _outgoing_reply_id_of(msg: AgentMessageModel) -> int | None:
            """Reply target of the agent's answer: the structured response's
            `reply_to`, or the AgentResponse tool call args."""
            found = reply_target_of(msg.payload)
            if found is not None:
                return found
            tool_calls = msg.payload.get("tool_calls")
            if isinstance(tool_calls, list):
                for call in tool_calls:
                    if not isinstance(call, dict):
                        continue
                    args = call.get("args")
                    if isinstance(args, dict):
                        found = _reply_id(args.get("reply_to"))
                        if found is not None:
                            return found
            return None

        # Rows of one turn share payload.turn_id. Tool events are written while
        # the turn runs, i.e. *before* the incoming/response rows are persisted,
        # so time-boundary grouping alone would split a turn apart. Group by
        # turn_id when present; rows without it (legacy data) fall back to
        # sequential grouping.
        by_turn_id: dict[str, ConversationTurn] = {}
        legacy_turns: list[ConversationTurn] = []
        legacy_current: ConversationTurn | None = None

        def _turn_for(turn_id: str, item_id: UUID, timestamp: datetime) -> ConversationTurn:
            turn = by_turn_id.get(turn_id)
            if turn is None:
                turn = ConversationTurn(
                    id=item_id,
                    agent_id=agent_id,
                    timestamp=timestamp,
                    turn_id=turn_id,
                    peer_id="",
                    direction="tools",
                )
                by_turn_id[turn_id] = turn
            elif timestamp < turn.timestamp:
                turn.timestamp = timestamp
            return turn

        oldest_keys: dict[int, tuple[datetime, UUID]] = {}

        def _touch(turn: ConversationTurn, timestamp: datetime, item_id: UUID) -> None:
            """Track the oldest (created_at, id) of a turn for the keyset cursor."""
            key = (timestamp, item_id)
            current = oldest_keys.get(id(turn))
            if current is None or key < current:
                oldest_keys[id(turn)] = key

        for item_type, timestamp, item in timeline:
            payload: dict[str, Any] = item.payload or {}
            turn_id = str(payload.get("turn_id") or "") or None
            if boundary_turn_id is not None and turn_id == boundary_turn_id:
                continue

            if item_type == "msg":
                msg = item
                content = _message_content(msg)
                media = [
                    entry for entry in (msg.payload.get("media") or []) if isinstance(entry, dict)
                ]
                if turn_id is not None:
                    turn = _turn_for(turn_id, msg.id, timestamp)
                    _touch(turn, timestamp, msg.id)
                    if msg.direction in ("incoming", "dashboard_trigger"):
                        if turn.incoming:
                            # Second incoming row in one turn (duplicate save in
                            # legacy data): keep both blocks so nothing is lost,
                            # but the extra block must not reuse the turn id —
                            # duplicated ids make react keys collide and blur the
                            # per-block state of tools/media. Without turn_id the
                            # frontend keys it by its own message id.
                            turn = ConversationTurn(
                                id=msg.id,
                                agent_id=agent_id,
                                timestamp=timestamp,
                                peer_id=str(payload.get("peer", "")),
                                peer_name=str(payload.get("peer_name", "")),
                                agent_name=str(payload.get("agent_name", "")),
                                incoming=content,
                                direction="incoming",
                                turn_id=None,
                                incoming_media=media,
                                incoming_reply=_incoming_reply_of(msg),
                            )
                            _touch(turn, timestamp, msg.id)
                            legacy_turns.append(turn)
                            continue
                        turn.id = msg.id
                        turn.peer_id = str(payload.get("peer", ""))
                        turn.peer_name = str(payload.get("peer_name", ""))
                        turn.agent_name = str(payload.get("agent_name", ""))
                        turn.incoming = content
                        turn.incoming_media = media
                        turn.incoming_reply = _incoming_reply_of(msg)
                        turn.direction = "both" if turn.outgoing else "incoming"
                    elif msg.direction in ("agent_response", "outgoing"):
                        turn.outgoing = content
                        turn.outgoing_reply_id = _outgoing_reply_id_of(msg)
                        if not turn.peer_id:
                            turn.peer_id = str(payload.get("peer", ""))
                            turn.peer_name = str(payload.get("peer_name", ""))
                            turn.agent_name = str(payload.get("agent_name", ""))
                        turn.direction = "both" if turn.incoming else "outgoing"
                    continue

                if msg.direction in ("incoming", "dashboard_trigger"):
                    if legacy_current is not None:
                        legacy_turns.append(legacy_current)
                    legacy_current = ConversationTurn(
                        id=msg.id,
                        agent_id=agent_id,
                        timestamp=msg.created_at,
                        peer_id=str(msg.payload.get("peer", "")),
                        peer_name=str(msg.payload.get("peer_name", "")),
                        agent_name=str(msg.payload.get("agent_name", "")),
                        incoming=content,
                        direction="incoming",
                        incoming_media=media,
                        incoming_reply=_incoming_reply_of(msg),
                    )
                    _touch(legacy_current, msg.created_at, msg.id)
                elif msg.direction in ("agent_response", "outgoing"):
                    if legacy_current is not None and legacy_current.direction == "incoming":
                        legacy_current.outgoing = content
                        legacy_current.outgoing_reply_id = _outgoing_reply_id_of(msg)
                        legacy_current.direction = "both"
                        _touch(legacy_current, msg.created_at, msg.id)
                    else:
                        if legacy_current is not None:
                            legacy_turns.append(legacy_current)
                        legacy_current = ConversationTurn(
                            id=msg.id,
                            agent_id=agent_id,
                            timestamp=msg.created_at,
                            peer_id=str(msg.payload.get("peer", "")),
                            peer_name=str(msg.payload.get("peer_name", "")),
                            agent_name=str(msg.payload.get("agent_name", "")),
                            outgoing=content,
                            direction="outgoing",
                            outgoing_reply_id=_outgoing_reply_id_of(msg),
                        )
                        _touch(legacy_current, msg.created_at, msg.id)
            else:
                evt = item
                duration_ms = 0.0
                if evt.started_at and evt.completed_at:
                    duration_ms = (evt.completed_at - evt.started_at).total_seconds() * 1000
                tool = ToolCallRecord(
                    id=evt.id,
                    name=evt.event_type,
                    status=evt.status,
                    payload=evt.payload or {},
                    result=evt.result,
                    error=evt.error,
                    duration_ms=duration_ms,
                    created_at=evt.created_at,
                )
                if turn_id is not None:
                    turn = _turn_for(turn_id, evt.id, timestamp)
                    turn.tools.append(tool)
                    _touch(turn, timestamp, evt.id)
                    if not turn.peer_id:
                        turn.peer_id = str(payload.get("parent_peer") or payload.get("peer") or "")
                    continue
                # Lifecycle events (start/stop/timer/failure) belong to no turn:
                # they always stay their own block so history matches the
                # realtime feed and nothing is duplicated inside a turn.
                # Legacy tool events (no turn_id, pre-`tool.*` naming) still
                # attach to the turn they ran in.
                is_lifecycle = item.event_type.startswith(("agent.", "timer.", "turn.", "message."))
                if is_lifecycle or legacy_current is None:
                    block = ConversationTurn(
                        id=evt.id,
                        agent_id=agent_id,
                        timestamp=evt.created_at,
                        peer_id=str((evt.payload or {}).get("parent_peer", "")),
                        direction="tools",
                        tools=[tool],
                    )
                    _touch(block, timestamp, evt.id)
                    legacy_turns.append(block)
                else:
                    legacy_current.tools.append(tool)
                    _touch(legacy_current, timestamp, evt.id)

        if legacy_current is not None:
            legacy_turns.append(legacy_current)

        turns = [*by_turn_id.values(), *legacy_turns]
        # Fallback: an answer sent through the send_text_message tool carries
        # the reply target in its args, not in the structured response.
        for turn in turns:
            if turn.outgoing_reply_id is not None:
                continue
            for tool in turn.tools:
                if tool.name != "tool.send_text_message" or tool.status != "succeeded":
                    continue
                args = tool.payload.get("args") if isinstance(tool.payload, dict) else None
                found = _reply_id(args.get("reply_to_msg_id")) if isinstance(args, dict) else None
                if found is not None:
                    turn.outgoing_reply_id = found
                    break
        turns.sort(key=lambda turn: (turn.timestamp, turn.id), reverse=True)
        page = turns[:limit]
        next_before: datetime | None = None
        next_before_id: UUID | None = None
        if len(page) == limit:
            cursor_keys = [oldest_keys[id(turn)] for turn in page if id(turn) in oldest_keys]
            if cursor_keys:
                next_before, next_before_id = min(cursor_keys)
        return ConversationPage(turns=page, next_before=next_before, next_before_id=next_before_id)


def _agent_record(agent: AgentModel) -> AgentRecord:
    # The DB enum carries extra values (e.g. the `draft` default for rows
    # created outside AgentRuntimeState). One unexpected status must not break
    # the whole agent list or the startup restore — treat it as stopped.
    try:
        state = AgentRuntimeState(agent.status)
    except ValueError:
        logger.warning(
            "Agent %s has unsupported status %r, treating it as stopped", agent.id, agent.status
        )
        state = AgentRuntimeState.STOPPED
    return AgentRecord(
        agent_id=agent.id,
        owner_id=agent.owner_id,
        name=agent.name,
        state=state,
        restore_on_start=agent.restore_on_start,
    )


def _now() -> datetime:
    return datetime.now(UTC)
