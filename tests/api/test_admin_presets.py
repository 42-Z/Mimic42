from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.config import Settings
from mimic42.core.admin import AdminPresetDetail
from tests.api.admin_fakes import FakeAdminRepository
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier

if TYPE_CHECKING:
    from mimic42.core.admin import AdminRepository


def _settings() -> Settings:
    return Settings(
        database_connection_string=None,
        mem0_api_key=None,
        braintrust_api_key=None,
        supabase_url=None,
        supabase_service_key=None,
        secret_key=None,
    )


def _preset(
    *,
    owner_id: UUID | None = None,
    published: bool = False,
    active: bool = True,
    title: str = "Preset",
) -> AdminPresetDetail:
    return AdminPresetDetail(
        id=uuid4(),
        owner_id=owner_id,
        owner_name="Author" if owner_id is not None else None,
        title=title,
        summary="Summary",
        sort_order=3,
        is_active=active,
        published_at=datetime.now(UTC) if published else None,
        updated_at=datetime.now(UTC),
        body="Private prompt body",
        settings={"enabled_tools": ["send_text_message"]},
    )


def _app(user_id: UUID, repository: FakeAdminRepository) -> FastAPI:
    return create_app(
        settings=_settings(),
        auth_verifier=FakeAuthVerifier(user_id),
        admin_repository=cast("AdminRepository", repository),
    )


