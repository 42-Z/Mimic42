from __future__ import annotations

from io import BytesIO
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.agent_store import AgentRecord, InMemoryAgentStore
from mimic42.core.media import MAX_PHOTO_BYTES, MediaFile
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier


def _image_bytes(image_format: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), color=(200, 30, 30)).save(buffer, format=image_format)
    return buffer.getvalue()


PNG = _image_bytes("PNG")
JPEG = _image_bytes("JPEG")


class RecordingMediaStorage:
    def __init__(self) -> None:
        self.uploads: list[tuple[UUID, str, bytes, str, str]] = []

    async def upload(
        self,
        *,
        agent_id: UUID,
        filename: str,
        data: bytes,
        mime_type: str,
        kind: str = "doc",
    ) -> MediaFile | None:
        self.uploads.append((agent_id, filename, data, mime_type, kind))
        return MediaFile(
            kind=kind,
            name=filename,
            mime_type=mime_type,
            size=len(data),
            storage_path=f"{agent_id}/upload/{filename}",
        )

    async def open(self, path: str) -> bytes | None:
        return None

    async def remove_prefix(self, agent_id: UUID) -> None:
        return None


def _store_with_agent(owner_id: UUID, agent_id: UUID) -> InMemoryAgentStore:
    return InMemoryAgentStore(
        agents=[
            AgentRecord(
                agent_id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                state=AgentRuntimeState.STOPPED,
            )
        ]
    )


def _app(owner_id: UUID, agent_id: UUID, storage: RecordingMediaStorage):  # noqa: ANN202
    return create_app(
        agent_store=_store_with_agent(owner_id, agent_id),
        auth_verifier=FakeAuthVerifier(owner_id),
        media_uploader=storage,
    )


async def _upload(
    owner_id: UUID,
    agent_id: UUID,
    storage: RecordingMediaStorage,
    file: tuple[str, bytes, str],
) -> tuple[int, dict]:
    async with AsyncClient(
        transport=ASGITransport(app=_app(owner_id, agent_id, storage)),
        base_url="http://testserver",
    ) as client:
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/media",
            headers=AUTH_HEADERS,
            files={"file": file},
        )
    return resp.status_code, resp.json()


@pytest.mark.asyncio
async def test_upload_stores_the_image_in_the_agent_folder() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    storage = RecordingMediaStorage()

    status, body = await _upload(
        owner_id, agent_id, storage, ("снимок экрана.png", PNG, "image/png")
    )

    assert status == 201
    assert body["storage_path"].startswith(f"{agent_id}/")
    assert body["mime_type"] == "image/png"
    assert body["size"] == len(PNG)
    # Имя санитайзится в сторе, но расширение обязано пережить загрузку:
    # по нему Telethon решает, что это фото, а не файл.
    assert body["name"].endswith(".png")
    assert storage.uploads[0][0] == agent_id
    assert storage.uploads[0][4] == "photo"


@pytest.mark.asyncio
async def test_upload_gives_a_file_without_an_extension_one_by_type() -> None:
    storage = RecordingMediaStorage()

    status, _ = await _upload(uuid4(), uuid4(), storage, ("photo", JPEG, "image/jpeg"))

    assert status == 201
    assert storage.uploads[0][1] == "photo.jpg"


@pytest.mark.asyncio
async def test_upload_trusts_the_content_over_the_declared_type() -> None:
    """Браузер может прислать PNG с чужим типом и расширением: имя и mime
    берутся из самого файла, иначе Telethon отправил бы его документом."""
    storage = RecordingMediaStorage()

    status, body = await _upload(uuid4(), uuid4(), storage, ("pic.jpg", PNG, "image/jpeg"))

    assert status == 201
    assert body["mime_type"] == "image/png"
    assert storage.uploads[0][1] == "pic.png"


@pytest.mark.asyncio
async def test_upload_refuses_a_file_that_only_claims_to_be_an_image() -> None:
    storage = RecordingMediaStorage()

    status, _ = await _upload(uuid4(), uuid4(), storage, ("pic.png", b"%PDF-1.7", "image/png"))

    assert status == 415
    assert storage.uploads == []


@pytest.mark.asyncio
async def test_upload_refuses_a_type_telegram_would_not_show_as_a_photo() -> None:
    storage = RecordingMediaStorage()
    buffer = BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, format="GIF")

    status, _ = await _upload(
        uuid4(), uuid4(), storage, ("anim.gif", buffer.getvalue(), "image/gif")
    )

    assert status == 415
    assert storage.uploads == []


@pytest.mark.asyncio
async def test_upload_refuses_a_file_over_the_photo_limit() -> None:
    storage = RecordingMediaStorage()

    status, _ = await _upload(
        uuid4(), uuid4(), storage, ("big.png", PNG + b"x" * MAX_PHOTO_BYTES, "image/png")
    )

    assert status == 413
    assert storage.uploads == []


@pytest.mark.asyncio
async def test_upload_refuses_an_empty_file() -> None:
    storage = RecordingMediaStorage()

    status, _ = await _upload(uuid4(), uuid4(), storage, ("empty.png", b"", "image/png"))

    assert status == 400
    assert storage.uploads == []


@pytest.mark.asyncio
async def test_upload_is_denied_for_a_foreign_agent() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    storage = RecordingMediaStorage()
    app = create_app(
        agent_store=_store_with_agent(uuid4(), agent_id),
        auth_verifier=FakeAuthVerifier(owner_id),
        media_uploader=storage,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/media",
            headers=AUTH_HEADERS,
            files={"file": ("pic.png", PNG, "image/png")},
        )

    assert resp.status_code == 404
    assert storage.uploads == []
