from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import _telegram_login_http_error, create_app
from mimic42.config import Settings
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.agent_store import AgentRecord, InMemoryAgentStore
from mimic42.core.onboarding import (
    AgentOnboardingService,
    InMemoryOnboardingRepository,
    OnboardingPublicStatus,
    OnboardingSession,
    TelegramLoginStatus,
    TelegramPasswordRequiredError,
)
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramAuthClientFactory
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier


def test_telegram_login_value_error_does_not_expose_internal_message() -> None:
    internal_message = "Cannot find any entity corresponding to the current user"

    translated = _telegram_login_http_error(ValueError(internal_message))

    assert translated is not None
    assert translated.status_code == 400
    assert translated.detail == (
        "Не удалось обработать данные Telegram. Проверьте их и попробуйте снова."
    )
    assert internal_message not in str(translated.detail)


@pytest.mark.asyncio
async def test_onboarding_creates_login_flow_verifies_code_and_finalizes_agent() -> None:
    service = AgentOnboardingService(
        repository=InMemoryOnboardingRepository(),
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
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
    factory = FakeTelegramAuthClientFactory(FakeTelegramAccount())
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
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
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
async def test_onboarding_cannot_replace_a_completed_agents_telegram_account() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="old-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="old-session",
            completed_agent_id=agent_id,
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
    )
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
            json={
                "onboarding_id": str(agent_id),
                "phone_number": "+79991111111",
            },
        )

    assert response.status_code == 409
    assert "перепривязк" in response.json()["detail"].lower()
    unchanged = await repository.get(agent_id)
    assert unchanged.phone_number == "+79990000000"
    assert unchanged.session_secret == "old-session"


@pytest.mark.asyncio
async def test_verify_code_reports_phone_without_telegram_account() -> None:
    from telethon.errors import PhoneNumberUnoccupiedError

    from mimic42.testing.telegram.auth_client import FakeTelegramAuthClient

    class UnoccupiedPhoneAuthClient(FakeTelegramAuthClient):
        async def sign_in(self, **kwargs: object) -> object:
            raise PhoneNumberUnoccupiedError(request=None)

    class UnoccupiedPhoneAuthClientFactory(FakeTelegramAuthClientFactory):
        def build(
            self,
            *,
            api_id: int,
            api_hash: str,
            session_string: str | None = None,
        ) -> UnoccupiedPhoneAuthClient:
            self.built_with = (api_id, api_hash)
            return UnoccupiedPhoneAuthClient(self._account)

    service = AgentOnboardingService(
        repository=InMemoryOnboardingRepository(),
        telegram_factory=UnoccupiedPhoneAuthClientFactory(FakeTelegramAccount()),
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


class PasswordRequiredOnboardingService(AgentOnboardingService):
    """Стаб сервиса: код принят, но Telethon требует пароль 2FA."""

    def __init__(self, owner_id: UUID) -> None:
        self._owner_id = owner_id

    async def get_status(self, onboarding_id: UUID) -> OnboardingPublicStatus:
        return OnboardingPublicStatus(
            onboarding_id=onboarding_id,
            owner_id=self._owner_id,
            authorization_status=TelegramLoginStatus.CODE_REQUESTED,
            phone_number="+79990000000",
        )

    async def verify_telegram_code(
        self, onboarding_id: UUID, verification: object
    ) -> OnboardingPublicStatus:
        raise TelegramPasswordRequiredError


@pytest.mark.asyncio
async def test_verify_code_reports_2fa_requirement_in_russian() -> None:
    owner_id = uuid4()
    app = create_app(
        onboarding_service=PasswordRequiredOnboardingService(owner_id),
        auth_verifier=FakeAuthVerifier(owner_id),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/onboarding/{uuid4()}/telegram/code",
            headers=AUTH_HEADERS,
            json={"code": "12345"},
        )

    assert response.status_code == 428
    assert "двухфакторная" in response.json()["detail"]


@pytest.mark.asyncio
async def test_finalize_agent_reports_incomplete_authorization_in_russian() -> None:
    owner_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.NOT_STARTED,
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
    )
    app = create_app(onboarding_service=service, auth_verifier=FakeAuthVerifier(owner_id))

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/onboarding/{onboarding_id}/agent",
            headers=AUTH_HEADERS,
            json={"name": "Mimic", "soul_prompt": "Short replies"},
        )

    assert response.status_code == 409
    assert "авторизац" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_finalize_agent_refuses_to_take_over_a_foreign_agent() -> None:
    """Issue #95: поддельная онбординг-сессия с id чужого агента не должна
    переприсваивать агента вместе с его Telegram-сессией и характером."""
    owner_id = uuid4()
    foreign_owner_id = uuid4()
    agent_id = uuid4()
    store = InMemoryAgentStore(
        agents=[
            AgentRecord(
                agent_id=agent_id,
                owner_id=foreign_owner_id,
                name="Легальный агент",
                state=AgentRuntimeState.STOPPED,
            )
        ]
    )
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="forged-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="forged-session",
            name="Хакер",
            soul_prompt="Характер взломщика",
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
        agent_store=store,
    )
    app = create_app(
        onboarding_service=service,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/onboarding/{agent_id}/agent",
            headers=AUTH_HEADERS,
            json={"name": "Хакер", "soul_prompt": "Характер взломщика"},
        )

    assert response.status_code == 409
    assert "занят другим агентом" in response.json()["detail"]
    assert await store.list_agents(owner_id=owner_id) == []
    kept = await store.list_agents(owner_id=foreign_owner_id)
    assert [(agent.agent_id, agent.name) for agent in kept] == [(agent_id, "Легальный агент")]


@pytest.mark.asyncio
async def test_finalize_agent_can_be_retried_by_its_owner() -> None:
    """Гвард переприсвоения не должен ломать повторную финализацию: её делает
    тот же пользователь, когда ответ предыдущего запроса не дошёл."""
    owner_id = uuid4()
    agent_id = uuid4()
    store = InMemoryAgentStore()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="api-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="session",
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
        agent_store=store,
    )
    app = create_app(
        onboarding_service=service,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        first = await client.post(
            f"/api/v1/onboarding/{agent_id}/agent",
            headers=AUTH_HEADERS,
            json={"name": "Mimic", "soul_prompt": "Short replies"},
        )
        second = await client.post(
            f"/api/v1/onboarding/{agent_id}/agent",
            headers=AUTH_HEADERS,
            json={"name": "Mimic", "soul_prompt": "Short replies"},
        )

    assert first.status_code == 201
    assert second.status_code == 201
    agents = await store.list_agents(owner_id=owner_id)
    assert [agent.agent_id for agent in agents] == [agent_id]
