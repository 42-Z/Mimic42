from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from telethon import errors, functions

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentRuntimeState,
    MimicAgentRuntime,
)
from mimic42.core.agent_store import AgentRecord, InMemoryAgentStore
from mimic42.core.manager import AgentManager
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramClient
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier
from tests.api.fakes import configured_telegram_app
from tests.core.test_agent_runtime import FakeLangChainAgent


def _authorized_account() -> FakeTelegramAccount:
    account = FakeTelegramAccount()
    account.authorized = True
    account.username = "old_name"
    return account


@asynccontextmanager
async def _account_app(
    *,
    owner_id: UUID | None = None,
    auth_user_id: UUID | None = None,
    account: FakeTelegramAccount | None = None,
    client_class: type[FakeTelegramClient] = FakeTelegramClient,
) -> AsyncIterator[
    tuple[FastAPI, AgentManager, MimicAgentRuntime, FakeTelegramClient, FakeTelegramAccount]
]:
    owner = owner_id or uuid4()
    viewer = auth_user_id or owner
    telegram_account = account or _authorized_account()
    client = client_class(telegram_account)
    config = AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=owner,
        telegram_api_id=12345,
        telegram_api_hash="hash",
        telegram_session_string="session",
        telegram_session_token="session-token",
        system_prompt="system",
        name="Mimic",
    )
    runtime = MimicAgentRuntime(
        config=config,
        telegram_client=client,
        langchain_agent=FakeLangChainAgent(),
    )
    manager = AgentManager(runtime_factory=lambda _config: runtime)
    await manager.create_agent(config)
    store = InMemoryAgentStore(
        agents=[
            AgentRecord(
                agent_id=config.agent_id,
                owner_id=owner,
                name="Mimic",
                state=AgentRuntimeState.STOPPED,
            )
        ]
    )
    app = create_app(
        manager=manager,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(viewer),
        telegram_app_settings=configured_telegram_app(),
    )
    try:
        yield app, manager, runtime, client, telegram_account
    finally:
        await manager.shutdown()


def _url(runtime: MimicAgentRuntime, suffix: str) -> str:
    return f"/api/v1/agents/{runtime.config.agent_id}/telegram/{suffix}"


@pytest.mark.asyncio
async def test_password_state_reads_telegram_only_for_the_request() -> None:
    async with _account_app() as (app, _manager, runtime, client, _account):
        assert runtime.state is AgentRuntimeState.STOPPED
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.get(_url(runtime, "password"), headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"has_password": False}
    assert client.connect_calls == 1
    assert client.disconnect_calls == 1
    assert runtime.state is AgentRuntimeState.STOPPED


@pytest.mark.asyncio
async def test_username_is_changed_and_the_confirmed_name_is_returned() -> None:
    async with _account_app() as (app, _manager, runtime, client, account):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.put(
                _url(runtime, "username"),
                headers=AUTH_HEADERS,
                json={"username": "@new_name"},
            )

    assert response.status_code == 200
    assert response.json() == {"username": "new_name"}
    assert account.username == "new_name"
    assert runtime.telegram_username == "new_name"
    assert client.connect_calls == 1
    assert client.disconnect_calls == 1


@pytest.mark.asyncio
async def test_invalid_username_is_refused_before_telegram() -> None:
    async with _account_app() as (app, _manager, runtime, client, account):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.put(
                _url(runtime, "username"),
                headers=AUTH_HEADERS,
                json={"username": "bad name"},
            )

    assert response.status_code == 422
    assert account.username == "old_name"
    assert client.requests == []


