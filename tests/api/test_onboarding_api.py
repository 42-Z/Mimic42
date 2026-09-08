from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.config import Settings
from mimic42.core.onboarding import (
    AgentOnboardingService,
    InMemoryOnboardingRepository,
    TelegramAuthClientFactory,
)
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier


class FakeTelegramAuthClient:
    def __init__(self, *, requires_password: bool = False) -> None:
        self.requires_password = requires_password
        self.connected = False
        self.session_string = "temporary-session"
        self.sent_phone: str | None = None

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def send_code_request(self, phone: str) -> dict[str, str]:
        self.sent_phone = phone
        return {"phone_code_hash": "hash-123", "type": "app"}

    async def sign_in(
        self,
        *,
        phone: str | None = None,
        code: str | None = None,
        phone_code_hash: str | None = None,
        password: str | None = None,
    ) -> object:
        if self.requires_password and password is None:
            raise RuntimeError("2FA password required")
        self.session_string = "authorized-session"
        return {"phone": phone, "code": code, "phone_code_hash": phone_code_hash}

    def save_session(self) -> str:
        return self.session_string


class FakeTelegramAuthClientFactory(TelegramAuthClientFactory):
    def __init__(self, client: FakeTelegramAuthClient) -> None:
        self.client = client
        self.built_with: tuple[int, str] | None = None

    def build(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
    ) -> FakeTelegramAuthClient:
        self.built_with = (api_id, api_hash)
        self.client.session_string = session_string or self.client.session_string
        return self.client


@pytest.mark.asyncio
async def test_onboarding_creates_login_flow_verifies_code_and_finalizes_agent() -> None:
    service = AgentOnboardingService(
        repository=InMemoryOnboardingRepository(),
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAuthClient()),
    )
    owner_id = uuid4()
    app = create_app(onboarding_service=service, auth_verifier=FakeAuthVerifier(owner_id))

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        start_response = await client.post(
            "/api/v1/onboarding/telegram",
            headers=AUTH_HEADERS,
            json={
                "api_id": 12345,
                "api_hash": "api-hash",
                "phone_number": "+79990000000",
            },
        )
        onboarding_id = UUID(start_response.json()["onboarding_id"])

        verify_response = await client.post(
            f"/api/v1/onboarding/{onboarding_id}/telegram/code",
            headers=AUTH_HEADERS,
            json={"code": "12345"},
        )

        finalize_response = await client.post(
            f"/api/v1/onboarding/{onboarding_id}/agent",
            headers=AUTH_HEADERS,
            json={
                "name": "Personal Mimic",
                "soul_prompt": "Writes short calm replies.",
            },
        )

    assert start_response.status_code == 201
    assert start_response.json()["authorization_status"] == "code_requested"
    assert "api_hash" not in start_response.text
    assert "phone_code_hash" not in start_response.text

    assert verify_response.status_code == 200
    assert verify_response.json()["authorization_status"] == "authorized"

    assert finalize_response.status_code == 201
    assert finalize_response.json() == {
        "agent_id": str(onboarding_id),
        "owner_id": str(owner_id),
        "state": "stopped",
    }


@pytest.mark.asyncio
async def test_onboarding_uses_deployment_telegram_app_when_none_supplied() -> None:
    factory = FakeTelegramAuthClientFactory(FakeTelegramAuthClient())
    service = AgentOnboardingService(
        repository=InMemoryOnboardingRepository(),
        telegram_factory=factory,
    )
    owner_id = uuid4()
    app = create_app(
        onboarding_service=service,
        auth_verifier=FakeAuthVerifier(owner_id),
        settings=Settings(telegram_api_id=777, telegram_api_hash="deployment-hash"),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/onboarding/telegram",
            headers=AUTH_HEADERS,
            json={"phone_number": "+79990000000"},
        )

    assert response.status_code == 201
    assert response.json()["authorization_status"] == "code_requested"
    assert factory.built_with == (777, "deployment-hash")


@pytest.mark.asyncio
async def test_onboarding_fails_when_no_telegram_app_configured() -> None:
    service = AgentOnboardingService(
        repository=InMemoryOnboardingRepository(),
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAuthClient()),
    )
    app = create_app(
        onboarding_service=service,
        auth_verifier=FakeAuthVerifier(uuid4()),
        settings=Settings(telegram_api_id=None, telegram_api_hash=None),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/onboarding/telegram",
            headers=AUTH_HEADERS,
            json={"phone_number": "+79990000000"},
        )

    assert response.status_code == 503
    assert "TELEGRAM_API_ID" in response.json()["detail"]


@pytest.mark.asyncio
async def test_verify_code_reports_phone_without_telegram_account() -> None:
    from telethon.errors import PhoneNumberUnoccupiedError

    class UnoccupiedPhoneClient(FakeTelegramAuthClient):
        async def sign_in(self, **kwargs: object) -> object:
            raise PhoneNumberUnoccupiedError(request=None)

    service = AgentOnboardingService(
        repository=InMemoryOnboardingRepository(),
        telegram_factory=FakeTelegramAuthClientFactory(UnoccupiedPhoneClient()),
    )
    app = create_app(
        onboarding_service=service,
        auth_verifier=FakeAuthVerifier(uuid4()),
        settings=Settings(telegram_api_id=777, telegram_api_hash="deployment-hash"),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        start_response = await client.post(
            "/api/v1/onboarding/telegram",
            headers=AUTH_HEADERS,
            json={"phone_number": "+79990000000"},
        )
        onboarding_id = UUID(start_response.json()["onboarding_id"])

        verify_response = await client.post(
            f"/api/v1/onboarding/{onboarding_id}/telegram/code",
            headers=AUTH_HEADERS,
            json={"code": "12345"},
        )

    assert verify_response.status_code == 400
    assert verify_response.json()["detail"] == "Пользователя с таким номером нет в Telegram."
