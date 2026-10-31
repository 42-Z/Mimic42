from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from mimic42.api.app import create_app
from mimic42.config import Settings
from mimic42.core.admin import (
    AdminAgentProxy,
    AdminAgentSummary,
    AdminPage,
    AdminProxyDetail,
    AdminRepository,
    AdminUserDetail,
    AdminUserSummary,
)
from mimic42.core.agent_runtime import AgentRuntimeState, TelegramProxyConfig
from mimic42.core.model_catalog import DEFAULT_LLM_MODEL
from mimic42.core.telegram_proxy import TelegramProxyCheckResult
from tests.api.admin_fakes import FakeAdminRepository
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier
from tests.api.fakes import FakeAgentManager


def _settings() -> Settings:
    return Settings(
        database_connection_string=None,
        mem0_api_key=None,
        braintrust_api_key=None,
        supabase_url=None,
        supabase_service_key=None,
        secret_key=None,
    )


def _proxy_detail(
    *,
    proxy_id: UUID | None = None,
    label: str = "Основной",
    has_password: bool = True,
    agents_total: int = 0,
) -> AdminProxyDetail:
    now = datetime(2026, 10, 30, 12, tzinfo=UTC)
    return AdminProxyDetail(
        id=proxy_id or uuid4(),
        label=label,
        protocol="socks5",
        host="proxy.example.test",
        port=1080,
        username="mimic",
        has_password=has_password,
        is_active=True,
        agents_total=agents_total,
        onboarding_total=0,
        created_at=now,
        updated_at=now,
        created_by=uuid4(),
    )


def _app(
    admin_id: UUID,
    repository: FakeAdminRepository,
    manager: FakeAgentManager | None = None,
) -> FastAPI:
    return create_app(
        manager=manager or FakeAgentManager(),
        admin_repository=cast(AdminRepository, repository),
        auth_verifier=FakeAuthVerifier(admin_id),
        settings=_settings(),
    )


def _detail_with_agent(owner_id: UUID, agent_id: UUID) -> AdminUserDetail:
    return AdminUserDetail(
        profile=AdminUserSummary(
            user_id=owner_id,
            email="owner@example.test",
            display_name="Владелец",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            agents_total=1,
            states={AgentRuntimeState.STOPPED: 1},
        ),
        agents=AdminPage(
            items=[
                AdminAgentSummary(
                    agent_id=agent_id,
                    name="Мимик",
                    llm_model=DEFAULT_LLM_MODEL,
                    state=AgentRuntimeState.STOPPED,
                )
            ],
            total=1,
            page=1,
            page_size=25,
        ),
    )