@pytest.mark.asyncio
async def test_username_rejected_by_telegram_returns_400() -> None:
    class InvalidUsernameClient(FakeTelegramClient):
        async def __call__(self, request: Any) -> Any:
            if isinstance(request, functions.account.UpdateUsernameRequest):
                raise errors.UsernameInvalidError(request=request)
            return await super().__call__(request)

    async with _account_app(client_class=InvalidUsernameClient) as (
        app,
        _manager,
        runtime,
        _client,
        _account,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.put(
                _url(runtime, "username"),
                headers=AUTH_HEADERS,
                json={"username": "valid_name"},
            )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_occupied_username_returns_409() -> None:
    account = _authorized_account()
    account.occupied_usernames.add("taken_name")
    async with _account_app(account=account) as (app, _manager, runtime, _client, _account):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.put(
                _url(runtime, "username"),
                headers=AUTH_HEADERS,
                json={"username": "taken_name"},
            )

    assert response.status_code == 409
    assert account.username == "old_name"


@pytest.mark.asyncio
async def test_password_is_installed_on_an_account_without_2fa() -> None:
    account = _authorized_account()
    account.password = None
    account.password_hint = None
    async with _account_app(account=account) as (app, _manager, runtime, _client, _account):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.put(
                _url(runtime, "password"),
                headers=AUTH_HEADERS,
                json={"new_password": "new_secret"},
            )

    assert response.status_code == 200
    assert response.json() == {"changed": True}
    assert account.password == "new_secret"
    assert response.text.find("new_secret") == -1


@pytest.mark.asyncio
async def test_wrong_current_password_returns_400_and_keeps_the_account() -> None:
    account = _authorized_account()
    account.set_password("old_secret")
    async with _account_app(account=account) as (app, _manager, runtime, _client, _account):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.put(
                _url(runtime, "password"),
                headers=AUTH_HEADERS,
                json={"current_password": "wrong_secret", "new_password": "new_secret"},
            )

    assert response.status_code == 400
    assert response.status_code != 401
    assert account.password == "old_secret"


@pytest.mark.asyncio
async def test_current_password_is_required_when_2fa_is_enabled() -> None:
    account = _authorized_account()
    account.set_password("old_secret")
    async with _account_app(account=account) as (app, _manager, runtime, _client, _account):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.put(
                _url(runtime, "password"),
                headers=AUTH_HEADERS,
                json={"new_password": "new_secret"},
            )

    assert response.status_code == 400
    assert account.password == "old_secret"


@pytest.mark.asyncio
async def test_password_change_preserves_the_existing_hint() -> None:
    account = _authorized_account()
    account.set_password("old_secret", hint="любимый кот")
    async with _account_app(account=account) as (app, _manager, runtime, _client, _account):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.put(
                _url(runtime, "password"),
                headers=AUTH_HEADERS,
                json={"current_password": "old_secret", "new_password": "new_secret"},
            )

    assert response.status_code == 200
    assert account.password == "new_secret"
    assert account.password_hint == "любимый кот"


@pytest.mark.asyncio
async def test_empty_new_password_is_422_without_echoing_input() -> None:
    account = _authorized_account()
    async with _account_app(account=account) as (app, _manager, runtime, _client, _account):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.put(
                _url(runtime, "password"),
                headers=AUTH_HEADERS,
                json={"new_password": ""},
            )

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail"}
    for error in body["detail"]:
        assert set(error) == {"loc", "msg"}
    assert account.password_edits == []


@pytest.mark.asyncio
async def test_malformed_json_does_not_return_the_request_body() -> None:
    leaked = "super_secret_password_123"
    async with _account_app() as (app, _manager, runtime, _client, account):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.put(
                _url(runtime, "password"),
                headers={**AUTH_HEADERS, "Content-Type": "application/json"},
                content=f'{{"new_password": "{leaked}"',
            )

    assert response.status_code == 422
    assert leaked not in response.text
    assert '"input"' not in response.text
    assert '"ctx"' not in response.text
    assert '"body":' not in response.text
    assert account.password_edits == []


@pytest.mark.asyncio
async def test_another_owner_gets_404_before_telegram() -> None:
    async with _account_app(auth_user_id=uuid4()) as (app, _manager, runtime, client, _account):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            state = await api.get(_url(runtime, "password"), headers=AUTH_HEADERS)
            username = await api.put(
                _url(runtime, "username"),
                headers=AUTH_HEADERS,
                json={"username": "new_name"},
            )

    assert state.status_code == 404
    assert username.status_code == 404
    assert client.requests == []
    assert client.connect_calls == 0


@pytest.mark.asyncio
async def test_a_dead_session_is_428_and_never_401() -> None:
    account = _authorized_account()
    account.authorized = False
    async with _account_app(account=account) as (app, _manager, runtime, _client, _account):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            state = await api.get(_url(runtime, "password"), headers=AUTH_HEADERS)
            password = await api.put(
                _url(runtime, "password"),
                headers=AUTH_HEADERS,
                json={"new_password": "new_secret"},
            )

    assert state.status_code == 428
    assert password.status_code == 428
    assert state.status_code != 401
    assert password.status_code != 401
    assert "повторная привязка" in state.json()["detail"]


@pytest.mark.asyncio
async def test_flood_wait_returns_429_with_the_seconds() -> None:
    class FloodClient(FakeTelegramClient):
        async def edit_2fa(
            self,
            current_password: str | None = None,
            new_password: str | None = None,
            *,
            hint: str = "",
        ) -> bool:
            raise errors.FloodWaitError(request=None, capture=17)

    async with _account_app(client_class=FloodClient) as (
        app,
        _manager,
        runtime,
        _client,
        _account,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.put(
                _url(runtime, "password"),
                headers=AUTH_HEADERS,
                json={"new_password": "new_secret"},
            )

    assert response.status_code == 429
    assert "17" in response.json()["detail"]


class _StuckDisconnectClient(FakeTelegramClient):
    def __init__(self, account: FakeTelegramAccount) -> None:
        super().__init__(account)
        self.release = asyncio.Event()

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        await self.release.wait()
        self.connected = False


@pytest.mark.asyncio
async def test_a_pending_teardown_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mimic42.core.agent_runtime.STOP_STEP_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr("mimic42.core.agent_runtime.TELEGRAM_TEARDOWN_WAIT_SECONDS", 0.05)
    async with _account_app(client_class=_StuckDisconnectClient) as (
        app,
        manager,
        runtime,
        client,
        _account,
    ):
        assert isinstance(client, _StuckDisconnectClient)
        await manager.start_agent(runtime.config.agent_id)
        await manager.stop_agent(runtime.config.agent_id)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
                response = await api.get(_url(runtime, "password"), headers=AUTH_HEADERS)
        finally:
            client.release.set()
            await asyncio.sleep(0)

    assert response.status_code == 409
