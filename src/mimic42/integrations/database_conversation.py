from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Text, and_, case, cast, func, literal, or_, select, tuple_, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select

from mimic42.core.agent_store import (
    ConversationPage,
    ConversationTurn,
    ToolCallRecord,
    reply_target_of,
)
from mimic42.integrations.database_models import AgentEventModel, AgentMessageModel

_INCOMING = ("incoming", "dashboard_trigger")
_OUTGOING = ("agent_response", "outgoing")
_LIFECYCLE_PREFIXES = ("agent.", "timer.", "turn.", "message.", "first_comment.", "warmup.")


def _turn_id(payload: Any) -> ColumnElement[str]:
    value = type_coerce(payload, JSONB)["turn_id"]
    return case(
        (value.in_([literal(item, type_=JSONB) for item in (None, False, 0, "", [], {})]), None),
        (value == literal(True, type_=JSONB), "True"),
        else_=value.astext,
    )


def _conversation_statement(
    *, agent_id: UUID, limit: int, before: datetime | None, before_id: UUID | None
) -> Select[Any]:
    messages = (
        select(
            AgentMessageModel.id,
            AgentMessageModel.created_at,
            cast(AgentMessageModel.direction, Text).label("direction"),
            _turn_id(AgentMessageModel.payload).label("turn_id"),
        )
        .where(AgentMessageModel.agent_id == agent_id)
        .cte("message_meta")
    )
    events = (
        select(
            AgentEventModel.id,
            AgentEventModel.created_at,
            AgentEventModel.event_type,
            _turn_id(AgentEventModel.payload).label("turn_id"),
        )
        .where(AgentEventModel.agent_id == agent_id)
        .cte("event_meta")
    )
    incoming = (
        select(
            messages.c.id,
            func.row_number()
            .over(partition_by=messages.c.turn_id, order_by=(messages.c.created_at, messages.c.id))
            .label("incoming_rank"),
        )
        .where(messages.c.turn_id.is_not(None), messages.c.direction.in_(_INCOMING))
        .cte("tagged_incoming")
    )
    duplicate = incoming.c.incoming_rank > 1
    tagged_messages = (
        select(
            case((duplicate, "message"), else_="turn").label("block_kind"),
            case((duplicate, cast(messages.c.id, Text)), else_=messages.c.turn_id).label(
                "block_ref"
            ),
            literal(0).label("source_rank"),
            messages.c.id.label("source_id"),
            messages.c.created_at,
            case((incoming.c.incoming_rank == 1, 0), else_=1).label("id_priority"),
        )
        .select_from(messages.outerjoin(incoming, incoming.c.id == messages.c.id))
        .where(messages.c.turn_id.is_not(None))
    )
    tagged_events = select(
        literal("turn"), events.c.turn_id, literal(1), events.c.id, events.c.created_at, literal(1)
    ).where(events.c.turn_id.is_not(None))

    legacy_previous = (
        select(
            messages,
            func.lag(messages.c.direction)
            .over(order_by=(messages.c.created_at, messages.c.id))
            .label("previous_direction"),
        )
        .where(messages.c.turn_id.is_(None), messages.c.direction.in_((*_INCOMING, *_OUTGOING)))
        .cte("legacy_previous")
    )
    legacy_boundaries = select(
        legacy_previous,
        case(
            (legacy_previous.c.direction.in_(_INCOMING), 1),
            (legacy_previous.c.previous_direction.in_(_INCOMING), 0),
            else_=1,
        ).label("starts_block"),
    ).cte("legacy_boundaries")
    lifecycle = or_(
        *(events.c.event_type.startswith(prefix, autoescape=True) for prefix in _LIFECYCLE_PREFIXES)
    )
    legacy_stream = (
        select(
            legacy_boundaries.c.id,
            legacy_boundaries.c.created_at,
            literal(0).label("source_rank"),
            legacy_boundaries.c.starts_block,
            literal(False).label("lifecycle"),
        )
        .union_all(
            select(events.c.id, events.c.created_at, literal(1), literal(0), lifecycle).where(
                events.c.turn_id.is_(None)
            )
        )
        .cte("legacy_stream")
    )
    stream_order = (
        legacy_stream.c.created_at,
        legacy_stream.c.id,
        legacy_stream.c.source_rank,
    )
    legacy_numbered = select(
        legacy_stream,
        func.sum(legacy_stream.c.starts_block)
        .over(order_by=stream_order, rows=(None, 0))
        .label("segment"),
    ).cte("legacy_numbered")
    legacy_assigned = select(
        legacy_numbered,
        func.first_value(legacy_numbered.c.id)
        .over(
            partition_by=legacy_numbered.c.segment,
            order_by=(
                legacy_numbered.c.created_at,
                legacy_numbered.c.id,
                legacy_numbered.c.source_rank,
            ),
        )
        .label("anchor_id"),
    ).cte("legacy_assigned")
    attached = and_(legacy_assigned.c.segment > 0, ~legacy_assigned.c.lifecycle)
    legacy_members = select(
        case((attached, "legacy"), else_="event"),
        cast(case((attached, legacy_assigned.c.anchor_id), else_=legacy_assigned.c.id), Text),
        legacy_assigned.c.source_rank,
        legacy_assigned.c.id,
        legacy_assigned.c.created_at,
        literal(1),
    )
    members = tagged_messages.union_all(tagged_events, legacy_members).cte("conversation_members")
    block = (members.c.block_kind, members.c.block_ref)
    ranked = select(
        members,
        func.min(members.c.created_at).over(partition_by=block).label("timestamp"),
        func.row_number()
        .over(
            partition_by=block,
            order_by=(
                members.c.id_priority,
                members.c.created_at,
                members.c.source_id,
                members.c.source_rank,
            ),
        )
        .label("public_rank"),
    ).cte("ranked_blocks")
    descriptors = (
        select(
            ranked.c.block_kind,
            ranked.c.block_ref,
            ranked.c.timestamp,
            ranked.c.source_id.label("public_id"),
        )
        .where(ranked.c.public_rank == 1)
        .cte("block_descriptors")
    )
    candidates_query = select(descriptors).order_by(
        descriptors.c.timestamp.desc(), descriptors.c.public_id.desc()
    )
    if before is not None:
        condition = descriptors.c.timestamp < before
        if before_id is not None:
            condition = tuple_(descriptors.c.timestamp, descriptors.c.public_id) < tuple_(
                literal(before), literal(before_id)
            )
        candidates_query = candidates_query.where(condition)
    candidates = candidates_query.limit(limit + 1).cte("block_candidates")
    selected = (
        select(candidates)
        .order_by(candidates.c.timestamp.desc(), candidates.c.public_id.desc())
        .limit(limit)
        .cte("selected_blocks")
    )
    has_more = select(func.count() > limit).select_from(candidates).scalar_subquery()
    return (
        select(selected, has_more.label("has_more"), AgentMessageModel, AgentEventModel)
        .select_from(selected)
        .join(
            members,
            and_(
                members.c.block_kind == selected.c.block_kind,
                members.c.block_ref == selected.c.block_ref,
            ),
        )
        .outerjoin(
            AgentMessageModel,
            and_(
                members.c.source_rank == 0,
                AgentMessageModel.id == members.c.source_id,
                AgentMessageModel.agent_id == agent_id,
            ),
        )
        .outerjoin(
            AgentEventModel,
            and_(
                members.c.source_rank == 1,
                AgentEventModel.id == members.c.source_id,
                AgentEventModel.agent_id == agent_id,
            ),
        )
        .order_by(
            selected.c.timestamp.desc(),
            selected.c.public_id.desc(),
            members.c.created_at,
            members.c.source_id,
            members.c.source_rank,
        )
    )


