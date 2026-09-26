from __future__ import annotations

import builtins
import warnings
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest

from mimic42.integrations.supabase_media import (
    MAX_MEDIA_BYTES,
    SupabaseMediaStorage,
    storage_client,
)
from supabase import SupabaseException


class FakeBucket:
    """Mimics the real storage API semantics: list() returns one level at a
    time (folders have id=None), remove() deletes exact object paths only."""

    def __init__(self, store: dict[str, bytes]) -> None:
        self._store = store
        self.removed: list[str] = []

    def upload(self, *, file: bytes, path: str, file_options: dict[str, str] | None = None) -> None:
        self._store[path] = bytes(file)

    def download(self, path: str) -> bytes:
        if path not in self._store:
            raise KeyError(path)
        return self._store[path]

    def list(
        self, prefix: str | None = None, options: dict[str, int] | None = None
    ) -> builtins.list[dict[str, object]]:
        prefix = (prefix or "").strip("/")
        children: dict[str, bool] = {}
        for path in self._store:
            if prefix:
                if not path.startswith(prefix + "/"):
                    continue
                rest = path[len(prefix) + 1 :]
            else:
                rest = path
            head = rest.split("/", 1)[0]
            is_file = "/" not in rest
            children[head] = children.get(head, True) and is_file
        return [
            {"name": name, "id": f"obj-{name}" if is_file else None}
            for name, is_file in children.items()
        ]

    def remove(self, paths: builtins.list[str]) -> None:
        for path in paths:
            if path not in self._store:
                raise KeyError(f"not an object: {path}")
            self.removed.append(path)
            self._store.pop(path)


def build_storage(monkeypatch: pytest.MonkeyPatch, store: dict[str, bytes]) -> SupabaseMediaStorage:
    bucket = FakeBucket(store)
    fake = SimpleNamespace(storage=SimpleNamespace(from_=lambda _name: bucket))
    monkeypatch.setattr("supabase.create_client", lambda *a, **k: fake)
    return SupabaseMediaStorage(
        supabase_url="https://example.supabase.co", service_key="service-key"
    )


def test_storage_builds_without_deprecation_warnings() -> None:
    """Живые тесты идут с -W error: предупреждение при создании клиента отключало
    хранилище целиком, и проверки с картинками тихо пропускались."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        storage = SupabaseMediaStorage(
            supabase_url="https://example.supabase.co", service_key="header.payload.signature"
        )
    storage.close()


def test_storage_client_closes_its_http_client_when_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Неверный адрес в настройках: хранилища не будет, а сокеты его HTTP-клиента
    закрыть больше некому."""
    built: list[httpx.Client] = []

    class RecordingClient(httpx.Client):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            built.append(self)

    monkeypatch.setattr(httpx, "Client", RecordingClient)
    with pytest.raises(SupabaseException, match="Invalid URL"):
        storage_client("not-a-url", "header.payload.signature")

    (client,) = built
    assert client.is_closed


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


async def test_remove_prefix_deletes_nested_files_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch: list() is one-level deep; remove() must target exact file paths."""
    store: dict[str, bytes] = {}
    bucket = FakeBucket(store)
    fake = SimpleNamespace(storage=SimpleNamespace(from_=lambda _name: bucket))
    monkeypatch.setattr("supabase.create_client", lambda *a, **k: fake)
    storage = SupabaseMediaStorage(
        supabase_url="https://example.supabase.co", service_key="service-key"
    )
    agent_id = uuid4()
    other_agent = uuid4()
    first = await storage.upload(
        agent_id=agent_id, filename="one.jpeg", data=b"1", mime_type="image/jpeg", kind="photo"
    )
    second = await storage.upload(
        agent_id=agent_id, filename="two.ogg", data=b"2", mime_type="audio/ogg", kind="voice"
    )
    foreign = await storage.upload(
        agent_id=other_agent, filename="keep.txt", data=b"3", mime_type="text/plain", kind="doc"
    )
    assert first and second and foreign and first.storage_path and second.storage_path
    assert foreign.storage_path

    await storage.remove_prefix(agent_id)

    assert set(store) == {foreign.storage_path}
    assert set(bucket.removed) == {first.storage_path, second.storage_path}
