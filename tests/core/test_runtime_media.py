from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID, uuid4

from telethon import types

from mimic42.core.agent_runtime import _process_media_and_text
from mimic42.core.media import MAX_MEDIA_BYTES, MediaFile


class FakeClient:
    async def download_media(self, message: object, file: object = None, **kwargs: object) -> bytes:
        # Telethon: with `file=bytes` returns the data, with a stream writes to it.
        data = b"JPEGDATA"
        write = getattr(file, "write", None)
        if callable(write):
            write(data)
            return data
        return data


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


def _doc_event(size: int, client: object | None = None) -> MagicMock:
    filename_attr = MagicMock(spec=types.DocumentAttributeFilename)
    filename_attr.file_name = "notes.txt"

    doc = MagicMock(spec=types.Document)
    doc.id = 1
    doc.access_hash = 2
    doc.file_reference = b"\x01"
    doc.dc_id = 2
    doc.mime_type = "text/plain"
    doc.size = size
    doc.attributes = [filename_attr]

    media = MagicMock(spec=types.MessageMediaDocument)
    media.document = doc

    message = MagicMock(spec=types.Message)
    message.media = media
    message.document = doc

    event = MagicMock()
    event.client = client or FakeClient()
    event.message = message
    return event


def _sticker_event(mime_type: str) -> MagicMock:
    sticker_attr = MagicMock(spec=types.DocumentAttributeSticker)
    sticker_attr.alt = "🙂"
    sticker_attr.stickerset = None

    doc = MagicMock(spec=types.Document)
    doc.id = 7
    doc.access_hash = 8
    doc.file_reference = b"\x01"
    doc.dc_id = 2
    doc.mime_type = mime_type
    doc.size = 10
    doc.attributes = [sticker_attr]

    media = MagicMock(spec=types.MessageMediaDocument)
    media.document = doc

    message = MagicMock(spec=types.Message)
    message.media = media
    message.document = doc

    event = MagicMock()
    event.client = FakeClient()
    event.message = message
    return event


class CountingClient(FakeClient):
    def __init__(self) -> None:
        self.downloads = 0

    async def download_media(self, message: object, file: object = None, **kwargs: object) -> bytes:
        self.downloads += 1
        return await super().download_media(message, file, **kwargs)


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


async def test_small_document_is_read_and_archived() -> None:
    uploader = FakeUploader()
    agent_id = uuid4()

    text, media = await _process_media_and_text(
        _doc_event(10), "", media_uploader=uploader, agent_id=agent_id
    )

    assert "содержимое" in text
    assert len(media) == 1
    assert uploader.uploads == [("notes.txt", b"JPEGDATA", "text/plain", "doc")]


async def test_oversized_document_is_not_downloaded() -> None:
    """Кап размера — до скачивания в память, а не только в ветке «нельзя
    открыть»: огромный txt иначе тянется целиком в память и в LLM."""
    client = CountingClient()
    uploader = FakeUploader()
    agent_id = uuid4()

    text, media = await _process_media_and_text(
        _doc_event(MAX_MEDIA_BYTES + 1, client=client),
        "",
        media_uploader=uploader,
        agent_id=agent_id,
    )

    assert "слишком большой" in text
    assert media == []
    assert uploader.uploads == []
    assert client.downloads == 0


async def test_animated_sticker_keeps_its_real_mime() -> None:
    """Анимированный стикер — не webp: битый mime не открывается в ленте."""
    uploader = FakeUploader()
    agent_id = uuid4()

    text, media = await _process_media_and_text(
        _sticker_event("application/x-tgsticker"),
        "",
        media_uploader=uploader,
        agent_id=agent_id,
    )

    assert text.startswith("[Стикер")
    assert uploader.uploads == [("sticker.tgs", b"JPEGDATA", "application/x-tgsticker", "sticker")]
