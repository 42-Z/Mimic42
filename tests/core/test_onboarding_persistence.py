from __future__ import annotations

import logging
from uuid import UUID, uuid4

import pytest
from telethon.errors import FloodWaitError

from mimic42.core.agent_runtime import AgentRuntimeState, TelegramProxyConfig
from mimic42.core.agent_store import InMemoryAgentStore
from mimic42.core.onboarding import (
    AgentOnboardingService,
    AgentProfileInput,
    InMemoryOnboardingRepository,
    OnboardingOwnershipError,
    OnboardingPublicStatus,
    OnboardingSession,
    TelegramAuthClient,
    TelegramCodeVerification,
    TelegramCredentials,
    TelegramLoginStatus,
)
from mimic42.testing.telegram import (
    FakeTelegramAccount,
    FakeTelegramAuthClient,
    FakeTelegramAuthClientFactory,
)


def _fake_telegram_factory() -> FakeTelegramAuthClientFactory:
    return FakeTelegramAuthClientFactory(FakeTelegramAccount())


class UnusedTelegramFactory:
    def build(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
        proxy: TelegramProxyConfig | None = None,
    ) -> TelegramAuthClient:
        raise AssertionError("Telegram factory should not be used while finalizing an agent")


@pytest.mark.asyncio
async def test_finalize_agent_persists_agent_and_telegram_session() -> None:
    owner_id = uuid4()
    onboarding_id = uuid4()
    onboarding_repository = InMemoryOnboardingRepository()
    agent_store = InMemoryAgentStore()
    await onboarding_repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="encrypted-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="encrypted-session",
        )
    )
    service = AgentOnboardingService(
        repository=onboarding_repository,
        telegram_factory=UnusedTelegramFactory(),
        agent_store=agent_store,
    )

    status = await service.finalize_agent(
        onboarding_id,
        AgentProfileInput(name="Mimic", soul_prompt="Short replies"),
    )

    assert status.agent_id == onboarding_id
    assert status.state is AgentRuntimeState.STOPPED
    # Черновик помечен завершённым на сервере: клиентский апдейт мог упасть.
    completed = await onboarding_repository.get(onboarding_id)
    assert completed.completed_agent_id == onboarding_id
    persisted = await agent_store.get_runtime_config(onboarding_id)
    assert persisted.owner_id == owner_id
    assert persisted.telegram_api_hash == "encrypted-hash"
    assert persisted.telegram_session_string == "encrypted-session"
    from mimic42.core.onboarding import load_default_system_prompt

    assert persisted.system_prompt == load_default_system_prompt()
    assert persisted.soul_prompt == "Short replies"


async def _started_onboarding(
    service: AgentOnboardingService, owner_id: UUID, phone_number: str
) -> OnboardingPublicStatus:
    started = await service.request_telegram_code(
        TelegramCredentials(
            owner_id=owner_id,
            api_id=12345,
            api_hash="hash",
            phone_number=phone_number,
        )
    )
    return started


@pytest.mark.asyncio
async def test_verify_telegram_code_stores_account_username() -> None:
    owner_id = uuid4()
    repository = InMemoryOnboardingRepository()
    account = FakeTelegramAccount()
    account.script_code("12345")
    account.username = "mimic_user"
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(account),
    )
    started = await _started_onboarding(service, owner_id, "+79990000003")

    status = await service.verify_telegram_code(
        started.onboarding_id, TelegramCodeVerification(code="12345")
    )

    assert status.authorization_status is TelegramLoginStatus.AUTHORIZED
    session = await repository.get(started.onboarding_id)
    assert session.username == "mimic_user"


