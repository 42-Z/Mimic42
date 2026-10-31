from __future__ import annotations

import asyncio
import logging
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from mimic42.core.agent_runtime import (
    DEFAULT_LLM_MODEL,
    AgentRuntimeConfig,
    AgentRuntimeState,
    AgentStatus,
    TelegramProxyConfig,
)
from mimic42.core.agent_store import AgentStore
from mimic42.core.telegram_attrs import read_attr, read_optional_attr
from mimic42.core.telegram_proxy import (
    TelegramProxyAssignment,
    TelegramProxyStore,
    TelegramProxyUnavailableError,
)

logger = logging.getLogger("mimic42.onboarding")


def mask_phone_number(phone: str) -> str:
    """Номер без середины: логи не должны содержать личные данные целиком."""
    if len(phone) <= 6:
        return "*" * len(phone)
    return f"{phone[:4]}{'*' * (len(phone) - 6)}{phone[-2:]}"


def load_default_system_prompt() -> str:
    # Файл лежит в пакете (src/mimic42), поэтому одинаково резолвится из
    # editable-инсталла в dev и из wheel в образе (site-packages).
    path = Path(__file__).resolve().parents[1] / "BASE_SYSTEM_PROMPT.txt"
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
    api_hash: str = Field(min_length=1, repr=False)
    phone_number: str = Field(min_length=5, repr=False)
    onboarding_id: UUID | None = Field(default=None)


class TelegramCodeVerification(BaseModel):
    code: str = Field(min_length=1, repr=False)
    password: str | None = Field(default=None, min_length=1, repr=False)


class AgentProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    soul_prompt: str = Field(min_length=1, max_length=20_000)


class OnboardingSession(BaseModel):
    onboarding_id: UUID
    owner_id: UUID
    api_id: int | None = None
    api_hash_secret: str | None = Field(default=None, repr=False)
    phone_number: str | None = Field(default=None, repr=False)
    username: str | None = None
    authorization_status: TelegramLoginStatus
    phone_code_hash_secret: str | None = Field(default=None, repr=False)
    session_secret: str | None = Field(default=None, repr=False)
    name: str | None = None
    soul_prompt: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    completed_agent_id: UUID | None = None
    proxy_id: UUID | None = None
    auth_generation: UUID = Field(default_factory=uuid4)
    applied_auth_generation: UUID | None = None

    def authorization_ref(self) -> TelegramAuthorizationRef:
        return TelegramAuthorizationRef(
            onboarding_id=self.onboarding_id,
            owner_id=self.owner_id,
            generation=self.auth_generation,
            completed_agent_id=self.completed_agent_id,
        )


class TelegramAuthorizationRef(BaseModel):
    model_config = {"frozen": True}

    onboarding_id: UUID
    owner_id: UUID
    generation: UUID
    completed_agent_id: UUID | None

    def check(self, session: OnboardingSession) -> None:
        if self != session.authorization_ref():
            raise TelegramLoginStaleError()


class TelegramLoginAttempt(BaseModel):
    session: OnboardingSession = Field(repr=False)
    assignment: TelegramProxyAssignment | None = Field(default=None, repr=False)

    @property
    def proxy_id(self) -> UUID | None:
        return self.assignment.proxy_id if self.assignment else None


class TelegramLoginStaleError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Попытка входа отменена или заменена. Повторите текущий шаг.")


