from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from mimic42.core.agent_runtime import (
    DEFAULT_LLM_MODEL,
    AgentRuntimeConfig,
    AgentRuntimeState,
    AgentStatus,
)
from mimic42.core.agent_store import AgentStore


def load_default_system_prompt() -> str:
    root = Path(__file__).resolve().parents[3]
    path = root / "BASE_SYSTEM_PROMPT.txt"
    if path.exists():
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return (
        "Ты — умный ИИ-агент, который общается в Telegram от имени пользователя. "
        "Твоя задача — поддерживать живой, естественный диалог, как это делает человек. "
        "Отвечай кратко и по делу. Используй неформальный, дружелюбный тон. "
        "Не раскрывай, что ты ИИ, если тебя прямо не спросят. "
        "Помни контекст разговора и учитывай предыдущие сообщения."
    )


DEFAULT_SYSTEM_PROMPT = load_default_system_prompt()


class TelegramLoginStatus(StrEnum):
    NOT_STARTED = "not_started"
    CODE_REQUESTED = "code_requested"
    PASSWORD_REQUIRED = "password_required"
    AUTHORIZED = "authorized"
    ERROR = "error"


class TelegramCredentials(BaseModel):
    owner_id: UUID
    api_id: int = Field(gt=0)
    api_hash: str = Field(min_length=1)
    phone_number: str = Field(min_length=5)
    onboarding_id: UUID | None = Field(default=None)


class TelegramCodeVerification(BaseModel):
    code: str = Field(min_length=1)
    password: str | None = Field(default=None, min_length=1)


class AgentProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    soul_prompt: str = Field(min_length=1, max_length=20_000)


class OnboardingSession(BaseModel):
    onboarding_id: UUID
    owner_id: UUID
    api_id: int | None = None
    api_hash_secret: str | None = None
    phone_number: str | None = None
    authorization_status: TelegramLoginStatus
    phone_code_hash_secret: str | None = None
    session_secret: str | None = None
    name: str | None = None
    soul_prompt: str | None = None
    completed_agent_id: UUID | None = None


class OnboardingPublicStatus(BaseModel):
    onboarding_id: UUID
    owner_id: UUID
    authorization_status: TelegramLoginStatus
    phone_number: str | None = None


class SecretCipher(Protocol):
    def encrypt(self, value: str) -> str: ...

    def decrypt(self, value: str) -> str: ...


class PlainTextCipher:
    """Development-only cipher used when a deployment key is not configured."""

    def encrypt(self, value: str) -> str:
        return value

    def decrypt(self, value: str) -> str:
        return value


class OnboardingRepository(Protocol):
    async def save(self, session: OnboardingSession) -> None: ...

    async def get(self, onboarding_id: UUID) -> OnboardingSession: ...

    async def get_for_agent(self, agent_id: UUID) -> OnboardingSession: ...


class InMemoryOnboardingRepository:
    def __init__(self) -> None:
        self._sessions: dict[UUID, OnboardingSession] = {}

    async def save(self, session: OnboardingSession) -> None:
        self._sessions[session.onboarding_id] = session.model_copy(deep=True)

    async def get(self, onboarding_id: UUID) -> OnboardingSession:
        try:
            return self._sessions[onboarding_id].model_copy(deep=True)
        except KeyError as exc:
            raise OnboardingNotFoundError(onboarding_id) from exc

    async def get_for_agent(self, agent_id: UUID) -> OnboardingSession:
        for session in self._sessions.values():
            if session.onboarding_id == agent_id or session.completed_agent_id == agent_id:
                return session.model_copy(deep=True)
        raise OnboardingNotFoundError(agent_id)


class OnboardingNotFoundError(KeyError):
    def __init__(self, onboarding_id: UUID) -> None:
        super().__init__("Сессия онбординга не найдена")
        self.onboarding_id = onboarding_id


class OnboardingOwnershipError(PermissionError):
    def __init__(self, onboarding_id: UUID) -> None:
        super().__init__("Сессия онбординга принадлежит другому пользователю")
        self.onboarding_id = onboarding_id


