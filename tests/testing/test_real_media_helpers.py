"""Ошибка инфраструктуры не должна считаться потерей Telegram-файла."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from telethon import errors, types

from tests.real_tg.backend.test_real_media import recipient_can_download


class DownloadClient:
    def __init__(self, error: Exception | None, fresh: Any | None = None) -> None:
        self.error = error
        self.fresh = fresh
        self.get_messages_calls: list[tuple[int, int]] = []

    async def download_media(self, message: Any, file: Any = None) -> bytes:
        assert file is bytes
        if self.error is not None and message is not self.fresh:
            raise self.error
        return b"photo"

    async def get_messages(self, peer: int, ids: int) -> Any:
        self.get_messages_calls.append((peer, ids))
        return self.fresh


def photo_message() -> Any:
    photo = types.Photo(
        id=123,
        access_hash=456,
        file_reference=b"old",
        date=datetime.now(UTC),
        sizes=[types.PhotoSize(type="x", w=0, h=0, size=0)],
        dc_id=2,
    )
    return types.Message(
        id=55,
        peer_id=types.PeerUser(42),
        message="",
        out=False,
        date=datetime.now(UTC),
        media=types.MessageMediaPhoto(photo=photo),
    )


async def test_recipient_can_download_only_treats_missing_media_as_lost() -> None:
    request = type("Request", (), {})()
    assert await recipient_can_download(DownloadClient(None), photo_message(), 42)
    assert not await recipient_can_download(
        DownloadClient(errors.FileReferenceExpiredError(request)), photo_message(), 42
    )


async def test_recipient_retries_stale_reference_before_declaring_loss() -> None:
    request = type("Request", (), {})()
    fresh = photo_message()
    client = DownloadClient(errors.FileReferenceExpiredError(request), fresh)

    assert await recipient_can_download(client, photo_message(), 42)
    assert client.get_messages_calls == [(42, 55)]


async def test_recipient_can_download_does_not_swallow_network_failure() -> None:
    with pytest.raises(ConnectionError, match="offline"):
        await recipient_can_download(
            DownloadClient(ConnectionError("offline")), photo_message(), 42
        )