class TelegramLoginRouteChangedError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Маршрут Telegram изменён. Повторите текущий шаг.")


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
    async def get(self, onboarding_id: UUID) -> OnboardingSession: ...

    async def get_for_agent(self, agent_id: UUID) -> OnboardingSession: ...

    async def begin_login(
        self,
        credentials: TelegramCredentials,
        *,
        api_hash_secret: str,
        onboarding_id: UUID | None = None,
    ) -> OnboardingSession: ...

    async def begin_rebind(self, agent_id: UUID, *, owner_id: UUID) -> OnboardingSession: ...

    async def claim_verification(
        self,
        onboarding_id: UUID,
        *,
        password: bool,
        owner_id: UUID | None = None,
    ) -> OnboardingSession: ...

    async def load_attempt(self, ref: TelegramAuthorizationRef) -> TelegramLoginAttempt: ...

    async def check_attempt(self, attempt: TelegramLoginAttempt) -> None: ...

    async def record_auth(
        self,
        ref: TelegramAuthorizationRef,
        *,
        status: TelegramLoginStatus,
        session_secret: str,
        phone_code_hash_secret: str | None = None,
    ) -> OnboardingSession: ...

    async def record_username(
        self, ref: TelegramAuthorizationRef, username: str | None
    ) -> None: ...


