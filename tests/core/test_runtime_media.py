from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from telethon import types

from mimic42.core.agent_runtime import _process_media_and_text
from mimic42.core.media import MAX_MEDIA_BYTES, MediaFile
from mimic42.core.media_download import MediaRefCache


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


async def test_archived_photo_payload_keeps_telegram_identity() -> None:
    event = _photo_event_with(FakeClient())
    _, media = await _process_media_and_text(
        event, "", media_uploader=FakeUploader(), agent_id=uuid4()
    )

    payload = media[0].as_payload()
    assert payload["media_id"] == "photo:123:456:0102:2"
    assert payload["peer"] == -100500
    assert payload["message_id"] == 55


async def test_no_uploader_keeps_text_marker_and_media_coordinates() -> None:
    text, media = await _process_media_and_text(_photo_event(), "подпись", media_uploader=None)

    assert text.startswith("[Фото id=")
    assert text.endswith("подпись")
    assert len(media) == 1 and media[0].storage_path is None
    assert media[0].media_id == "photo:123:456:0102:2"


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


async def test_incoming_document_preserves_mime_for_archived_resend() -> None:
    refs = MediaRefCache()
    await _process_media_and_text(
        _doc_event(10), "", media_uploader=FakeUploader(), agent_id=uuid4(), media_refs=refs
    )

    ref = refs.lookup("doc:1:2:01:2:notes.txt")
    assert ref is not None and ref.storage_path is not None
    assert ref.mime_type == "text/plain"


async def test_incoming_voice_keeps_original_telegram_duration_and_waveform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mimic42.config.Settings", lambda: SimpleNamespace(openrouter_api_key=""))
    event = _doc_event(10)
    original = types.DocumentAttributeAudio(duration=25, voice=True, waveform=b"\x10")
    event.message.document.attributes = [original]
    event.message.document.mime_type = "audio/ogg"
    refs = MediaRefCache()

    await _process_media_and_text(event, "", media_refs=refs)

    ref = refs.lookup("voice:1:2:01:2")
    assert ref is not None and ref.attributes == (original,)
    assert ref.mime_type == "audio/ogg"


@pytest.mark.parametrize(("kind", "mime"), [("voice", "audio/ogg"), ("round", "video/mp4")])
async def test_incoming_notes_archive_even_without_transcription_key(
    monkeypatch: pytest.MonkeyPatch, kind: str, mime: str
) -> None:
    monkeypatch.setattr("mimic42.config.Settings", lambda: SimpleNamespace(openrouter_api_key=""))
    event = _doc_event(10)
    event.message.document.attributes = [
        types.DocumentAttributeAudio(duration=25, voice=True)
        if kind == "voice"
        else types.DocumentAttributeVideo(duration=25, w=240, h=240, round_message=True)
    ]
    event.message.document.mime_type = mime
    uploader = FakeUploader()

    text, media = await _process_media_and_text(
        event, "", media_uploader=uploader, agent_id=uuid4()
    )

    assert "OPENROUTER_API_KEY" in text
    assert len(media) == 1 and media[0].kind == kind
    assert uploader.uploads[0][2:] == (mime, kind)
    payload = media[0].as_payload()
    assert payload["media_id"] == f"{kind}:1:2:01:2"
    assert payload["mime_type"] == mime
    assert payload["attributes"][0]["duration"] == 25


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
    assert len(media) == 1 and media[0].storage_path is None
    assert media[0].media_id == "doc:1:2:01:2:notes.txt"
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


class ExpiringClient(FakeClient):
    """Свежая копия сообщения скачивается, исходная — падает с протухшей ссылкой."""

    def __init__(self, fresh: object | None = None) -> None:
        self.fresh = fresh
        self.downloads = 0

    async def download_media(self, message: object, file: object = None, **kwargs: object) -> bytes:
        self.downloads += 1
        if self.fresh is None or message is not getattr(self.fresh, "media", None):
            from telethon import errors

            raise errors.FileReferenceExpiredError(type("Request", (), {})())
        return await super().download_media(message, file, **kwargs)

    async def get_messages(self, chat: object, ids: int) -> object:
        self.refetched = (chat, ids)
        return self.fresh


def _photo_event_with(client: object) -> MagicMock:
    event = _photo_event()
    event.client = client
    event.chat_id = -100500
    event.message.id = 55
    return event


