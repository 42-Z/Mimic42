from __future__ import annotations

import builtins
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mimic42.integrations.supabase_media import MAX_MEDIA_BYTES, SupabaseMediaStorage


class FakeBucket:
    def __init__(self, store: dict[str, bytes]) -> None:
        self._store = store

    def upload(self, *, file: bytes, path: str, file_options: dict[str, str] | None = None) -> None:
        self._store[path] = bytes(file)

    def download(self, path: str) -> bytes:
        if path not in self._store:
            raise KeyError(path)
        return self._store[path]

    def list(self, prefix: str) -> builtins.list[dict[str, str]]:
        return [
            {"name": p.removeprefix(prefix + "/")}
            for p in self._store
            if p.startswith(prefix + "/")
        ]

    def remove(self, paths: builtins.list[str]) -> None:
        for p in paths:
            self._store.pop(p, None)


def build_storage(monkeypatch: pytest.MonkeyPatch, store: dict[str, bytes]) -> SupabaseMediaStorage:
    bucket = FakeBucket(store)
    fake = SimpleNamespace(storage=SimpleNamespace(from_=lambda _name: bucket))
    monkeypatch.setattr("supabase.create_client", lambda *a, **k: fake)
    return SupabaseMediaStorage(
        supabase_url="https://example.supabase.co", service_key="service-key"
    )


async def test_upload_stores_file_and_returns_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, bytes] = {}
    storage = build_storage(monkeypatch, store)
    agent_id = uuid4()
    media = await storage.upload(
        agent_id=agent_id,
        filename="photo.jpeg",
        data=b"\xff\xd8jpg",
        mime_type="image/jpeg",
        kind="photo",
    )
    assert media is not None
    assert media.kind == "photo"
    assert media.storage_path is not None
    assert media.storage_path.startswith(f"{agent_id}/")
    assert media.storage_path.endswith("/photo.jpeg")
    assert media.size == len(b"\xff\xd8jpg")
    assert store[media.storage_path] == b"\xff\xd8jpg"


async def test_upload_skips_oversized(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, bytes] = {}
    storage = build_storage(monkeypatch, store)
    media = await storage.upload(
        agent_id=uuid4(),
        filename="big.bin",
        data=b"x" * (MAX_MEDIA_BYTES + 1),
        mime_type="application/octet-stream",
        kind="doc",
    )
    assert media is None
    assert store == {}


async def test_open_and_remove_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, bytes] = {}
    storage = build_storage(monkeypatch, store)
    agent_id = uuid4()
    media = await storage.upload(
        agent_id=agent_id, filename="a.txt", data=b"hi", mime_type="text/plain", kind="doc"
    )
    assert media is not None
    assert media.storage_path is not None
    assert await storage.open(media.storage_path) == b"hi"
    assert await storage.open(f"{agent_id}/missing.txt") is None
    await storage.remove_prefix(agent_id)
    assert store == {}