@pytest.mark.asyncio
async def test_proxy_list_never_exposes_the_password() -> None:
    admin_id = uuid4()
    proxy = _proxy_detail()
    repository = FakeAdminRepository(
        admin_ids={admin_id},
        proxies=[proxy],
        proxy_configs={
            proxy.id: TelegramProxyConfig(
                protocol="socks5",
                host=proxy.host,
                port=proxy.port,
                username=proxy.username,
                password=SecretStr("secret"),
            )
        },
    )
    app = _app(admin_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/admin/proxies", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["items"][0]["has_password"] is True
    assert '"password"' not in response.text
    assert "secret" not in response.text
    assert repository.proxy_calls == [("list", {"page": 1, "page_size": 25})]


@pytest.mark.asyncio
async def test_create_proxy_accepts_credentials_and_returns_no_password() -> None:
    admin_id = uuid4()
    repository = FakeAdminRepository(admin_ids={admin_id})
    app = _app(admin_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/proxies",
            headers=AUTH_HEADERS,
            json={
                "label": " Основной ",
                "protocol": "socks5",
                "host": " proxy.example.test ",
                "port": 1080,
                "username": " mimic ",
                "password": "secret",
                "is_active": True,
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["label"] == "Основной"
    assert body["host"] == "proxy.example.test"
    assert body["username"] == "mimic"
    assert body["has_password"] is True
    assert "secret" not in response.text
    assert repository.proxy_calls[0][1]["values"]["password"] == "secret"


@pytest.mark.asyncio
async def test_create_proxy_rejects_password_without_username() -> None:
    admin_id = uuid4()
    repository = FakeAdminRepository(admin_ids={admin_id})
    app = _app(admin_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/proxies",
            headers=AUTH_HEADERS,
            json={
                "label": "Основной",
                "protocol": "socks5",
                "host": "proxy.example.test",
                "port": 1080,
                "password": "secret",
            },
        )

    assert response.status_code == 422
    assert repository.proxy_calls == []


@pytest.mark.asyncio
async def test_create_proxy_without_a_label_returns_null_label() -> None:
    admin_id = uuid4()
    repository = FakeAdminRepository(admin_ids={admin_id})
    app = _app(admin_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/proxies",
            headers=AUTH_HEADERS,
            json={
                "protocol": "socks5",
                "host": "proxy.example.test",
                "port": 1080,
            },
        )

    assert response.status_code == 201
    assert response.json()["label"] is None
    assert repository.proxy_calls[0][1]["values"]["label"] is None


@pytest.mark.asyncio
async def test_import_parses_file_lines_and_skips_existing_proxy() -> None:
    admin_id = uuid4()
    existing = _proxy_detail(label="Уже есть")
    repository = FakeAdminRepository(admin_ids={admin_id}, proxies=[existing])
    app = _app(admin_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/proxies/import",
            headers=AUTH_HEADERS,
            json={
                "text": "\n".join(
                    [
                        f"{existing.host}:{existing.port}:{existing.username}:new-password",
                        "5.6.7.8:3128:second:secret",
                        "not-a-proxy",
                    ]
                ),
                "protocol": "socks5",
                "is_active": True,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "imported": 1,
        "skipped": 1,
        "errors": ["Строка 3: Ожидается host:port или host:port:login:password"],
    }
    assert "new-password" not in response.text
    assert "secret" not in response.text
    created = [call for call in repository.proxy_calls if call[0] == "create"]
    assert created[0][1]["values"]["label"] is None
    assert created[0][1]["values"]["password"] == "secret"


@pytest.mark.asyncio
async def test_import_url_errors_never_echo_credentials_and_keep_counters() -> None:
    admin_id = uuid4()
    existing = _proxy_detail()
    repository = FakeAdminRepository(admin_ids={admin_id}, proxies=[existing])
    app = _app(admin_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/proxies/import",
            headers=AUTH_HEADERS,
            json={
                "text": "\n".join(
                    [
                        "# comment",
                        "socks5://user:review_secret#rest@proxy.example.test:1080",
                        "http://user:nfkc_secret\uff03suffix@proxy.example.test:3128",
                        "socks5://user:bracket_secret@[bracket_secret]:1080",
                        f"{existing.host}:{existing.port}:{existing.username}:duplicate_secret",
                        "",
                        "5.6.7.8:3128:second:imported_secret",
                        "5.6.7.8:3128:second:imported_secret",
                    ]
                ),
                "protocol": "socks5",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 1
    assert body["skipped"] == 2
    assert len(body["errors"]) == 3
    for line_number, error in enumerate(body["errors"], start=2):
        assert error.startswith(f"Строка {line_number}: ")
    for fragment in (
        "review_secret",
        "rest",
        "nfkc_secret",
        "suffix",
        "bracket_secret",
        "duplicate_secret",
        "imported_secret",
    ):
        assert fragment not in response.text
    created = [call for call in repository.proxy_calls if call[0] == "create"]
    assert len(created) == 1
    assert created[0][1]["values"]["label"] is None
    assert created[0][1]["values"]["password"] == "imported_secret"


@pytest.mark.asyncio
async def test_create_proxy_rejects_an_overlong_password() -> None:
    admin_id = uuid4()
    repository = FakeAdminRepository(admin_ids={admin_id})
    app = _app(admin_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/proxies",
            headers=AUTH_HEADERS,
            json={
                "label": "Основной",
                "protocol": "socks5",
                "host": "proxy.example.test",
                "port": 1080,
                "username": "mimic",
                "password": "x" * 513,
            },
        )

    assert response.status_code == 422
    assert repository.proxy_calls == []


@pytest.mark.asyncio
async def test_patch_without_password_keeps_the_old_one_and_password_is_never_returned() -> None:
    admin_id = uuid4()
    proxy = _proxy_detail()
    repository = FakeAdminRepository(admin_ids={admin_id}, proxies=[proxy])
    app = _app(admin_id, repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/api/v1/admin/proxies/{proxy.id}",
            headers=AUTH_HEADERS,
            json={"label": "Новый", "password": ""},
        )

    assert response.status_code == 200
    assert response.json()["label"] == "Новый"
    assert response.json()["has_password"] is True
    assert '"password"' not in response.text
    recorded = repository.proxy_calls[0][1]["values"]
    assert recorded.get("password") is None


@pytest.mark.asyncio
async def test_delete_assigned_proxy_succeeds_and_reloads_agents() -> None:
    admin_id = uuid4()
    owner_id = uuid4()
    agent_id = uuid4()
    proxy = _proxy_detail(agents_total=1)
    repository = FakeAdminRepository(
        admin_ids={admin_id},
        proxies=[proxy],
        user_details={owner_id: _detail_with_agent(owner_id, agent_id)},
    )
    repository.agent_proxies[agent_id] = AdminAgentProxy(
        id=proxy.id,
        label=proxy.label,
        protocol=proxy.protocol,
        host=proxy.host,
        port=proxy.port,
        is_active=proxy.is_active,
    )
    manager = FakeAgentManager(default_owner_id=owner_id)
    app = _app(admin_id, repository, manager)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(
            f"/api/v1/admin/proxies/{proxy.id}",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 204
    assert proxy.id not in repository.proxies
    assert repository.agent_proxies[agent_id] is None
    assert manager.reloaded == [agent_id]


@pytest.mark.asyncio
async def test_assign_proxy_updates_agent_and_reloads_runtime() -> None:
    admin_id = uuid4()
    owner_id = uuid4()
    agent_id = uuid4()
    proxy = _proxy_detail()
    repository = FakeAdminRepository(
        admin_ids={admin_id},
        proxies=[proxy],
        user_details={owner_id: _detail_with_agent(owner_id, agent_id)},
    )
    manager = FakeAgentManager(default_owner_id=owner_id)
    app = _app(admin_id, repository, manager)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            f"/api/v1/admin/agents/{agent_id}/proxy",
            headers=AUTH_HEADERS,
            json={"proxy_id": str(proxy.id)},
        )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(proxy.id),
        "label": proxy.label,
        "protocol": "socks5",
        "host": proxy.host,
        "port": proxy.port,
        "is_active": True,
    }
    assert manager.reloaded == [agent_id]
    assert repository.agent_proxies[agent_id] == AdminAgentProxy(
        id=proxy.id,
        label=proxy.label,
        protocol="socks5",
        host=proxy.host,
        port=proxy.port,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_assign_proxy_reports_reload_failure_after_persisting_the_change() -> None:
    admin_id = uuid4()
    owner_id = uuid4()
    agent_id = uuid4()
    proxy = _proxy_detail()
    repository = FakeAdminRepository(
        admin_ids={admin_id},
        proxies=[proxy],
        user_details={owner_id: _detail_with_agent(owner_id, agent_id)},
    )
    manager = FakeAgentManager(default_owner_id=owner_id, reload_error=True)
    app = _app(admin_id, repository, manager)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            f"/api/v1/admin/agents/{agent_id}/proxy",
            headers=AUTH_HEADERS,
            json={"proxy_id": str(proxy.id)},
        )

    assert response.status_code == 503
    assert "Прокси назначен" in response.json()["detail"]
    assert repository.agent_proxies[agent_id] is not None


@pytest.mark.asyncio
async def test_proxy_check_returns_connection_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_id = uuid4()
    proxy = _proxy_detail()
    repository = FakeAdminRepository(
        admin_ids={admin_id},
        proxies=[proxy],
        proxy_configs={
            proxy.id: TelegramProxyConfig(protocol="socks5", host=proxy.host, port=proxy.port)
        },
    )
    app = _app(admin_id, repository)

    async def fake_check(_config: TelegramProxyConfig) -> TelegramProxyCheckResult:
        return TelegramProxyCheckResult(ok=True, latency_ms=42)

    monkeypatch.setattr("mimic42.api.admin.check_telegram_proxy", fake_check)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/admin/proxies/{proxy.id}/check",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "latency_ms": 42, "error": None}
