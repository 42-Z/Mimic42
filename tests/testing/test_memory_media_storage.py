"""MemoryMediaStorage — фолбэк хранилища медиа для живых тестов без сервисного ключа."""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests.real_tg.backend.helpers import MemoryMediaStorage, media_storage


async def test_uploads_with_the_same_name_do_not_overwrite_each_other() -> None:
    """Два входящих photo.jpeg — два разных пути: иначе open() по старому пути
    вернул бы чужие байты, и «архив переживает потерю файла» только на вид."""
    storage = MemoryMediaStorage()
    agent_id = uuid4()

    first = await storage.upload(
        agent_id=agent_id,
        filename="photo.jpeg",
        data=b"first",
        mime_type="image/jpeg",
        kind="photo",
    )
    second = await storage.upload(
        agent_id=agent_id,
        filename="photo.jpeg",
        data=b"second",
        mime_type="image/jpeg",
        kind="photo",
    )

    assert first.storage_path != second.storage_path
    assert await storage.open(first.storage_path) == b"first"
    assert await storage.open(second.storage_path) == b"second"


async def test_empty_upload_and_missing_path_are_not_archived() -> None:
    storage = MemoryMediaStorage()
    assert (
        await storage.upload(agent_id=uuid4(), filename="empty", data=b"", mime_type="image/jpeg")
        is None
    )
    assert await storage.open("missing") is None


def test_media_storage_without_service_key_is_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    assert isinstance(media_storage(), MemoryMediaStorage)