class InMemoryOnboardingRepository:
    def __init__(
        self,
        *,
        proxy_store: TelegramProxyStore | None = None,
        agent_store: AgentStore | None = None,
    ) -> None:
        self._sessions: dict[UUID, OnboardingSession] = {}
        self.proxy_store = proxy_store
        self.agent_store = agent_store
        self.lock = asyncio.Lock()

    async def save(self, session: OnboardingSession) -> None:
        """Seed an in-memory test fixture, never save a network result."""
        self._sessions[session.onboarding_id] = session.model_copy(deep=True)

    async def reset_authorization(self, onboarding_id: UUID) -> None:
        async with self.lock:
            current = await self.get(onboarding_id)
            self._reset(current)
            self._sessions[onboarding_id] = current

    async def begin_login(
        self,
        credentials: TelegramCredentials,
        *,
        api_hash_secret: str,
        onboarding_id: UUID | None = None,
    ) -> OnboardingSession:
        async with self.lock:
            if onboarding_id is None:
                current = OnboardingSession(
                    onboarding_id=uuid4(),
                    owner_id=credentials.owner_id,
                    authorization_status=TelegramLoginStatus.NOT_STARTED,
                )
            else:
                current = await self.get(onboarding_id)
                if current.owner_id != credentials.owner_id:
                    raise OnboardingOwnershipError(onboarding_id)
                if current.completed_agent_id is not None:
                    raise OnboardingAlreadyCompletedError(onboarding_id)
            if current.proxy_id is None and self.proxy_store is not None:
                assignment = await self.proxy_store.allocate()
                current.proxy_id = assignment.proxy_id if assignment else None
            current.api_id = credentials.api_id
            current.api_hash_secret = api_hash_secret
            current.phone_number = credentials.phone_number
            self._reset(current)
            self._sessions[current.onboarding_id] = current.model_copy(deep=True)
            return current

    def _reset(self, current: OnboardingSession) -> None:
        current.authorization_status = TelegramLoginStatus.NOT_STARTED
        current.auth_generation = uuid4()
        current.applied_auth_generation = None
        current.phone_code_hash_secret = None
        current.session_secret = None
        current.username = None

    async def begin_rebind(self, agent_id: UUID, *, owner_id: UUID) -> OnboardingSession:
        async with self.lock:
            try:
                current = await self.get_for_agent(agent_id)
            except OnboardingNotFoundError:
                current = OnboardingSession(
                    onboarding_id=agent_id,
                    owner_id=owner_id,
                    authorization_status=TelegramLoginStatus.NOT_STARTED,
                )
            if current.owner_id != owner_id or current.completed_agent_id not in (None, agent_id):
                raise OnboardingOwnershipError(current.onboarding_id)
            if self.agent_store is not None:
                try:
                    stored = await self.agent_store.get_telegram_rebind_credentials(agent_id)
                except (KeyError, ValueError):
                    raise TelegramRebindUnavailableError(
                        "Нет сохранённых реквизитов Telegram"
                    ) from None
                if stored.owner_id != owner_id:
                    raise OnboardingOwnershipError(current.onboarding_id)
                current.api_id = stored.api_id
                current.api_hash_secret = stored.api_hash_secret
                current.phone_number = stored.phone_number
            if (
                current.api_id is None
                or current.api_hash_secret is None
                or current.phone_number is None
            ):
                raise TelegramRebindUnavailableError("Нет сохранённых реквизитов Telegram")
            current.completed_agent_id = agent_id
            current.proxy_id = None
            self._reset(current)
            self._sessions[current.onboarding_id] = current.model_copy(deep=True)
            return current

    async def claim_verification(
        self,
        onboarding_id: UUID,
        *,
        password: bool,
        owner_id: UUID | None = None,
    ) -> OnboardingSession:
        async with self.lock:
            current = await self.get(onboarding_id)
            _validate_verification(current, password=password, owner_id=owner_id)
            current.auth_generation = uuid4()
            self._sessions[onboarding_id] = current.model_copy(deep=True)
            return current

    async def load_attempt(self, ref: TelegramAuthorizationRef) -> TelegramLoginAttempt:
        try:
            current = await self.get(ref.onboarding_id)
        except OnboardingNotFoundError:
            raise TelegramLoginStaleError() from None
        ref.check(current)
        assignment = None
        if self.proxy_store is not None:
            if current.completed_agent_id is not None:
                assignment = await self.proxy_store.assignment_for_agent(current.completed_agent_id)
            elif current.proxy_id is not None:
                assignment = TelegramProxyAssignment(
                    proxy_id=current.proxy_id, config=await self.proxy_store.load(current.proxy_id)
                )
        elif current.proxy_id is not None:
            raise TelegramProxyUnavailableError("Хранилище назначенного прокси недоступно")
        return TelegramLoginAttempt(session=current, assignment=assignment)

    async def check_attempt(self, attempt: TelegramLoginAttempt) -> None:
        ref = attempt.session.authorization_ref()
        try:
            current = await self.get(ref.onboarding_id)
        except OnboardingNotFoundError:
            raise TelegramLoginStaleError() from None
        ref.check(current)
        proxy_id = current.proxy_id
        if current.completed_agent_id is not None:
            assignment = (
                await self.proxy_store.assignment_for_agent(current.completed_agent_id)
                if self.proxy_store is not None
                else None
            )
            proxy_id = assignment.proxy_id if assignment else None
        if proxy_id != attempt.proxy_id:
            raise TelegramLoginRouteChangedError()

    async def record_auth(
        self,
        ref: TelegramAuthorizationRef,
        *,
        status: TelegramLoginStatus,
        session_secret: str,
        phone_code_hash_secret: str | None = None,
    ) -> OnboardingSession:
        async with self.lock:
            try:
                current = await self.get(ref.onboarding_id)
            except OnboardingNotFoundError:
                raise TelegramLoginStaleError() from None
            ref.check(current)
            current.authorization_status = status
            current.session_secret = session_secret
            if phone_code_hash_secret is not None:
                current.phone_code_hash_secret = phone_code_hash_secret
            current.auth_generation = uuid4()
            current.applied_auth_generation = None
            self._sessions[ref.onboarding_id] = current.model_copy(deep=True)
            return current

    async def record_username(self, ref: TelegramAuthorizationRef, username: str | None) -> None:
        async with self.lock:
            current = self._sessions.get(ref.onboarding_id)
            if current is None:
                raise TelegramLoginStaleError()
            ref.check(current)
            current.username = username

    async def get(self, onboarding_id: UUID) -> OnboardingSession:
        try:
            return self._sessions[onboarding_id].model_copy(deep=True)
        except KeyError as exc:
            raise OnboardingNotFoundError(onboarding_id) from exc

    async def get_for_agent(self, agent_id: UUID) -> OnboardingSession:
        for session in self._sessions.values():
            if session.completed_agent_id == agent_id:
                return session.model_copy(deep=True)
        session = self._sessions.get(agent_id)
        if session is not None:
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

    async def get_me(self) -> object: ...


class TelegramAuthClientFactory(Protocol):
    def build(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
        proxy: TelegramProxyConfig | None = None,
    ) -> TelegramAuthClient: ...


