from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from mimic42.api.app import create_app
from mimic42.config import Settings
from mimic42.testing import server
from mimic42.testing.server import (
    delete_test_official_preset,
    get_test_admin_role,
    set_test_admin_role,
)
from mimic42.testing.slots import DEV_PROJECT_REF, PROD_PROJECT_REF, SLOTS

DEV_DSN = f"postgresql+asyncpg://test:test@db.{DEV_PROJECT_REF}.supabase.co:5432/postgres"
DEV_URL = f"https://{DEV_PROJECT_REF}.supabase.co"


class FakeTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeConnection:
    def __init__(
        self,
        *,
        existing: bool = False,
        lease_active: bool = True,
        lease_expires_at: datetime | None = None,
        delete_result: str = "DELETE 1",
    ) -> None:
        self.existing = existing
        self.lease_active = lease_active
        self.lease_expires_at = lease_expires_at or datetime.now(UTC) + timedelta(minutes=1)
        self.delete_result = delete_result
        self.statements: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.statements.append((query, args))
        lowered_query = query.lower()
        if "test_support.slot_leases" in lowered_query:
            return self.lease_expires_at
        if "clock_timestamp()" in lowered_query:
            return self.lease_active
        return self.existing

    async def execute(self, query: str, *args: Any) -> str:
        self.statements.append((query, args))
        return self.delete_result

    async def close(self) -> None:
        self.closed = True


def _fake_app_settings() -> Settings:
    return Settings(
        database_connection_string=DEV_DSN,
        supabase_url=DEV_URL,
        secret_key="test-only-secret",
        telegram_api_id=1,
        telegram_api_hash="test-only-hash",
        mem0_api_key=None,
        braintrust_api_key=None,
    )


@pytest.mark.asyncio
async def test_admin_role_helper_changes_only_the_persona_in_the_named_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection(existing=False)
    connect_calls: list[tuple[str, int]] = []

    async def connect(dsn: str, *, timeout: int) -> FakeConnection:
        connect_calls.append((dsn, timeout))
        return connection

    monkeypatch.setattr(server.asyncpg, "connect", connect)
    owner_id = SLOTS[0].persona("empty").user_id

    was_enabled = await set_test_admin_role(
        DEV_DSN, DEV_URL, "a", owner_id, lease_holder="run-a", enabled=True
    )

    assert was_enabled is False
    assert len(connection.statements) == 4
    assert connection.statements[0][1] == ("a", "run-a")
    assert "test_support.slot_leases" in connection.statements[0][0].lower()
    assert "for update" in connection.statements[0][0].lower()
    assert "clock_timestamp()" in connection.statements[1][0].lower()
    assert connection.statements[2][1] == (owner_id,)
    assert connection.statements[3][1] == (owner_id,)
    assert "insert into public.admin_users" in connection.statements[3][0].lower()
    assert "on conflict (user_id) do nothing" in connection.statements[3][0].lower()
    assert "delete from public.admin_users" not in connection.statements[3][0].lower()
    assert connect_calls[0][0] == DEV_DSN.replace("postgresql+asyncpg://", "postgresql://", 1)
    assert connection.closed is True


@pytest.mark.asyncio
async def test_admin_role_restore_deletes_only_the_requested_user_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection(existing=True)

    async def connect(_dsn: str, *, timeout: int) -> FakeConnection:
        return connection

    monkeypatch.setattr(server.asyncpg, "connect", connect)
    owner_id = SLOTS[0].persona("empty").user_id

    was_enabled = await set_test_admin_role(
        DEV_DSN, DEV_URL, "a", owner_id, lease_holder="run-a", enabled=False
    )

    assert was_enabled is True
    assert connection.statements[-1][1] == (owner_id,)
    assert (
        "delete from public.admin_users where user_id = $1" in connection.statements[-1][0].lower()
    )
    assert connection.closed is True


@pytest.mark.asyncio
async def test_admin_role_helper_rejects_unknown_slots_and_cross_slot_users_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_connect(*_args: Any, **_kwargs: Any) -> FakeConnection:
        raise AssertionError("validation must happen before database access")

    monkeypatch.setattr(server.asyncpg, "connect", unexpected_connect)
    owner_id = SLOTS[1].persona("empty").user_id

    with pytest.raises(ValueError, match="слот"):
        await set_test_admin_role(
            DEV_DSN, DEV_URL, "missing", owner_id, lease_holder="run-a", enabled=True
        )
    with pytest.raises(ValueError, match="слоту"):
        await set_test_admin_role(
            DEV_DSN, DEV_URL, "a", owner_id, lease_holder="run-a", enabled=True
        )


