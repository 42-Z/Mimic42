from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID, uuid4

from mimic42.core.media import MediaFile

logger = logging.getLogger("mimic42.media")

MAX_MEDIA_BYTES = 20 * 1024 * 1024
BUCKET = "agent-media"


class SupabaseMediaStorage:
    """Media files for the activity feed in a private Supabase Storage bucket.

    All access goes through the backend with the service role key; the bucket
    has no anon/authenticated policies, so the dashboard can only read files
    via the media API endpoint. supabase-py is synchronous — every call is
    wrapped in asyncio.to_thread so the event loop never blocks.
    """

    def __init__(self, *, supabase_url: str, service_key: str) -> None:
        from supabase import create_client

        self._storage = create_client(supabase_url, service_key).storage

    def _bucket(self) -> Any:
        return self._storage.from_(BUCKET)

    async def upload(
        self,
        *,
        agent_id: UUID,
        filename: str,
        data: bytes,
        mime_type: str,
        kind: str = "doc",
    ) -> MediaFile | None:
        if not data:
            return None
        if len(data) > MAX_MEDIA_BYTES:
            logger.warning("Media %s too large (%d bytes), skipping", filename, len(data))
            return None
        safe_name = filename.replace("/", "_") or "file"
        path = f"{agent_id}/{uuid4()}/{safe_name}"
        try:
            await asyncio.to_thread(
                lambda: self._bucket().upload(
                    file=data,
                    path=path,
                    file_options={"content-type": mime_type, "upsert": "false"},
                )
            )
        except Exception:
            logger.warning("Failed to upload media %s", path, exc_info=True)
            return None
        return MediaFile(
            kind=kind, name=safe_name, mime_type=mime_type, size=len(data), storage_path=path
        )

    async def open(self, path: str) -> bytes | None:
        try:
            blob = await asyncio.to_thread(lambda: self._bucket().download(path))
        except Exception:
            logger.warning("Failed to download media %s", path, exc_info=True)
            return None
        return bytes(blob) if isinstance(blob, (bytes, bytearray)) else None

    async def remove_prefix(self, agent_id: UUID) -> None:
        try:
            items = await asyncio.to_thread(lambda: self._bucket().list(str(agent_id)))
            paths = [f"{agent_id}/{item['name']}" for item in items if item.get("name")]
            if paths:
                await asyncio.to_thread(lambda: self._bucket().remove(paths))
        except Exception:
            logger.warning("Failed to clean media for agent %s", agent_id, exc_info=True)