@dataclass
class _ConversationBlock:
    kind: str
    id: UUID
    timestamp: datetime
    turn_id: str | None
    items: list[AgentMessageModel | AgentEventModel] = field(default_factory=list)


async def load_conversation(
    session: AsyncSession,
    *,
    agent_id: UUID,
    limit: int,
    before: datetime | None,
    before_id: UUID | None,
) -> ConversationPage:
    result = await session.execute(
        _conversation_statement(agent_id=agent_id, limit=limit, before=before, before_id=before_id)
    )
    blocks: dict[tuple[str, str], _ConversationBlock] = {}
    has_more = False
    for kind, ref, timestamp, public_id, more, message, event in result:
        has_more = more
        key = (kind, ref)
        if key not in blocks:
            blocks[key] = _ConversationBlock(
                kind, public_id, timestamp, ref if kind == "turn" else None
            )
        blocks[key].items.append(message if message is not None else event)
    turns = [_render_block(agent_id, block) for block in blocks.values()]
    last = turns[-1] if has_more and turns else None
    return ConversationPage(
        turns=turns,
        next_before=last.timestamp if last is not None else None,
        next_before_id=last.id if last is not None else None,
    )


def stored_structured_text(msg: AgentMessageModel) -> str:
    response = msg.payload.get("structured_response")
    if isinstance(response, dict):
        text = response.get("text", "")
        if isinstance(text, str):
            return text
    return ""