@pytest.mark.asyncio
async def test_preset_list_excludes_content_and_detail_only_exposes_visible_rows() -> None:
    owner_id = uuid4()
    official_active = _preset(title="Official active")
    official_inactive = _preset(title="Official inactive", active=False)
    custom_active = _preset(owner_id=owner_id, published=True, title="Published active")
    custom_hidden = _preset(
        owner_id=owner_id,
        published=True,
        active=False,
        title="Published hidden",
    )
    private = _preset(owner_id=owner_id, title="Private draft")
    user_id = uuid4()
    repository = FakeAdminRepository(
        admin_ids={user_id},
        presets=[official_active, official_inactive, custom_active, custom_hidden, private],
    )
    app = _app(user_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listing = await client.get("/api/v1/admin/presets", headers=AUTH_HEADERS)
        details = [
            await client.get(f"/api/v1/admin/presets/{preset.id}", headers=AUTH_HEADERS)
            for preset in (official_active, official_inactive, custom_active, custom_hidden)
        ]
        private_detail = await client.get(
            f"/api/v1/admin/presets/{private.id}", headers=AUTH_HEADERS
        )

    assert listing.status_code == 200
    payload = listing.json()
    assert payload["total"] == 4
    assert {item["id"] for item in payload["items"]} == {
        str(official_active.id),
        str(official_inactive.id),
        str(custom_active.id),
        str(custom_hidden.id),
    }
    assert all("body" not in item and "settings" not in item for item in payload["items"])
    assert [response.status_code for response in details] == [200, 200, 200, 200]
    assert all(response.json()["body"] == "Private prompt body" for response in details)
    assert all("settings" in response.json() for response in details)
    assert private_detail.status_code == 404


@pytest.mark.asyncio
async def test_official_create_patch_and_published_custom_visibility() -> None:
    admin_id = uuid4()
    official = _preset(title="  Keep original whitespace  ")
    owner_id = uuid4()
    published = _preset(owner_id=owner_id, published=True, active=True)
    private = _preset(owner_id=owner_id, published=False, active=True)
    repository = FakeAdminRepository(admin_ids={admin_id}, presets=[official, published, private])
    app = _app(admin_id, repository)
    create_values = {
        "title": "  New title  ",
        "summary": " New summary ",
        "body": " New body ",
        "settings": {"custom": {"preserve": True}},
        "sort_order": 7,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/admin/presets", json=create_values, headers=AUTH_HEADERS
        )
        patched = await client.patch(
            f"/api/v1/admin/presets/{official.id}",
            json={"sort_order": 9},
            headers=AUTH_HEADERS,
        )
        hidden = await client.patch(
            f"/api/v1/admin/presets/{published.id}/visibility",
            json={"is_active": False},
            headers=AUTH_HEADERS,
        )
        private_visibility = await client.patch(
            f"/api/v1/admin/presets/{private.id}/visibility",
            json={"is_active": False},
            headers=AUTH_HEADERS,
        )
        custom_edit = await client.patch(
            f"/api/v1/admin/presets/{published.id}",
            json={"body": "Administrator must not edit user content"},
            headers=AUTH_HEADERS,
        )

    assert created.status_code == 201
    assert created.json()["title"] == create_values["title"]
    assert created.json()["body"] == create_values["body"]
    assert created.json()["settings"] == create_values["settings"]
    assert patched.status_code == 200
    assert patched.json()["sort_order"] == 9
    assert patched.json()["title"] == official.title
    assert patched.json()["body"] == official.body
    assert patched.json()["settings"] == official.settings
    assert hidden.status_code == 200
    assert hidden.json()["is_active"] is False
    assert private_visibility.status_code == 404
    assert custom_edit.status_code == 404
    assert repository.presets[published.id].body == published.body
    assert repository.preset_calls[0][1]["actor_user_id"] == admin_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("title", ""),
        ("title", " " * 4),
        ("title", "t" * 201),
        ("summary", "\t\n"),
        ("summary", "s" * 1001),
        ("body", " "),
        ("body", "b" * 20001),
    ],
)
async def test_create_rejects_invalid_text_without_normalizing_valid_text(
    field: str,
    value: str,
) -> None:
    admin_id = uuid4()
    repository = FakeAdminRepository(admin_ids={admin_id})
    app = _app(admin_id, repository)
    payload = {
        "title": "Title",
        "summary": "Summary",
        "body": "Body",
        "settings": None,
        "sort_order": 0,
    }
    payload[field] = value

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/admin/presets", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_validation_rejects_empty_null_required_and_extra_fields() -> None:
    admin_id = uuid4()
    official = _preset()
    repository = FakeAdminRepository(admin_ids={admin_id}, presets=[official])
    app = _app(admin_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        empty = await client.patch(
            f"/api/v1/admin/presets/{official.id}", json={}, headers=AUTH_HEADERS
        )
        null_title = await client.patch(
            f"/api/v1/admin/presets/{official.id}",
            json={"title": None},
            headers=AUTH_HEADERS,
        )
        null_sort_order = await client.patch(
            f"/api/v1/admin/presets/{official.id}",
            json={"sort_order": None},
            headers=AUTH_HEADERS,
        )
        unknown = await client.patch(
            f"/api/v1/admin/presets/{official.id}",
            json={"owner_id": None},
            headers=AUTH_HEADERS,
        )
        nullable_settings = await client.patch(
            f"/api/v1/admin/presets/{official.id}",
            json={"settings": None},
            headers=AUTH_HEADERS,
        )

    assert [
        empty.status_code,
        null_title.status_code,
        null_sort_order.status_code,
        unknown.status_code,
    ] == [422, 422, 422, 422]
    assert nullable_settings.status_code == 200
    assert nullable_settings.json()["settings"] is None
    assert repository.preset_calls[-1][1]["values"] == {"settings": None}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"title": "Title", "summary": "Summary", "body": "Body", "owner_id": None},
        {"title": "Title", "summary": "Summary", "body": "Body", "slug": "client"},
        {
            "title": "Title",
            "summary": "Summary",
            "body": "Body",
            "published_at": None,
        },
        {"title": "Title", "summary": "Summary", "body": "Body", "is_active": False},
        {"title": "Title", "summary": "Summary", "body": "Body", "actor_user_id": str(uuid4())},
    ],
)
async def test_create_forbids_client_managed_identity_and_visibility(
    payload: dict[str, object],
) -> None:
    admin_id = uuid4()
    repository = FakeAdminRepository(admin_ids={admin_id})
    app = _app(admin_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/admin/presets", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_preset_list_trims_search_and_validates_pagination_and_kind() -> None:
    admin_id = uuid4()
    repository = FakeAdminRepository(admin_ids={admin_id}, presets=[_preset()])
    app = _app(admin_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        valid = await client.get(
            "/api/v1/admin/presets",
            params={"q": "  Preset  ", "page": 1, "page_size": 100, "kind": "all"},
            headers=AUTH_HEADERS,
        )
        invalid_queries = [
            await client.get("/api/v1/admin/presets?page=0", headers=AUTH_HEADERS),
            await client.get("/api/v1/admin/presets?page=1000001", headers=AUTH_HEADERS),
            await client.get("/api/v1/admin/presets?page_size=0", headers=AUTH_HEADERS),
            await client.get("/api/v1/admin/presets?page_size=101", headers=AUTH_HEADERS),
            await client.get(
                "/api/v1/admin/presets", params={"kind": "private"}, headers=AUTH_HEADERS
            ),
            await client.get(
                "/api/v1/admin/presets", params={"q": "q" * 201}, headers=AUTH_HEADERS
            ),
        ]

    assert valid.status_code == 200
    assert repository.preset_calls[0][1] == {
        "q": "Preset",
        "kind": "all",
        "page": 1,
        "page_size": 100,
    }
    assert all(response.status_code == 422 for response in invalid_queries)


@pytest.mark.asyncio
async def test_sort_order_is_a_postgres_integer_for_create_and_patch() -> None:
    admin_id = uuid4()
    official = _preset()
    repository = FakeAdminRepository(admin_ids={admin_id}, presets=[official])
    app = _app(admin_id, repository)
    create_payload = {"title": "Title", "summary": "Summary", "body": "Body"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for invalid in (-2_147_483_649, 2_147_483_648, True):
            created = await client.post(
                "/api/v1/admin/presets",
                json={**create_payload, "sort_order": invalid},
                headers=AUTH_HEADERS,
            )
            patched = await client.patch(
                f"/api/v1/admin/presets/{official.id}",
                json={"sort_order": invalid},
                headers=AUTH_HEADERS,
            )
            assert created.status_code == 422
            assert patched.status_code == 422

        for valid in (-2_147_483_648, 2_147_483_647):
            created = await client.post(
                "/api/v1/admin/presets",
                json={**create_payload, "sort_order": valid},
                headers=AUTH_HEADERS,
            )
            assert created.status_code == 201
            assert created.json()["sort_order"] == valid


@pytest.mark.asyncio
async def test_visibility_body_only_accepts_boolean() -> None:
    admin_id = uuid4()
    official = _preset()
    repository = FakeAdminRepository(admin_ids={admin_id}, presets=[official])
    app = _app(admin_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        extra = await client.patch(
            f"/api/v1/admin/presets/{official.id}/visibility",
            json={"is_active": False, "title": "Not allowed"},
            headers=AUTH_HEADERS,
        )
        non_boolean = await client.patch(
            f"/api/v1/admin/presets/{official.id}/visibility",
            json={"is_active": "false"},
            headers=AUTH_HEADERS,
        )

    assert extra.status_code == 422
    assert non_boolean.status_code == 422


@pytest.mark.asyncio
async def test_admin_authentication_and_role_are_checked_for_every_preset_route() -> None:
    admin_id = uuid4()
    official = _preset()
    published = _preset(owner_id=uuid4(), published=True)
    repository = FakeAdminRepository(admin_ids={admin_id}, presets=[official, published])
    app = _app(admin_id, repository)
    paths = [
        ("GET", "/api/v1/admin/presets", None),
        ("GET", f"/api/v1/admin/presets/{official.id}", None),
        ("POST", "/api/v1/admin/presets", {"title": "t", "summary": "s", "body": "b"}),
        ("PATCH", f"/api/v1/admin/presets/{official.id}", {"title": "Changed"}),
        (
            "PATCH",
            f"/api/v1/admin/presets/{published.id}/visibility",
            {"is_active": False},
        ),
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for method, path, payload in paths:
            response = await client.request(method, path, json=payload)
            assert response.status_code == 401
        for method, path, payload in paths:
            response = await client.request(
                method,
                path,
                json=payload,
                headers=AUTH_HEADERS,
            )
            expected_status = 201 if method == "POST" else 200
            assert response.status_code == expected_status

        repository.admin_ids.clear()
        non_admin_responses = [
            await client.request(method, path, json=payload, headers=AUTH_HEADERS)
            for method, path, payload in paths
        ]

    assert all(response.status_code == 403 for response in non_admin_responses)
    assert len(repository.calls) == len(paths) * 2
