from __future__ import annotations

from datetime import UTC
from io import BytesIO
from typing import Any

import pytest
from telethon import errors, types

from mimic42.core.media_download import (
    MediaRef,
    MediaRefCache,
    MediaUnavailableError,
    download_media_with_refresh,
    normalize_peer_ref,
)


def _expired(request: object = None) -> Exception:
    return errors.FileReferenceExpiredError(request or type("Request", (), {})())


def _photo_message(media_id: int = 123) -> Any:
    from datetime import datetime

    photo = types.Photo(
        id=media_id,
        access_hash=456,
        file_reference=b"\x01\x02",
        date=datetime.now(UTC),
        sizes=[types.PhotoSize(type="x", w=0, h=0, size=0)],
        dc_id=2,
    )
    return types.Message(
        id=55,
        peer_id=types.PeerChannel(100500),
        message="",
        out=False,
        date=datetime.now(UTC),
        media=types.MessageMediaPhoto(photo=photo),
    )


class ExpiringClient:
    """Свежее сообщение скачивается, старое — падает с протухшей ссылкой."""

    def __init__(self, fresh: Any) -> None:
        self.fresh = fresh
        self.downloads: list[Any] = []
        self.get_messages_calls: list[tuple[Any, int]] = []

    async def download_media(self, message: Any, file: Any = None, **kwargs: Any) -> Any:
        self.downloads.append(message)
        if message is not self.fresh:
            raise _expired()
        return b"JPEGDATA"

    async def get_messages(self, chat: Any, ids: int) -> Any:
        self.get_messages_calls.append((chat, ids))
        return self.fresh


async def test_expired_reference_without_message_ref_raises_media_unavailable() -> None:
    client = ExpiringClient(fresh=None)

    with pytest.raises(MediaUnavailableError) as exc_info:
        await download_media_with_refresh(client, "stale-media")

    assert "недоступно" in str(exc_info.value)
    assert client.get_messages_calls == []


async def test_expired_reference_refetches_message_and_retries() -> None:
    fresh = _photo_message()
    client = ExpiringClient(fresh=fresh)

    data = await download_media_with_refresh(client, "stale-media", message_ref=(-100500, 55))

    assert data == b"JPEGDATA"
    assert client.get_messages_calls == [(-100500, 55)]
    assert client.downloads == ["stale-media", fresh]


async def test_media_unavailable_when_refetched_message_also_fails() -> None:
    fresh = _photo_message()

    class StillExpiringClient(ExpiringClient):
        async def download_media(self, message: Any, file: Any = None, **kwargs: Any) -> Any:
            self.downloads.append(message)
            raise _expired()

    client = StillExpiringClient(fresh=fresh)

    with pytest.raises(MediaUnavailableError):
        await download_media_with_refresh(client, "stale-media", message_ref=(-100500, 55))


async def test_media_unavailable_when_message_is_gone() -> None:
    fresh = _photo_message()

    class DeletedMessageClient(ExpiringClient):
        async def get_messages(self, chat: Any, ids: int) -> Any:
            self.get_messages_calls.append((chat, ids))
            return None

    client = DeletedMessageClient(fresh=fresh)

    with pytest.raises(MediaUnavailableError):
        await download_media_with_refresh(client, "stale-media", message_ref=(-100500, 55))

    assert len(client.downloads) == 1


def test_media_ref_cache_remembers_and_evicts() -> None:
    cache = MediaRefCache(capacity=2)
    cache.remember("photo:1:1:01:2", MediaRef(peer="-100500", message_id=1, storage_path="a"))
    cache.remember("photo:2:1:01:2", MediaRef(peer="-100500", message_id=2, storage_path="b"))
    cache.remember("photo:3:1:01:2", MediaRef(peer="-100500", message_id=3, storage_path="c"))

    assert cache.lookup("photo:3:1:01:2") == MediaRef(
        peer="-100500", message_id=3, storage_path="c"
    )
    assert cache.lookup("photo:1:1:01:2") is None


def test_media_ref_cache_merges_reregistrations() -> None:
    """Повторная регистрация media_id не должна терять уже известное:
    путь архива — при перечитывании истории, сообщение — при архивации."""
    cache = MediaRefCache()
    cache.remember("photo:1:1:01:2", MediaRef(peer="-100500", message_id=1, storage_path="a"))

    cache.remember("photo:1:1:01:2", MediaRef(peer="-100500", message_id=2))
    assert cache.lookup("photo:1:1:01:2") == MediaRef(
        peer="-100500", message_id=2, storage_path="a"
    )

    cache.remember("photo:1:1:01:2", MediaRef(storage_path="b"))
    assert cache.lookup("photo:1:1:01:2") == MediaRef(
        peer="-100500", message_id=2, storage_path="b"
    )


