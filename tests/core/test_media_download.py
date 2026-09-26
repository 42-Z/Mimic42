from __future__ import annotations

from datetime import UTC
from typing import Any

import pytest
from telethon import errors, types

from mimic42.core.media_download import (
    MediaRef,
    MediaRefCache,
    MediaUnavailableError,
    download_media_with_refresh,
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


async def test_refresh_rejects_a_replaced_attachment() -> None:
    """Перечитанное сообщение могли отредактировать: медиа с другим id под
    старый media_id не подсовываем (как и сам Telethon при обновлении)."""
    client = ExpiringClient(fresh=_photo_message(media_id=999))

    with pytest.raises(MediaUnavailableError):
        await download_media_with_refresh(
            client, _photo_message(media_id=123), message_ref=(-100500, 55)
        )

    assert len(client.downloads) == 1


async def test_media_empty_error_is_also_unavailable() -> None:
    """Пропавшее медиа Telegram отдаёт как MediaEmptyError — это та же
    категория «скачать больше нельзя»."""

    class EmptyMediaClient(ExpiringClient):
        async def download_media(self, message: Any, file: Any = None, **kwargs: Any) -> Any:
            self.downloads.append(message)
            raise errors.MediaEmptyError(type("Request", (), {})())

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