@pytest.mark.asyncio
async def test_verify_telegram_code_without_account_username_stores_none() -> None:
    owner_id = uuid4()
    repository = InMemoryOnboardingRepository()
    account = FakeTelegramAccount()
    account.script_code("12345")
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(account),
    )
    started = await _started_onboarding(service, owner_id, "+79990000004")

    status = await service.verify_telegram_code(
        started.onboarding_id, TelegramCodeVerification(code="12345")
    )

    assert status.authorization_status is TelegramLoginStatus.AUTHORIZED
    session = await repository.get(started.onboarding_id)
    assert session.username is None


@pytest.mark.asyncio
async def test_verify_telegram_code_with_2fa_password_stores_account_username() -> None:
    owner_id = uuid4()
    repository = InMemoryOnboardingRepository()
    account = FakeTelegramAccount()
    account.script_code("12345")
    account.require_password("secret")
    account.username = "mimic_user"
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(account),
    )
    started = await _started_onboarding(service, owner_id, "+79990000005")

    password_required = await service.verify_telegram_code(
        started.onboarding_id, TelegramCodeVerification(code="12345")
    )
    assert password_required.authorization_status is TelegramLoginStatus.PASSWORD_REQUIRED

    status = await service.verify_telegram_code(
        started.onboarding_id, TelegramCodeVerification(code="12345", password="secret")
    )

    assert status.authorization_status is TelegramLoginStatus.AUTHORIZED
    session = await repository.get(started.onboarding_id)
    assert session.username == "mimic_user"


@pytest.mark.asyncio
async def test_verify_telegram_code_survives_get_me_failure() -> None:
    """Сбой получения @username не должен ломать уже успешный вход."""

    owner_id = uuid4()
    repository = InMemoryOnboardingRepository()
    account = FakeTelegramAccount()
    account.script_code("12345")

    class FailingGetMeClient(FakeTelegramAuthClient):
        async def get_me(self) -> object:
            raise RuntimeError("Telegram unavailable")

    class FailingGetMeFactory(FakeTelegramAuthClientFactory):
        def build(
            self,
            *,
            api_id: int,
            api_hash: str,
            session_string: str | None = None,
            proxy: TelegramProxyConfig | None = None,
        ) -> FakeTelegramAuthClient:
            return FailingGetMeClient(self._account)

    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FailingGetMeFactory(account),
    )
    started = await _started_onboarding(service, owner_id, "+79990000006")

    status = await service.verify_telegram_code(
        started.onboarding_id, TelegramCodeVerification(code="12345")
    )

    assert status.authorization_status is TelegramLoginStatus.AUTHORIZED
    session = await repository.get(started.onboarding_id)
    assert session.username is None


@pytest.mark.asyncio
async def test_two_onboarding_runs_create_two_distinct_sessions() -> None:
    owner_id = uuid4()
    repository = InMemoryOnboardingRepository()
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
    )
    credentials = TelegramCredentials(
        owner_id=owner_id,
        api_id=12345,
        api_hash="hash",
        phone_number="+79990000000",
    )

    first = await service.request_telegram_code(credentials)
    second = await service.request_telegram_code(credentials)

    assert first.onboarding_id != second.onboarding_id
    assert len(repository._sessions) == 2


@pytest.mark.asyncio
async def test_request_code_with_existing_onboarding_id_reuses_draft() -> None:
    owner_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.NOT_STARTED,
            name="Mimic",
            soul_prompt="Short replies",
            settings={"enabled_tools": ["send_text_message"]},
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
    )
    credentials = TelegramCredentials(
        owner_id=owner_id,
        api_id=12345,
        api_hash="hash",
        phone_number="+79990000001",
    )

    status = await service.request_telegram_code(credentials, onboarding_id=onboarding_id)

    assert status.onboarding_id == onboarding_id
    reused = await repository.get(onboarding_id)
    assert reused.name == "Mimic"
    assert reused.soul_prompt == "Short replies"
    assert reused.settings == {"enabled_tools": ["send_text_message"]}
    assert reused.phone_number == "+79990000001"


