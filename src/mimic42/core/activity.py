from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.media_download import MediaRef
from mimic42.integrations.database_models import AgentEventModel

logger = logging.getLogger("mimic42.activity")

MAX_JSON_CHARS = 4000
MAX_ITEM_CHARS = 400
PREVIEW_CHARS = 500


def _media_reference_items(items: Any) -> list[dict[str, Any]]:
    """Retain durable coordinates, never the text or bytes of a tool result."""
    if not isinstance(items, list):
        return []
    references = []
    for item in items:
        if not isinstance(item, dict):
            continue
        media = item.get("media")
        if isinstance(media, dict) and isinstance(media.get("media_id"), str):
            references.append(
                {
                    "media": {
                        "media_id": media["media_id"],
                        **MediaRef.from_payload(media).as_payload(),
                    }
                }
            )
        elif item.get("type") == "media_ref":
            references.append(
                {
                    **MediaRef.from_payload(item).as_payload(),
                    **{
                        key: item[key]
                        for key in ("type", "kind", "name", "size", "media_id")
                        if key in item
                    },
                }
            )
    return references


def _truncate(value: Any) -> dict[str, Any]:
    """Fit an arbitrary JSON value into the payload/result column.

    Large tool outputs (get_messages, get_dialogs) must not bloat the
    activity log. For oversized dicts the small top-level keys are kept —
    they carry turn correlation and error identity (turn_id, peer,
    error_code, success, error) — while each oversized value collapses to
    a marker. Non-dict values collapse to a short preview. Compact media
    references are exempt from the text budget: truncating them would lose
    access to attachments after a restart.
    """
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        serialized = str(value)
    if len(serialized) <= MAX_JSON_CHARS:
        if isinstance(value, dict):
            return value
        return {"value": value}

    if not isinstance(value, dict):
        return {"_truncated": True, "preview": serialized[:PREVIEW_CHARS]}

    kept: dict[str, Any] = {}
    for key, item in value.items():
        try:
            item_json = json.dumps(item, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            item_json = str(item)
        if len(item_json) <= MAX_ITEM_CHARS:
            kept[key] = item
        else:
            kept[key] = {"_truncated": True}
    kept["_truncated"] = True

    if len(json.dumps(kept, ensure_ascii=False, default=str)) > MAX_JSON_CHARS:
        kept = {"_truncated": True, "preview": serialized[:PREVIEW_CHARS]}
    media_items = _media_reference_items(value.get("items"))
    if media_items:
        kept["items"] = media_items
    return kept


class ActivityRecorder:
    """Writes typed agent events to ``agent_events``.

    The recorder must never break an agent turn: every write runs in its
    own session and every failure is downgraded to a warning.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(
        self,
        *,
        agent_id: UUID,
        event_type: str,
        status: str,
        payload: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        try:
            event = AgentEventModel(
                agent_id=agent_id,
                event_type=event_type,
                status=status,
                payload=_truncate(payload if payload is not None else {}),
                result=_truncate(result) if result is not None else None,
                error=error,
                started_at=started_at,
                completed_at=completed_at,
            )
            async with self._session_factory() as db_session:
                db_session.add(event)
                await db_session.commit()
        except Exception:
            logger.warning(
                "Failed to record activity event %s for agent %s",
                event_type,
                agent_id,
                exc_info=True,
            )