async def test_undownloadable_photo_keeps_a_graceful_marker() -> None:
    """Не скачиваемая картинка не должна терять сообщение: остаётся маркер с
    причиной, без сырых английских ошибок (issue #98: бот верификации шлёт
    картинку, которую нельзя скачать повторно)."""
    uploader = FakeUploader()

    text, media = await _process_media_and_text(
        _photo_event_with(ExpiringClient()),
        "",
        media_uploader=uploader,
        agent_id=uuid4(),
        media_refs=MediaRefCache(),
    )

    assert text.startswith("[Фото (недоступно")
    assert "GetFileRequest" not in text
    assert len(media) == 1 and media[0].storage_path is None
    assert media[0].as_payload()["peer"] == -100500
    assert media[0].as_payload()["message_id"] == 55
    assert uploader.uploads == []


async def test_archiving_failure_does_not_lose_downloaded_photo() -> None:
    class FailingUploader(FakeUploader):
        async def upload(
            self, *, agent_id: UUID, filename: str, data: bytes, mime_type: str, kind: str = "doc"
        ) -> MediaFile | None:
            raise ConnectionError("storage offline")

    text, media = await _process_media_and_text(
        _photo_event_with(FakeClient()),
        "подпись",
        media_uploader=FailingUploader(),
        agent_id=uuid4(),
    )

    assert "[Фото id=" in text
    assert "подпись" in text
    assert len(media) == 1 and media[0].storage_path is None
    assert media[0].as_payload()["peer"] == -100500
    assert media[0].as_payload()["message_id"] == 55


async def test_unexpected_media_error_keeps_the_message() -> None:
    """Непредвиденная ошибка скачивания тоже не теряет медиа молча:
    остаётся маркер, сырая ошибка не уходит в текст."""

    class BrokenClient(FakeClient):
        async def download_media(
            self, message: object, file: object = None, **kwargs: object
        ) -> bytes:
            raise RuntimeError("boom (caused by GetFileRequest)")

    text, media = await _process_media_and_text(
        _photo_event_with(BrokenClient()),
        "подпись",
        media_uploader=None,
        media_refs=MediaRefCache(),
    )

    assert "Фото" in text
    assert "подпись" in text
    assert "GetFileRequest" not in text


async def test_media_marker_survives_a_broken_media_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ошибка подготовки media_id не теряет сообщение без подписи:
    остаётся общий маркер, иначе _format_incoming выбросит ход целиком."""

    def boom(msg: object) -> str:
        raise RuntimeError("broken media object")

    monkeypatch.setattr("mimic42.integrations.telegram_tools.format_media_object", boom)

    text, media = await _process_media_and_text(
        _photo_event_with(FakeClient()), "", media_refs=MediaRefCache()
    )

    assert text
    assert "Медиа" in text
    assert "broken media object" not in text
    assert media == []


async def test_incoming_photo_retries_after_refetching_the_message() -> None:
    """Протухшую ссылку чиним перечитыванием сообщения, а не отбрасыванием."""
    fresh = MagicMock(spec=types.Message)
    fresh.media = _photo_event().message.media
    client = ExpiringClient(fresh=fresh)
    uploader = FakeUploader()
    cache = MediaRefCache()

    text, media = await _process_media_and_text(
        _photo_event_with(client),
        "",
        media_uploader=uploader,
        agent_id=uuid4(),
        media_refs=cache,
    )

    assert text.startswith("[Фото id=")
    assert client.downloads == 2
    assert client.refetched == (-100500, 55)
    assert len(media) == 1
    ref = cache.lookup("photo:123:456:0102:2")
    assert ref is not None and ref.download_source is fresh


async def test_photo_media_id_is_registered_for_view_image() -> None:
    """Ссылка на заархивированную копию и сообщение запоминаются, чтобы
    view_image не качал самоуничтожившееся медиа повторно."""
    cache = MediaRefCache()
    uploader = FakeUploader()
    agent_id = uuid4()

    text, _media = await _process_media_and_text(
        _photo_event_with(FakeClient()),
        "",
        media_uploader=uploader,
        agent_id=agent_id,
        media_refs=cache,
    )

    media_id = text[len("[Фото id=") : text.index("]")]
    ref = cache.lookup(media_id)
    assert ref is not None
    assert ref.storage_path == f"{agent_id}/u1/photo.jpeg"
    assert ref.peer == -100500
    assert ref.message_id == 55