@pytest.mark.asyncio
async def test_request_code_for_foreign_onboarding_is_rejected() -> None:
    owner_id = uuid4()
    stranger_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=stranger_id,
            authorization_status=TelegramLoginStatus.NOT_STARTED,
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
    )
    credentials = TelegramCredentials(
        owner_id=owner_id,
        api_id=12345,
        api_hash="hash",
        phone_number="+79990000002",
    )

    with pytest.raises(OnboardingOwnershipError):
        await service.request_telegram_code(credentials, onboarding_id=onboarding_id)


class FloodedAuthClient(FakeTelegramAuthClient):
    """Подделка, у которой запрос кода упирается во флуд-лимит Telegram."""

    def __init__(self, account: FakeTelegramAccount, seconds: int) -> None:
        super().__init__(account)
        self._seconds = seconds

    async def send_code_request(self, phone: str) -> object:
        raise FloodWaitError(request=None, capture=self._seconds)


class FloodedAuthFactory:
    def __init__(self, seconds: int) -> None:
        self._seconds = seconds

    def build(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
        proxy: TelegramProxyConfig | None = None,
    ) -> TelegramAuthClient:
        return FloodedAuthClient(FakeTelegramAccount(), self._seconds)


async def _logged(
    caplog: pytest.LogCaptureFixture,
    level: int,
    service: AgentOnboardingService,
    owner_id: UUID,
    phone_number: str,
) -> str:
    """Запрашивает код под caplog и возвращает весь собранный лог-текст."""
    with caplog.at_level(level, logger="mimic42.onboarding"):
        await service.request_telegram_code(
            TelegramCredentials(
                owner_id=owner_id,
                api_id=12345,
                api_hash="hash",
                phone_number=phone_number,
            )
        )
    return caplog.text


@pytest.mark.asyncio
async def test_failed_code_request_is_logged_with_flood_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Флуд-отказ должен попадать в лог с секундами, но без сырого номера."""
    service = AgentOnboardingService(telegram_factory=FloodedAuthFactory(37))

    with caplog.at_level(logging.WARNING, logger="mimic42.onboarding"):
        with pytest.raises(FloodWaitError):
            await service.request_telegram_code(
                TelegramCredentials(
                    owner_id=uuid4(),
                    api_id=12345,
                    api_hash="hash",
                    phone_number="+79991234567",
                )
            )

    text = caplog.text
    assert "Запрос кода Telegram не удался" in text
    assert "FloodWaitError" in text
    assert "37 seconds" in text
    assert "api_id=12345" in text
    assert "+79991234567" not in text
    assert "+799******67" in text


@pytest.mark.asyncio
async def test_successful_code_request_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    service = AgentOnboardingService(
        repository=InMemoryOnboardingRepository(),
        telegram_factory=_fake_telegram_factory(),
    )
    owner_id = uuid4()

    text = await _logged(caplog, logging.INFO, service, owner_id, "+79991234567")

    assert "Код Telegram отправлен" in text
    assert "api_id=12345" in text
    assert "+79991234567" not in text
    assert "+799******67" in text


@pytest.mark.asyncio
async def test_failed_sign_in_is_logged_with_masked_phone(
    caplog: pytest.LogCaptureFixture,
) -> None:
    account = FakeTelegramAccount()
    account.script_code("11111")
    repository = InMemoryOnboardingRepository()
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(account),
    )
    owner_id = uuid4()
    started = await service.request_telegram_code(
        TelegramCredentials(
            owner_id=owner_id,
            api_id=12345,
            api_hash="hash",
            phone_number="+79991234567",
        )
    )

    with caplog.at_level(logging.WARNING, logger="mimic42.onboarding"):
        with pytest.raises(ValueError):
            await service.verify_telegram_code(
                started.onboarding_id,
                TelegramCodeVerification(code="22222"),
            )

    text = caplog.text
    assert "Подтверждение кода Telegram не удалось" in text
    assert "+79991234567" not in text
    assert "+799******67" in text
