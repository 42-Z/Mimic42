from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID, uuid4

from telethon import types

from mimic42.core.agent_runtime import _process_media_and_text
from mimic42.core.media import MediaFile


class FakeClient:
    async def download_media(self, message: object, file: object = None, **kwargs: object) -> bytes:
        return b"JPEGDATA"


class FakeUploader:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes, str, str]] = []

    async def upload(
        self,
        *,
        agent_id: UUID,
        filename: str,
        data: bytes,
        mime_type: str,
        kind: str = "doc",
    ) -> MediaFile | None:
        self.uploads.append((filename, data, mime_type, kind))
        return MediaFile(
            kind=kind,
            name=filename,
            mime_type=mime_type,
            size=len(data),
            storage_path=f"{agent_id}/u1/{filename}",
        )

    async def open(self, path: str) -> bytes | None:
        return None

    async def remove_prefix(self, agent_id: UUID) -> None:
        return None


def _photo_event() -> MagicMock:
    photo = MagicMock(spec=types.Photo)
    photo.id = 123
    photo.access_hash = 456
    photo.file_reference = b"\x01\x02"
    photo.dc_id = 2

    media = MagicMock(spec=types.MessageMediaPhoto)
    media.photo = photo

    message = MagicMock(spec=types.Message)
    message.media = media

    event = MagicMock()
    event.client = FakeClient()
    event.message = message
    return event


async def test_photo_message_uploads_and_returns_media() -> None:
    uploader = FakeUploader()
    agent_id = uuid4()

    text, media = await _process_media_and_text(
        _photo_event(), "", media_uploader=uploader, agent_id=agent_id
    )

    assert text.startswith("[Фото id=")
    assert len(media) == 1
    assert media[0].kind == "photo"
    assert media[0].storage_path == f"{agent_id}/u1/photo.jpeg"
    assert uploader.uploads == [("photo.jpeg", b"JPEGDATA", "image/jpeg", "photo")]


async def test_no_uploader_keeps_text_marker_without_media() -> None:
    text, media = await _process_media_and_text(_photo_event(), "подпись", media_uploader=None)

    assert text.startswith("[Фото id=")
    assert text.endswith("подпись")
    assert media == []


async def test_no_media_message_is_passthrough() -> None:
    event = MagicMock()
    event.message = None

    text, media = await _process_media_and_text(event, "просто текст")

    assert text == "просто текст"
    assert media == []
