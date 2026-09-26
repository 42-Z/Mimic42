from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from mimic42.core.media import MAX_MEDIA_BYTES, MediaFile, safe_filename

if TYPE_CHECKING:
    from storage3 import SyncStorageClient

logger = logging.getLogger("mimic42.media")

__all__ = ["BUCKET", "MAX_MEDIA_BYTES", "SupabaseMediaStorage", "storage_client"]

BUCKET = "agent-media"
_LIST_PAGE = 1000
_REMOVE_CHUNK = 1000
_MAX_DEPTH = 8


def storage_client(supabase_url: str, service_key: str) -> SyncStorageClient:
    """Клиент Supabase Storage с service-ключом.

    Без своего HTTP-клиента supabase-py сам передаёт в storage3 устаревшие
    timeout и verify, а тот отвечает DeprecationWarning. Под -W error это
    исключение, и приложение молча оставалось без хранилища. storage3 просит
    настраивать таймаут на HTTP-клиенте — так и делаем, с прежним значением.
    """
    import httpx
    from supabase.lib.client_options import DEFAULT_STORAGE_CLIENT_TIMEOUT

    from supabase import ClientOptions, create_client

    http_client = httpx.Client(
        timeout=DEFAULT_STORAGE_CLIENT_TIMEOUT, follow_redirects=True, http2=True
    )
    options = ClientOptions(httpx_client=http_client)
    return create_client(supabase_url, service_key, options=options).storage


class SupabaseMediaStorage:
    """Media files for the activity feed in a private Supabase Storage bucket.

    All access goes through the backend with the service role key; the bucket
    has no anon/authenticated policies, so the dashboard can only read files
    via the media API endpoint. supabase-py is synchronous — every call is
    wrapped in asyncio.to_thread so the event loop never blocks.
    """

    def __init__(self, *, supabase_url: str, service_key: str) -> None:
        self._storage = storage_client(supabase_url, service_key)

    def close(self) -> None:
        """Закрыть соединения с Storage: HTTP-клиент создан здесь, другим он не нужен."""
        self._storage.session.close()

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
        safe_name = safe_filename(filename)
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

    async def _list_folder(self, prefix: str) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        offset = 0
        while True:
            page: list[dict[str, Any]] = await asyncio.to_thread(
                lambda current=offset: self._bucket().list(
                    prefix, {"limit": _LIST_PAGE, "offset": current}
                )
            )
            batch = list(page or [])
            entries.extend(batch)
            if len(batch) < _LIST_PAGE:
                return entries
            offset += len(batch)

    async def _collect_files(self, prefix: str, depth: int) -> list[str]:
        """Walk the folder tree: storage list() returns one level at a time and
        folders have ``id is None``; remove() deletes exact object paths only."""
        if depth > _MAX_DEPTH:
            logger.warning("Media listing depth limit reached at %s", prefix)
            return []
        paths: list[str] = []
        for entry in await self._list_folder(prefix):
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                continue
            path = f"{prefix}/{name}"
            if entry.get("id") is None:
                paths.extend(await self._collect_files(path, depth + 1))
            else:
                paths.append(path)
        return paths

    async def remove_prefix(self, agent_id: UUID) -> None:
        try:
            files = await self._collect_files(str(agent_id), depth=0)
            for start in range(0, len(files), _REMOVE_CHUNK):
                chunk = files[start : start + _REMOVE_CHUNK]
                await asyncio.to_thread(lambda paths=chunk: self._bucket().remove(paths))
        except Exception:
            logger.warning("Failed to clean media for agent %s", agent_id, exc_info=True)