def test_media_ref_cache_prefers_archived_entries_when_evicting() -> None:
    cache = MediaRefCache(capacity=2)
    cache.remember("archived", MediaRef(storage_path="saved"))
    cache.remember("recoverable", MediaRef(peer="chat", message_id=1))
    cache.remember("new", MediaRef(peer="chat", message_id=2))

    assert cache.lookup("archived") == MediaRef(storage_path="saved")
    assert cache.lookup("recoverable") is None


def test_media_ref_cache_never_discards_the_new_reference_on_insert() -> None:
    cache = MediaRefCache(capacity=2)
    cache.remember("archived-old", MediaRef(storage_path="old"))
    cache.remember("archived-recent", MediaRef(storage_path="recent"))
    cache.remember("new", MediaRef(peer="chat", message_id=3))

    assert cache.lookup("new") == MediaRef(peer="chat", message_id=3)
    assert cache.lookup("archived-old") is None
    assert cache.lookup("archived-recent") == MediaRef(storage_path="recent")


def test_media_ref_cache_retains_original_document_metadata_on_reregistration() -> None:
    cache = MediaRefCache()
    attrs = (types.DocumentAttributeAudio(duration=22, voice=True),)
    cache.remember(
        "voice:123",
        MediaRef(storage_path="saved/voice.ogg", mime_type="audio/ogg", attributes=attrs),
    )
    cache.remember("voice:123", MediaRef(peer="chat", message_id=55))

    assert cache.lookup("voice:123") == MediaRef(
        peer="chat",
        message_id=55,
        storage_path="saved/voice.ogg",
        mime_type="audio/ogg",
        attributes=attrs,
    )


def test_normalize_peer_ref_handles_username_suffix_and_spaces() -> None:
    assert normalize_peer_ref("  username#123  ") == 123
    assert normalize_peer_ref("  @username  ") == "@username"


def test_media_ref_cache_keeps_peer_and_message_id_together() -> None:
    cache = MediaRefCache()
    cache.remember("photo", MediaRef(peer="original", message_id=1))
    cache.remember("photo", MediaRef(peer="other"))
    assert cache.lookup("photo") == MediaRef(peer="original", message_id=1)


async def test_refresh_rejects_a_replaced_attachment() -> None:
    """Перечитанное сообщение могли отредактировать: медиа с другим id под
    старый media_id не подсовываем (как и сам Telethon при обновлении)."""
    client = ExpiringClient(fresh=_photo_message(media_id=999))

    with pytest.raises(MediaUnavailableError):
        await download_media_with_refresh(
            client, _photo_message(media_id=123), message_ref=(-100500, 55)
        )

    assert len(client.downloads) == 1


async def test_refresh_rejects_document_with_the_same_id_as_original_photo() -> None:
    from datetime import datetime

    document = types.Document(
        id=123,
        access_hash=456,
        file_reference=b"\x03",
        date=datetime.now(UTC),
        mime_type="application/pdf",
        size=10,
        dc_id=2,
        attributes=[],
    )
    fresh = types.Message(
        id=55,
        peer_id=types.PeerChannel(100500),
        message="",
        out=False,
        date=datetime.now(UTC),
        media=types.MessageMediaDocument(document=document),
    )
    client = ExpiringClient(fresh)

    with pytest.raises(MediaUnavailableError):
        await download_media_with_refresh(client, _photo_message(123), message_ref=("chat", 55))

    assert len(client.downloads) == 1


async def test_refresh_accepts_photo_restored_from_media_id() -> None:
    fresh = _photo_message(123)
    client = ExpiringClient(fresh)
    stale_photo = _photo_message(123).media.photo

    assert (
        await download_media_with_refresh(client, stale_photo, message_ref=("chat", 55))
        == b"JPEGDATA"
    )
    assert client.get_messages_calls == [("chat", 55)]


async def test_refresh_accepts_input_photo_of_same_identity() -> None:
    fresh = _photo_message(123)
    client = ExpiringClient(fresh)
    input_photo = types.InputPhoto(id=123, access_hash=456, file_reference=b"\x01\x02")

    assert (
        await download_media_with_refresh(client, input_photo, message_ref=("chat", 55))
        == b"JPEGDATA"
    )


