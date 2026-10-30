from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

from mimic42.api.app import create_app
from mimic42.api.auth import CurrentUser, require_user
from mimic42.config import Settings
from tests.api.admin_fakes import FakeAdminRepository
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier

if TYPE_CHECKING:
    from mimic42.core.admin import AdminRepository


def _api_settings() -> Settings:
    return Settings(
        database_connection_string=None,
        mem0_api_key=None,
        braintrust_api_key=None,
        supabase_url=None,
        supabase_service_key=None,
        secret_key=None,
    )


def _app_with_admin_probe(
    user_id: UUID,
    repository: FakeAdminRepository | None,
) -> FastAPI:
    from mimic42.api.admin import require_admin

    app = create_app(
        settings=_api_settings(),
        auth_verifier=FakeAuthVerifier(user_id),
        admin_repository=(cast("AdminRepository", repository) if repository is not None else None),
    )

    @app.get("/__test__/admin-access", dependencies=[Depends(require_admin)])
    async def admin_access_probe() -> dict[str, bool]:
        return {"allowed": True}

    return app


@pytest.mark.asyncio
async def test_admin_endpoint_requires_an_access_token() -> None:
    repository = FakeAdminRepository()
    app = _app_with_admin_probe(uuid4(), repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/__test__/admin-access")

    assert response.status_code == 401
    assert repository.calls == []


@pytest.mark.asyncio
async def test_non_admin_is_forbidden() -> None:
    user_id = uuid4()
    repository = FakeAdminRepository()
    app = _app_with_admin_probe(user_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/__test__/admin-access", headers=AUTH_HEADERS)

    assert response.status_code == 403
    assert repository.calls == [user_id]


@pytest.mark.asyncio
async def test_admin_role_is_rechecked_for_each_request() -> None:
    user_id = uuid4()
    repository = FakeAdminRepository(admin_ids={user_id})
    app = _app_with_admin_probe(user_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/__test__/admin-access", headers=AUTH_HEADERS)
        repository.admin_ids.clear()
        second = await client.get("/__test__/admin-access", headers=AUTH_HEADERS)

    assert first.status_code == 200
    assert second.status_code == 403
    assert repository.calls == [user_id, user_id]


@pytest.mark.asyncio
async def test_admin_dependency_uses_fastapi_user_dependency_override() -> None:
    user_id = uuid4()
    repository = FakeAdminRepository(admin_ids={user_id})
    app = _app_with_admin_probe(uuid4(), repository)

    async def override_user() -> CurrentUser:
        return CurrentUser(user_id=user_id)

    app.dependency_overrides[require_user] = override_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/__test__/admin-access")

    assert response.status_code == 200
    assert repository.calls == [user_id]


@pytest.mark.asyncio
async def test_repository_failure_fails_closed_without_exposing_error_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = FakeAdminRepository(unavailable=True)
    app = _app_with_admin_probe(uuid4(), repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/__test__/admin-access", headers=AUTH_HEADERS)

    assert response.status_code == 503
    assert "postgresql://private-dsn" not in response.text
    assert "private_table" not in response.text
    assert "RuntimeError" in caplog.text
    assert "private-dsn" not in caplog.text
    assert "private_table" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("is_admin", [False, True])
async def test_me_returns_authenticated_identity_and_current_role(is_admin: bool) -> None:
    user_id = uuid4()
    repository = FakeAdminRepository(admin_ids={user_id} if is_admin else set())
    app = create_app(
        settings=_api_settings(),
        auth_verifier=FakeAuthVerifier(user_id),
        admin_repository=cast("AdminRepository", repository),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/me", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"user_id": str(user_id), "is_admin": is_admin}
    assert repository.calls == [user_id]


@pytest.mark.asyncio
async def test_me_returns_503_when_admin_role_cannot_be_checked() -> None:
    user_id = uuid4()
    repository = FakeAdminRepository(unavailable=True)
    app = create_app(
        settings=_api_settings(),
        auth_verifier=FakeAuthVerifier(user_id),
        admin_repository=cast("AdminRepository", repository),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/me", headers=AUTH_HEADERS)

    assert response.status_code == 503
    assert "private-dsn" not in response.text


@pytest.mark.asyncio
async def test_me_without_database_repository_returns_503() -> None:
    app = create_app(
        settings=_api_settings(),
        auth_verifier=FakeAuthVerifier(uuid4()),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/me", headers=AUTH_HEADERS)

    assert response.status_code == 503


def test_admin_router_applies_role_dependency_to_all_its_routes() -> None:
    from mimic42.api.admin import require_admin, router

    assert router.prefix == "/api/v1/admin"
    assert any(dependency.dependency is require_admin for dependency in router.dependencies)


@pytest.mark.asyncio
async def test_database_repository_uses_select_exists_and_fresh_sessions() -> None:
    from mimic42.integrations.database_admin import DatabaseAdminRepository

    class Session:
        def __init__(self, value: bool) -> None:
            self.value = value
            self.closed = False
            self.statement: Any = None

        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *_: object) -> None:
            self.closed = True

        async def scalar(self, statement: Any) -> bool:
            self.statement = statement
            return self.value

    class SessionFactory:
        def __init__(self) -> None:
            self.sessions: list[Session] = []

        def __call__(self) -> Session:
            session = Session(value=not self.sessions)
            self.sessions.append(session)
            return session

    factory = SessionFactory()
    repository = DatabaseAdminRepository(cast(Any, factory))
    first_user_id = uuid4()

    assert await repository.is_admin(first_user_id) is True
    assert await repository.is_admin(uuid4()) is False
    assert len(factory.sessions) == 2
    assert all(session.closed for session in factory.sessions)

    statement = factory.sessions[0].statement
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "SELECT EXISTS" in str(compiled).upper()
    assert "ADMIN_USERS" in str(compiled).upper()
    assert first_user_id in compiled.params.values()


@pytest.mark.asyncio
async def test_database_repository_wraps_sqlalchemy_errors_safely() -> None:
    from mimic42.core.admin import AdminUnavailableError
    from mimic42.integrations.database_admin import DatabaseAdminRepository

    class Session:
        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def scalar(self, _statement: Any) -> bool:
            raise SQLAlchemyError("postgresql://secret-dsn SELECT sensitive_table")

    class SessionFactory:
        def __call__(self) -> Session:
            return Session()

    repository = DatabaseAdminRepository(cast(Any, SessionFactory()))

    with pytest.raises(AdminUnavailableError) as exc_info:
        await repository.is_admin(uuid4())

    assert "secret-dsn" not in str(exc_info.value)
    assert "sensitive_table" not in str(exc_info.value)
    assert exc_info.value.__suppress_context__ is True