class AgentOnboardingService:
    def __init__(
        self,
        *,
        repository: OnboardingRepository | None = None,
        telegram_factory: TelegramAuthClientFactory,
        cipher: SecretCipher | None = None,
        agent_store: AgentStore | None = None,
        proxy_store: TelegramProxyStore | None = None,
    ) -> None:
        self._repository = repository or InMemoryOnboardingRepository(
            proxy_store=proxy_store, agent_store=agent_store
        )
        if isinstance(self._repository, InMemoryOnboardingRepository):
            self._repository.proxy_store = proxy_store or self._repository.proxy_store
            self._repository.agent_store = agent_store or self._repository.agent_store
            from mimic42.core.agent_store import InMemoryAgentStore

            if isinstance(agent_store, InMemoryAgentStore):
                agent_store.onboarding_repository = self._repository
        self._telegram_factory = telegram_factory
        self._cipher = cipher or PlainTextCipher()
        self._agent_store = agent_store
        self._proxy_store = proxy_store
        self._llm_model = DEFAULT_LLM_MODEL

    async def request_telegram_code(
        self,
        credentials: TelegramCredentials,
        *,
        onboarding_id: UUID | None = None,
    ) -> OnboardingPublicStatus:
        session = await self._repository.begin_login(
            credentials,
            api_hash_secret=self._cipher.encrypt(credentials.api_hash),
            onboarding_id=onboarding_id or credentials.onboarding_id,
        )
        return await self._request_code(session.authorization_ref())

    async def _request_code(self, ref: TelegramAuthorizationRef) -> OnboardingPublicStatus:
        attempt = await self._repository.load_attempt(ref)
        session = attempt.session
        client = self._build_client(attempt)
        try:
            try:
                await self._repository.check_attempt(attempt)
                await client.connect()
                await self._repository.check_attempt(attempt)
                sent_code = await client.send_code_request(session.phone_number or "")
                saved = await self._repository.record_auth(
                    ref,
                    status=TelegramLoginStatus.CODE_REQUESTED,
                    session_secret=self._cipher.encrypt(client.save_session()),
                    phone_code_hash_secret=self._cipher.encrypt(
                        read_attr(sent_code, "phone_code_hash")
                    ),
                )
            except Exception:
                logger.warning(
                    "Запрос кода Telegram не удался: onboarding=%s phone=%s api_id=%s",
                    session.onboarding_id,
                    mask_phone_number(session.phone_number or ""),
                    session.api_id,
                    exc_info=True,
                )
                raise
        finally:
            await _disconnect_auth_client(client)
        logger.info(
            "Код Telegram отправлен: onboarding=%s phone=%s api_id=%s",
            session.onboarding_id,
            mask_phone_number(session.phone_number or ""),
            session.api_id,
        )
        return _public_status(saved)

    async def start_rebind(self, agent_id: UUID, *, owner_id: UUID) -> OnboardingPublicStatus:
        session = await self._repository.begin_rebind(agent_id, owner_id=owner_id)
        return await self._request_code(session.authorization_ref())

    async def verify_telegram_code(
        self,
        onboarding_id: UUID,
        verification: TelegramCodeVerification,
        *,
        owner_id: UUID | None = None,
    ) -> OnboardingPublicStatus:
        session = await self._repository.claim_verification(
            onboarding_id,
            password=bool(verification.password),
            owner_id=owner_id,
        )
        ref = session.authorization_ref()
        attempt = await self._repository.load_attempt(ref)
        client = self._build_client(attempt)
        try:
            try:
                await self._repository.check_attempt(attempt)
                await client.connect()
                await self._repository.check_attempt(attempt)
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
                saved = await self._repository.record_auth(
                    ref,
                    status=TelegramLoginStatus.PASSWORD_REQUIRED,
                    session_secret=self._cipher.encrypt(client.save_session()),
                )
                return _public_status(saved)
            except Exception:
                logger.warning(
                    "Подтверждение кода Telegram не удалось: onboarding=%s phone=%s",
                    onboarding_id,
                    mask_phone_number(session.phone_number or ""),
                    exc_info=True,
                )
                raise

            logger.info(
                "Вход по коду Telegram выполнен: onboarding=%s phone=%s",
                onboarding_id,
                mask_phone_number(session.phone_number or ""),
            )
            saved = await self._repository.record_auth(
                ref,
                status=TelegramLoginStatus.AUTHORIZED,
                session_secret=self._cipher.encrypt(client.save_session()),
            )
            attempt.session = saved
            try:
                await self._repository.check_attempt(attempt)
            except TelegramLoginStaleError:
                raise
            except TelegramLoginRouteChangedError:
                pass
            except Exception:
                logger.warning(
                    "Не удалось проверить маршрут для получения имени Telegram", exc_info=True
                )
            else:
                username = await _fetch_account_username(client)
                try:
                    await self._repository.record_username(saved.authorization_ref(), username)
                except TelegramLoginStaleError:
                    raise
                except Exception:
                    logger.warning("Не удалось сохранить имя Telegram после входа", exc_info=True)
        finally:
            await _disconnect_auth_client(client)
        return _public_status(saved)

    def _build_client(self, attempt: TelegramLoginAttempt) -> TelegramAuthClient:
        session = attempt.session
        if (
            session.api_id is None
            or session.api_hash_secret is None
            or session.phone_number is None
        ):
            raise TelegramAuthorizationIncompleteError(session.onboarding_id)
        return self._telegram_factory.build(
            api_id=session.api_id,
            api_hash=self._cipher.decrypt(session.api_hash_secret),
            session_string=_decrypt_optional(self._cipher, session.session_secret),
            proxy=attempt.assignment.config if attempt.assignment else None,
        )

    async def get_status(self, onboarding_id: UUID) -> OnboardingPublicStatus:
        return _public_status(await self._repository.get(onboarding_id))

    async def finalize_agent(
        self, onboarding_id: UUID, profile: AgentProfileInput, *, owner_id: UUID | None = None
    ) -> AgentStatus:
        session = await self._repository.get(onboarding_id)
        if owner_id is not None and session.owner_id != owner_id:
            raise OnboardingOwnershipError(onboarding_id)
        if session.authorization_status is not TelegramLoginStatus.AUTHORIZED:
            raise TelegramAuthorizationIncompleteError(onboarding_id)

        if self._agent_store is not None:
            await self._agent_store.finalize_onboarding(session.authorization_ref(), profile)
        elif isinstance(self._repository, InMemoryOnboardingRepository):
            async with self._repository.lock:
                current = self._repository._sessions[onboarding_id]
                session.authorization_ref().check(current)
                current.name = profile.name
                current.soul_prompt = profile.soul_prompt
        else:
            raise RuntimeError("Хранилище агентов не настроено")

        return AgentStatus(
            agent_id=session.onboarding_id,
            owner_id=session.owner_id,
            state=AgentRuntimeState.STOPPED,
        )

    async def rebind_to_agent(
        self,
        onboarding_id: UUID,
        agent_id: UUID,
        *,
        owner_id: UUID,
        authorization: TelegramAuthorizationRef | None = None,
    ) -> AgentStatus:
        """Перенести авторизованную онбординг-сессию на существующего агента.

        Флоу перепривязки: Telegram-сессия обновляется, а имя, характер,
        память и настройки агента остаются прежними. Строка онбординга
        остаётся помеченной completed_agent_id и невидимой мастеру: она же
        будет переиспользована при следующей перепривязке.
        """
        session = await self._validated_rebind_session(
            onboarding_id,
            agent_id,
            owner_id=owner_id,
            authorization=authorization,
        )
        if self._agent_store is None:
            raise RuntimeError("Хранилище агентов не настроено")
        await self._agent_store.apply_rebind(session.authorization_ref(), agent_id)
        return AgentStatus(
            agent_id=agent_id,
            owner_id=session.owner_id,
            state=AgentRuntimeState.STOPPED,
        )

    async def validate_rebind_to_agent(
        self, onboarding_id: UUID, agent_id: UUID, *, owner_id: UUID
    ) -> TelegramAuthorizationRef:
        """Validate a rebind before stopping the current runtime."""
        session = await self._validated_rebind_session(onboarding_id, agent_id, owner_id=owner_id)
        return session.authorization_ref()

    async def _validated_rebind_session(
        self,
        onboarding_id: UUID,
        agent_id: UUID,
        *,
        owner_id: UUID,
        authorization: TelegramAuthorizationRef | None = None,
    ) -> OnboardingSession:
        try:
            session = await self._repository.get(onboarding_id)
        except OnboardingNotFoundError:
            if authorization is not None:
                raise TelegramLoginStaleError() from None
            raise
        if authorization is not None:
            authorization.check(session)
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
        if self._agent_store is not None and session.completed_agent_id is not None:
            return await self._agent_store.get_runtime_config(session.completed_agent_id)
        if not session.soul_prompt or session.api_id is None or session.api_hash_secret is None:
            raise TelegramAuthorizationIncompleteError(onboarding_id)

        proxy: TelegramProxyConfig | None = None
        if self._proxy_store is not None and session.proxy_id is not None:
            proxy = await self._proxy_store.load(session.proxy_id)

        return AgentRuntimeConfig(
            agent_id=session.onboarding_id,
            owner_id=session.owner_id,
            telegram_api_id=session.api_id,
            telegram_api_hash=self._cipher.decrypt(session.api_hash_secret),
            telegram_session_string=_decrypt_optional(self._cipher, session.session_secret),
            telegram_session_token=session.session_secret,
            telegram_proxy=proxy,
            llm_model=self._llm_model,
            system_prompt=load_default_system_prompt(),
            soul_prompt=session.soul_prompt,
            name=session.name or "AI",
        )