@pytest.mark.parametrize(
    "error_type",
    [
        errors.FileReferenceInvalidError,
        errors.FileReferenceEmptyError,
        errors.FilerefUpgradeNeededError,
        errors.MediaEmptyError,
    ],
)
async def test_other_missing_media_errors_are_unavailable(
    error_type: type[Exception],
) -> None:
    """Telegram может сообщать об одной потере файла несколькими кодами."""

    class EmptyMediaClient(ExpiringClient):
        async def download_media(self, message: Any, file: Any = None, **kwargs: Any) -> Any:
            self.downloads.append(message)
            raise error_type(type("Request", (), {})())

    client = EmptyMediaClient(fresh=None)

    with pytest.raises(MediaUnavailableError):
        await download_media_with_refresh(client, "gone-media")


async def test_retry_rewinds_a_dirty_stream() -> None:
    """Первая попытка могла записать в поток мусор — повторная пишет начисто."""
    from io import BytesIO

    class DirtyFirstClient:
        def __init__(self, fresh: Any) -> None:
            self.fresh = fresh
            self.calls = 0

        async def download_media(self, message: Any, file: Any = None, **kwargs: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                file.write(b"GARBAGE")
                raise errors.FileReferenceExpiredError(type("Request", (), {})())
            file.write(b"CLEANDATA")
            return b"CLEANDATA"

        async def get_messages(self, chat: Any, ids: int) -> Any:
            return self.fresh

    buffer = BytesIO()
    await download_media_with_refresh(
        DirtyFirstClient(_photo_message()),
        "stale-media",
        message_ref=(-100500, 55),
        file=buffer,
    )

    assert buffer.getvalue() == b"CLEANDATA"


async def test_retry_with_non_seekable_stream_reports_stream_error() -> None:
    class NonSeekable(BytesIO):
        def seek(self, *args: Any, **kwargs: Any) -> Any:
            raise OSError("not seekable")

    class StillExpired(ExpiringClient):
        async def download_media(self, message: Any, file: Any = None, **kwargs: Any) -> Any:
            raise _expired()

    with pytest.raises(OSError, match="поток"):
        await download_media_with_refresh(
            StillExpired(_photo_message()),
            _photo_message(),
            message_ref=("chat", 55),
            file=NonSeekable(),
        )


async def test_retry_refuses_a_stream_without_seek_and_truncate() -> None:
    class WriteOnly:
        def write(self, value: bytes) -> None:
            self.data = value

    with pytest.raises(OSError, match="seek и truncate"):
        await download_media_with_refresh(
            ExpiringClient(_photo_message()),
            _photo_message(),
            message_ref=("chat", 55),
            file=WriteOnly(),
        )


async def test_network_failure_during_refetch_is_not_reported_as_media_loss() -> None:
    class NetworkFailure(ExpiringClient):
        async def get_messages(self, chat: Any, ids: int) -> Any:
            raise ConnectionError("network offline")

    with pytest.raises(ConnectionError, match="network offline"):
        await download_media_with_refresh(
            NetworkFailure(_photo_message()), _photo_message(), message_ref=("chat", 55)
        )


async def test_flood_wait_during_refetch_is_not_reported_as_media_loss() -> None:
    class RateLimited(ExpiringClient):
        async def get_messages(self, chat: Any, ids: int) -> Any:
            raise errors.FloodWaitError(type("Request", (), {})(), 90)

    with pytest.raises(errors.FloodWaitError):
        await download_media_with_refresh(
            RateLimited(_photo_message()), _photo_message(), message_ref=("chat", 55)
        )


async def test_unresolvable_message_reference_does_not_pretend_media_is_lost() -> None:
    class MissingPeer(ExpiringClient):
        async def get_messages(self, chat: Any, ids: int) -> Any:
            raise ValueError("unknown peer")

    with pytest.raises(ValueError, match="unknown peer"):
        await download_media_with_refresh(
            MissingPeer(_photo_message()), _photo_message(), message_ref=("missing", 55)
        )


async def test_telegram_retry_exhaustion_does_not_pretend_media_is_lost() -> None:
    class RetryExhausted(ExpiringClient):
        async def get_messages(self, chat: Any, ids: int) -> Any:
            raise ValueError("Request was unsuccessful 5 time(s)")

    with pytest.raises(ValueError, match="Request was unsuccessful"):
        await download_media_with_refresh(
            RetryExhausted(_photo_message()), _photo_message(), message_ref=("chat", 55)
        )