def _reply_id(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _outgoing_reply_id(msg: AgentMessageModel) -> int | None:
    found = reply_target_of(msg.payload)
    if found is not None:
        return found
    calls = msg.payload.get("tool_calls")
    if isinstance(calls, list):
        for call in calls:
            if not isinstance(call, dict):
                continue
            args = call.get("args")
            if isinstance(args, dict):
                found = _reply_id(args.get("reply_to"))
                if found is not None:
                    return found
    return None


def _render_block(agent_id: UUID, block: _ConversationBlock) -> ConversationTurn:
    turn = ConversationTurn(
        id=block.id,
        agent_id=agent_id,
        timestamp=block.timestamp,
        turn_id=block.turn_id,
        peer_id="",
        direction="tools",
    )
    for item in block.items:
        payload = item.payload or {}
        if isinstance(item, AgentMessageModel):
            content = item.content
            if not content.strip() and item.role == "assistant":
                content = stored_structured_text(item)
            if item.direction in _INCOMING:
                turn.peer_id = str(payload.get("peer", ""))
                turn.peer_name = str(payload.get("peer_name", ""))
                turn.agent_name = str(payload.get("agent_name", ""))
                turn.incoming = content
                turn.incoming_media = [
                    entry for entry in (payload.get("media") or []) if isinstance(entry, dict)
                ]
                reply = payload.get("reply")
                turn.incoming_reply = reply if isinstance(reply, dict) else None
                turn.direction = "both" if turn.outgoing else "incoming"
            elif item.direction in _OUTGOING:
                turn.outgoing = content
                turn.outgoing_reply_id = _outgoing_reply_id(item)
                if not turn.peer_id and (block.kind == "turn" or turn.direction == "tools"):
                    turn.peer_id = str(payload.get("peer", ""))
                    turn.peer_name = str(payload.get("peer_name", ""))
                    turn.agent_name = str(payload.get("agent_name", ""))
                has_incoming = (
                    bool(turn.incoming) if block.kind == "turn" else turn.direction == "incoming"
                )
                turn.direction = "both" if has_incoming else "outgoing"
        else:
            duration_ms = 0.0
            if item.started_at and item.completed_at:
                duration_ms = (item.completed_at - item.started_at).total_seconds() * 1000
            turn.tools.append(
                ToolCallRecord(
                    id=item.id,
                    name=item.event_type,
                    status=item.status,
                    payload=payload,
                    result=item.result,
                    error=item.error,
                    duration_ms=duration_ms,
                    created_at=item.created_at,
                )
            )
            if block.kind == "turn" and not turn.peer_id:
                turn.peer_id = str(payload.get("parent_peer") or payload.get("peer") or "")
            elif block.kind == "event":
                turn.peer_id = str(payload.get("parent_peer", ""))
    if turn.outgoing_reply_id is None:
        for tool in turn.tools:
            if tool.name != "tool.send_text_message" or tool.status != "succeeded":
                continue
            args = tool.payload.get("args") if isinstance(tool.payload, dict) else None
            found = _reply_id(args.get("reply_to_msg_id")) if isinstance(args, dict) else None
            if found is not None:
                turn.outgoing_reply_id = found
                break
    return turn