class TelegramAuthorizationIncompleteError(RuntimeError):
    def __init__(self, onboarding_id: UUID) -> None:
        super().__init__("Онбординг-сессия не готова: завершите авторизацию в Telegram.")
        self.onboarding_id = onboarding_id


def _validate_verification(
    session: OnboardingSession, *, password: bool, owner_id: UUID | None
) -> None:
    if owner_id is not None and session.owner_id != owner_id:
        raise OnboardingOwnershipError(session.onboarding_id)
    expected = (
        TelegramLoginStatus.PASSWORD_REQUIRED if password else TelegramLoginStatus.CODE_REQUESTED
    )
    if (
        session.authorization_status is not expected
        or session.api_id is None
        or session.api_hash_secret is None
        or session.phone_number is None
        or session.session_secret is None
        or (not password and session.phone_code_hash_secret is None)
    ):
        raise TelegramAuthorizationIncompleteError(session.onboarding_id)


async def _disconnect_auth_client(client: TelegramAuthClient) -> None:
    try:
        await client.disconnect()
    except Exception:
        logger.warning("Не удалось закрыть клиент авторизации Telegram", exc_info=True)


def _public_status(session: OnboardingSession) -> OnboardingPublicStatus:
    return OnboardingPublicStatus(
        onboarding_id=session.onboarding_id,
        owner_id=session.owner_id,
        authorization_status=session.authorization_status,
        phone_number=session.phone_number,
    )


async def _fetch_account_username(client: TelegramAuthClient) -> str | None:
    """@username авторизованного аккаунта.

    У аккаунта может не быть @username, а сбой получения не должен отменять
    уже успешный вход: сохраняется просто None.
    """
    try:
        user = await client.get_me()
        return read_optional_attr(user, "username")
    except Exception:
        logger.warning("Failed to fetch Telegram username after sign-in", exc_info=True)
        return None


def _decrypt_optional(cipher: SecretCipher, value: str | None) -> str | None:
    if value is None:
        return None
    return cipher.decrypt(value)