class OnboardingAlreadyCompletedError(ValueError):
    def __init__(self, onboarding_id: UUID) -> None:
        super().__init__("Онбординг уже завершен; используйте перепривязку Telegram")
        self.onboarding_id = onboarding_id


class TelegramRebindUnavailableError(ValueError):
    """Сохранённых данных недостаточно для повторной авторизации Telegram."""


class TelegramPasswordRequiredError(RuntimeError):
    pass


class TelegramAuthClient(Protocol):
    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def send_code_request(self, phone: str) -> object: ...

    async def sign_in(
        self,
        *,
        phone: str | None = None,
        code: str | None = None,
        phone_code_hash: str | None = None,
        password: str | None = None,
    ) -> object: ...

    def save_session(self) -> str: ...


class TelegramAuthClientFactory(Protocol):
    def build(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
    ) -> TelegramAuthClient: ...


class AgentOnboardingService:
    def __init__(
        self,
        *,
        repository: OnboardingRepository | None = None,
        telegram_factory: TelegramAuthClientFactory,
        cipher: SecretCipher | None = None,
        agent_store: AgentStore | None = None,
    ) -> None:
        self._repository = repository or InMemoryOnboardingRepository()
        self._telegram_factory = telegram_factory
        self._cipher = cipher or PlainTextCipher()
        self._agent_store = agent_store
        self._llm_model = DEFAULT_LLM_MODEL

    async def request_telegram_code(
        self,
        credentials: TelegramCredentials,
        *,
        onboarding_id: UUID | None = None,
        allow_completed: bool = False,
    ) -> OnboardingPublicStatus:
        phone_number = credentials.phone_number
        if onboarding_id is not None:
            existing = await self._repository.get(onboarding_id)
            if existing.owner_id != credentials.owner_id:
                raise OnboardingOwnershipError(onboarding_id)
            if existing.completed_agent_id is not None and not allow_completed:
                raise OnboardingAlreadyCompletedError(onboarding_id)
            name = existing.name
            soul_prompt = existing.soul_prompt
            # Метка завершения переживает перезапись строки: иначе rebind-сессия
            # агента снова стала бы черновиком мастера онбординга.
            completed_agent_id = existing.completed_agent_id
        else:
            onboarding_id = uuid4()
            name = None
            soul_prompt = None
            completed_agent_id = None

        client = self._telegram_factory.build(
            api_id=credentials.api_id,
            api_hash=credentials.api_hash,
        )
        await client.connect()
        try:
            sent_code = await client.send_code_request(phone_number)
            session_string = client.save_session()
        finally:
            await client.disconnect()

        phone_code_hash = _read_attr(sent_code, "phone_code_hash")
        session = OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=credentials.owner_id,
            api_id=credentials.api_id,
            api_hash_secret=self._cipher.encrypt(credentials.api_hash),
            phone_number=phone_number,
            authorization_status=TelegramLoginStatus.CODE_REQUESTED,
            phone_code_hash_secret=self._cipher.encrypt(phone_code_hash),
            session_secret=self._cipher.encrypt(session_string),
            name=name,
            soul_prompt=soul_prompt,
            completed_agent_id=completed_agent_id,
        )
        await self._repository.save(session)
        return _public_status(session)

    async def start_rebind(self, agent_id: UUID, *, owner_id: UUID) -> OnboardingPublicStatus:
        """Начать повторный вход того же Telegram-аккаунта.

        Данные агента не меняются: номер и Telegram-приложение берутся из его
        сохранённой строки, новой сессии нужен только код подтверждения.
        """
        try:
            existing = await self._repository.get_for_agent(agent_id)
        except OnboardingNotFoundError:
            if self._agent_store is None:
                raise TelegramRebindUnavailableError(
                    "У агента нет сохранённой Telegram-сессии — перепривязка недоступна"
                ) from None
            try:
                stored = await self._agent_store.get_telegram_rebind_credentials(agent_id)
            except (KeyError, ValueError):
                raise TelegramRebindUnavailableError(
                    "У агента нет сохранённой Telegram-сессии — перепривязка недоступна"
                ) from None
            if stored.owner_id != owner_id:
                raise OnboardingOwnershipError(agent_id) from None
            existing = OnboardingSession(
                onboarding_id=agent_id,
                owner_id=stored.owner_id,
                api_id=stored.api_id,
                api_hash_secret=stored.api_hash_secret,
                phone_number=stored.phone_number,
                authorization_status=TelegramLoginStatus.AUTHORIZED,
                completed_agent_id=agent_id,
            )
            await self._repository.save(existing)
        if existing.owner_id != owner_id:
            raise OnboardingOwnershipError(existing.onboarding_id)
        if existing.completed_agent_id is None:
            existing.completed_agent_id = agent_id
            await self._repository.save(existing)
        if (
            existing.phone_number is None
            or existing.api_id is None
            or existing.api_hash_secret is None
        ):
            raise TelegramRebindUnavailableError(
                "У агента нет данных Telegram-сессии — перепривязка недоступна"
            )
        credentials = TelegramCredentials(
            owner_id=owner_id,
            api_id=existing.api_id,
            api_hash=self._cipher.decrypt(existing.api_hash_secret),
            phone_number=existing.phone_number,
        )
        # Старый AUTHORIZED нельзя оставлять пригодным для confirm, пока новый
        # код ещё запрашивается. Если Telegram недоступен, повторная попытка
        # начнёт flow заново, но применить прежнюю session string уже нельзя.
        existing.authorization_status = TelegramLoginStatus.NOT_STARTED
        existing.phone_code_hash_secret = None
        existing.session_secret = None
        await self._repository.save(existing)
        return await self.request_telegram_code(
            credentials,
            onboarding_id=existing.onboarding_id,
            allow_completed=True,
        )

    async def verify_telegram_code(
        self,
        onboarding_id: UUID,
        verification: TelegramCodeVerification,
    ) -> OnboardingPublicStatus:
        session = await self._repository.get(onboarding_id)
        if (
            session.api_id is None
            or session.api_hash_secret is None
            or session.phone_number is None
        ):
            raise TelegramAuthorizationIncompleteError(onboarding_id)
        client = self._telegram_factory.build(
            api_id=session.api_id,
            api_hash=self._cipher.decrypt(session.api_hash_secret),
            session_string=_decrypt_optional(self._cipher, session.session_secret),
        )
        await client.connect()
        try:
            try:
                if verification.password:
                    await client.sign_in(
                        password=verification.password,
                    )
                else:
                    await client.sign_in(
                        phone=session.phone_number,
                        code=verification.code,
                        phone_code_hash=_decrypt_optional(
                            self._cipher, session.phone_code_hash_secret
                        ),
                    )
            except TelegramPasswordRequiredError:
                session.authorization_status = TelegramLoginStatus.PASSWORD_REQUIRED
                session.session_secret = self._cipher.encrypt(client.save_session())
                await self._repository.save(session)
                return _public_status(session)

            session.authorization_status = TelegramLoginStatus.AUTHORIZED
            session.session_secret = self._cipher.encrypt(client.save_session())
        finally:
            await client.disconnect()

        await self._repository.save(session)
        return _public_status(session)

    async def get_status(self, onboarding_id: UUID) -> OnboardingPublicStatus:
        return _public_status(await self._repository.get(onboarding_id))

    async def finalize_agent(self, onboarding_id: UUID, profile: AgentProfileInput) -> AgentStatus:
        session = await self._repository.get(onboarding_id)
        if session.authorization_status is not TelegramLoginStatus.AUTHORIZED:
            raise TelegramAuthorizationIncompleteError(onboarding_id)

        session.name = profile.name
        session.soul_prompt = profile.soul_prompt
        await self._repository.save(session)

        if self._agent_store is not None:
            await self._agent_store.create_from_onboarding(session)
            # Черновик помечается завершённым на сервере, а не клиентом:
            # браузерный апдейт после финализации мог отвалиться, и мастер
            # подхватывал уже использованный черновик заново.
            session.completed_agent_id = session.onboarding_id
            await self._repository.save(session)

        return AgentStatus(
            agent_id=session.onboarding_id,
            owner_id=session.owner_id,
            state=AgentRuntimeState.STOPPED,
        )

    async def rebind_to_agent(
        self, onboarding_id: UUID, agent_id: UUID, *, owner_id: UUID
    ) -> AgentStatus:
        """Перенести авторизованную онбординг-сессию на существующего агента.

        Флоу перепривязки: Telegram-сессия обновляется, а имя, характер,
        память и настройки агента остаются прежними. Строка онбординга
        остаётся помеченной completed_agent_id и невидимой мастеру: она же
        будет переиспользована при следующей перепривязке.
        """
        session = await self._validated_rebind_session(onboarding_id, agent_id, owner_id=owner_id)
        if self._agent_store is None:
            raise RuntimeError("Хранилище агентов не настроено")
        await self._agent_store.rebind_telegram_session(agent_id, session)
        return AgentStatus(
            agent_id=agent_id,
            owner_id=session.owner_id,
            state=AgentRuntimeState.STOPPED,
        )

    async def validate_rebind_to_agent(
        self, onboarding_id: UUID, agent_id: UUID, *, owner_id: UUID
    ) -> None:
        """Validate a rebind before stopping the current runtime."""
        await self._validated_rebind_session(onboarding_id, agent_id, owner_id=owner_id)

    async def _validated_rebind_session(
        self, onboarding_id: UUID, agent_id: UUID, *, owner_id: UUID
    ) -> OnboardingSession:
        session = await self._repository.get(onboarding_id)
        if session.owner_id != owner_id:
            raise OnboardingOwnershipError(onboarding_id)
        if session.completed_agent_id != agent_id:
            # start_rebind всегда привязывает сессию к агенту, поэтому
            # расхождение означает, что сессия выдана для другого агента.
            raise OnboardingOwnershipError(onboarding_id)
        if session.authorization_status is not TelegramLoginStatus.AUTHORIZED:
            raise TelegramAuthorizationIncompleteError(onboarding_id)
        return session

    async def build_runtime_config(self, onboarding_id: UUID) -> AgentRuntimeConfig:
        session = await self._repository.get(onboarding_id)
        if not session.soul_prompt or session.api_id is None or session.api_hash_secret is None:
            raise TelegramAuthorizationIncompleteError(onboarding_id)

        return AgentRuntimeConfig(
            agent_id=session.onboarding_id,
            owner_id=session.owner_id,
            telegram_api_id=session.api_id,
            telegram_api_hash=self._cipher.decrypt(session.api_hash_secret),
            telegram_session_string=_decrypt_optional(self._cipher, session.session_secret),
            telegram_session_token=session.session_secret,
            llm_model=self._llm_model,
            system_prompt=load_default_system_prompt(),
            soul_prompt=session.soul_prompt,
            name=session.name or "AI",
        )


class TelegramAuthorizationIncompleteError(RuntimeError):
    def __init__(self, onboarding_id: UUID) -> None:
        super().__init__("Онбординг-сессия не готова: завершите авторизацию в Telegram.")
        self.onboarding_id = onboarding_id


def _public_status(session: OnboardingSession) -> OnboardingPublicStatus:
    return OnboardingPublicStatus(
        onboarding_id=session.onboarding_id,
        owner_id=session.owner_id,
        authorization_status=session.authorization_status,
        phone_number=session.phone_number,
    )


def _read_attr(value: object, name: str) -> str:
    if isinstance(value, Mapping):
        value_map = cast("Mapping[str, Any]", value)
        result = value_map.get(name)
    else:
        result = getattr(value, name, None)
    if not isinstance(result, str) or not result:
        raise ValueError("Telegram не вернул нужные данные. Попробуйте ещё раз.")
    return result


def _decrypt_optional(cipher: SecretCipher, value: str | None) -> str | None:
    if value is None:
        return None
    return cipher.decrypt(value)
