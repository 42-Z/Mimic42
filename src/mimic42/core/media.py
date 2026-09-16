from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

MAX_MEDIA_BYTES = 20 * 1024 * 1024


@dataclass(slots=True)
class MediaFile:
    """Metadata of one archived media item (Telegram attachment or tool view)."""

    kind: str  # photo | sticker | voice | round | doc
    name: str
    mime_type: str
    size: int
    storage_path: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "mime_type": self.mime_type,
            "size": self.size,
            "storage_path": self.storage_path,
        }


class MediaUploader(Protocol):
    async def upload(
        self,
        *,
        agent_id: UUID,
        filename: str,
        data: bytes,
        mime_type: str,
        kind: str = "doc",
    ) -> MediaFile | None: ...

    async def open(self, path: str) -> bytes | None: ...

    async def remove_prefix(self, agent_id: UUID) -> None: ...