@pytest.mark.asyncio
async def test_admin_role_helper_checks_expiry_after_locking_the_slot_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The row timestamp can appear valid at transaction start but expire while
    # waiting on its row lock; the second query must check the live wall clock.
    connection = FakeConnection(
        lease_active=False,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )

    async def connect(_dsn: str, *, timeout: int) -> FakeConnection:
        return connection

    monkeypatch.setattr(server.asyncpg, "connect", connect)
    owner_id = SLOTS[0].persona("empty").user_id

    with pytest.raises(ValueError, match="арендован"):
        await set_test_admin_role(
            DEV_DSN, DEV_URL, "a", owner_id, lease_holder="stale-run", enabled=True
        )

    assert len(connection.statements) == 2
    assert "test_support.slot_leases" in connection.statements[0][0].lower()
    assert "clock_timestamp()" in connection.statements[1][0].lower()
    assert connection.statements[1][1] == (connection.lease_expires_at,)
    assert connection.closed is True


@pytest.mark.asyncio
async def test_admin_role_read_is_scoped_to_the_active_slot_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection(existing=True)

    async def connect(_dsn: str, *, timeout: int) -> FakeConnection:
        return connection

    monkeypatch.setattr(server.asyncpg, "connect", connect)
    owner_id = SLOTS[0].persona("empty").user_id

    enabled = await get_test_admin_role(DEV_DSN, DEV_URL, "a", owner_id, lease_holder="run-a")

    assert enabled is True
    assert len(connection.statements) == 3
    assert connection.statements[0][1] == ("a", "run-a")
    assert "clock_timestamp()" in connection.statements[1][0].lower()
    assert connection.statements[2][1] == (owner_id,)
    assert connection.closed is True


@pytest.mark.asyncio
async def test_admin_role_helper_refuses_production_database_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_connect(*_args: Any, **_kwargs: Any) -> FakeConnection:
        raise AssertionError("production settings must fail before database access")

    monkeypatch.setattr(server.asyncpg, "connect", unexpected_connect)
    owner_id = SLOTS[0].persona("empty").user_id
    production_dsn = f"postgresql://test:test@db.{PROD_PROJECT_REF}.supabase.co:5432/postgres"

    with pytest.raises(RuntimeError, match="прод"):
        await set_test_admin_role(
            production_dsn, DEV_URL, "a", owner_id, lease_holder="run-a", enabled=True
        )


@pytest.mark.asyncio
async def test_cleanup_deletes_only_the_captured_test_official_preset_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection(delete_result="DELETE 1")

    async def connect(_dsn: str, *, timeout: int) -> FakeConnection:
        return connection

    monkeypatch.setattr(server.asyncpg, "connect", connect)
    preset_id = UUID("33333333-3333-4333-8333-333333333333")

    deleted = await delete_test_official_preset(
        DEV_DSN,
        DEV_URL,
        preset_id,
        slot_name="a",
        lease_holder="run-a",
    )

    assert deleted is True
    lease_query, lease_args = connection.statements[0]
    assert lease_args == ("a", "run-a")
    assert "test_support.slot_leases" in lease_query.lower()
    assert "clock_timestamp()" in connection.statements[1][0].lower()
    query, args = connection.statements[2]
    assert args == (preset_id,)
    assert "where id = $1" in query.lower()
    assert "owner_id is null" in query.lower()
    assert "e2e admin fixture:%" in query.lower()
    assert connection.closed is True


def test_test_server_exposes_support_routes_but_production_app_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "create_app", lambda **_kwargs: FastAPI())
    monkeypatch.setattr(server, "assert_test_project", lambda *_values: None)

    test_app = server.build_test_app(settings=_fake_app_settings())
    test_routes = [route for route in test_app.routes if isinstance(route, APIRoute)]
    assert any(
        route.path == "/__test__/admin-role" and "GET" in route.methods for route in test_routes
    )
    assert any(
        route.path == "/__test__/admin-role" and "PUT" in route.methods for route in test_routes
    )
    assert any(
        route.path == "/__test__/admin-presets/{preset_id}" and "DELETE" in route.methods
        for route in test_routes
    )

    production_app = create_app(
        settings=Settings(
            database_connection_string=None,
            mem0_api_key=None,
            braintrust_api_key=None,
            supabase_url=None,
            supabase_service_key=None,
            secret_key=None,
        )
    )
    production_paths = {
        route.path for route in production_app.routes if isinstance(route, APIRoute)
    }
    assert "/__test__/admin-role" not in production_paths
    assert "/__test__/admin-presets/{preset_id}" not in production_paths
