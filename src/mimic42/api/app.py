from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from mimic42.api.auth import AuthVerifier, CurrentUser, SupabaseJWTVerifier, require_user
from mimic42.config import Settings
from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentRuntimeState,
    AgentStatus,
    AgentTrigger,
    AgentTriggerResult,
    TelegramAuthorizationRequired,
)
from mimic42.core.agent_store import (
    AgentActivity,
    AgentMessageRecord,
    AgentRecord,
    AgentStore,
    ConversationPage,
)
from mimic42.core.crypto import FernetSecretCipher
from mimic42.core.manager import (
    AgentManager,
    AgentNotFoundError,
    LangChainAgentFactory,
    TelegramClientFactory,
)
from mimic42.core.media import MediaUploader
from mimic42.core.memory import LongTermMemoryLike, RuntimeMemoryService
from mimic42.core.onboarding import (
    AgentOnboardingService,
    AgentProfileInput,
    OnboardingNotFoundError,
    OnboardingOwnershipError,
    OnboardingPublicStatus,
    TelegramAuthClientFactory,
    TelegramAuthorizationIncompleteError,
    TelegramCodeVerification,
    TelegramCredentials,
    TelegramPasswordRequiredError,
)
from mimic42.integrations import openrouter_catalog
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.integrations.database_memory import DatabaseShortTermMemory
from mimic42.integrations.database_onboarding import (
    DatabaseOnboardingRepository,
)
from mimic42.integrations.database_session import create_engine, create_session_factory
from mimic42.integrations.mem0_memory import build_mem0_memory
from mimic42.integrations.supabase_media import SupabaseMediaStorage
from mimic42.integrations.telegram_auth import TelethonAuthClientFactory

logger = logging.getLogger("mimic42.api.app")

CurrentUserDep = Annotated[CurrentUser, Depends(require_user)]


class AgentManagerLike(Protocol):
    async def create_agent(
        self,
        config: AgentRuntimeConfig,
        *,
        start: bool = False,
    ) -> object: ...

    async def get_agent_status(self, agent_id: UUID) -> AgentStatus: ...

    async def list_agents(self, *, owner_id: UUID | None = None) -> list[AgentStatus]: ...

    async def start_agent(self, agent_id: UUID) -> None: ...

    async def stop_agent(self, agent_id: UUID) -> None: ...

    async def reload_agent(self, agent_id: UUID) -> None: ...

    async def remove_agent(self, agent_id: UUID) -> None: ...

    async def trigger_message(
        self,
        agent_id: UUID,
        trigger: AgentTrigger,
    ) -> AgentTriggerResult: ...

    async def shutdown(self) -> None: ...


class CreateAgentRequest(BaseModel):
    agent_id: UUID = Field(default_factory=uuid4)
    telegram_session_string: str | None = Field(default=None, min_length=1)
    telegram_api_id: int | None = Field(default=None, gt=0)
    telegram_api_hash: str | None = Field(default=None, min_length=1)
    soul_prompt: str = Field(default="", max_length=20_000)
    auto_start: bool = False

    def to_runtime_config(
        self,
        *,
        owner_id: UUID,
        api_id: int,
        api_hash: str,
    ) -> AgentRuntimeConfig:
        from mimic42.core.onboarding import load_default_system_prompt

        return AgentRuntimeConfig(
            agent_id=self.agent_id,
            owner_id=owner_id,
            telegram_api_id=api_id,
            telegram_api_hash=api_hash,
            telegram_session_string=self.telegram_session_string,
            system_prompt=load_default_system_prompt(),
            soul_prompt=self.soul_prompt,
        )


class TriggerMessageRequest(BaseModel):
    peer: str = Field(min_length=1)
    text: str = Field(min_length=1)

    def to_trigger(self) -> AgentTrigger:
        return AgentTrigger(peer=self.peer, text=self.text, raw_text=self.text)


class TelegramLoginRequest(BaseModel):
    api_id: int | None = Field(default=None, gt=0)
    api_hash: str | None = Field(default=None, min_length=1)
    phone_number: str = Field(min_length=5)
    onboarding_id: UUID | None = None


class TelegramRebindRequest(BaseModel):
    phone_number: str | None = Field(default=None, min_length=5)


class TelegramRebindConfirmRequest(BaseModel):
    onboarding_id: UUID


def _resolve_telegram_app(
    settings: Settings,
    api_id: int | None,
    api_hash: str | None,
) -> tuple[int, str]:
    """Fall back to the deployment-wide Telegram application when none is supplied."""
    resolved_id = api_id if api_id is not None else settings.telegram_api_id
    resolved_hash = api_hash if api_hash is not None else settings.telegram_api_hash
    if resolved_id is None or resolved_hash is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Telegram-приложение не настроено на сервере. "
                "Задайте TELEGRAM_API_ID и TELEGRAM_API_HASH в окружении."
            ),
        )
    return resolved_id, resolved_hash


def _telegram_login_http_error(exc: Exception) -> HTTPException | None:
    """Перевести ошибку Telegram-логина в понятный пользователю ответ.

    Возвращает None для незнакомых исключений — эндпоинт пробрасывает их как есть.
    """
    from telethon.errors import (
        ApiIdInvalidError,
        ApiIdPublishedFloodError,
        FloodWaitError,
        PhoneNumberBannedError,
        PhoneNumberInvalidError,
        RPCError,
    )

    if isinstance(exc, ApiIdInvalidError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Telegram отклонил приложение сервера: "
                "неверная комбинация TELEGRAM_API_ID и TELEGRAM_API_HASH."
            ),
        )
    if isinstance(exc, ApiIdPublishedFloodError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Telegram заблокировал приложение сервера как опубликованное. "
                "Замените TELEGRAM_API_ID и TELEGRAM_API_HASH."
            ),
        )
    if isinstance(exc, PhoneNumberBannedError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот номер заблокирован в Telegram.",
        )
    if isinstance(exc, PhoneNumberInvalidError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Неверный формат номера телефона. "
                "Используйте международный формат (например, +79991234567)."
            ),
        )
    if isinstance(exc, FloodWaitError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Слишком много попыток. Telegram просит подождать {exc.seconds} сек.",
        )
    if isinstance(exc, RPCError):
        logger.warning("Telegram RPC error: %s", exc.message)
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram отклонил запрос. Проверьте данные и попробуйте снова.",
        )
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return None


def create_app(
    *,
    manager: AgentManagerLike | None = None,
    onboarding_service: AgentOnboardingService | None = None,
    agent_store: AgentStore | None = None,
    auth_verifier: AuthVerifier | None = None,
    settings: Settings | None = None,
    telegram_factory: TelegramAuthClientFactory | None = None,
    telegram_client_factory: TelegramClientFactory | None = None,
    langchain_agent_factory: LangChainAgentFactory | None = None,
    long_term_memory: LongTermMemoryLike | None = None,
    media_uploader: MediaUploader | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    app_telegram_factory = telegram_factory or TelethonAuthClientFactory()
    # Resolution order: explicit argument → uploader of an injected manager →
    # storage built from settings. A broken Storage configuration must degrade
    # to "media unavailable", not crash application startup.
    app_media_storage: MediaUploader | None = media_uploader or getattr(
        manager, "media_uploader", None
    )
    if (
        app_media_storage is None
        and app_settings.supabase_url
        and app_settings.supabase_service_key
    ):
        try:
            app_media_storage = SupabaseMediaStorage(
                supabase_url=app_settings.supabase_url,
                service_key=app_settings.supabase_service_key,
            )
        except Exception:
            logger.warning("Failed to initialise Supabase media storage", exc_info=True)
            app_media_storage = None
    app_manager = manager or AgentManager(
        telegram_client_factory=telegram_client_factory,
        langchain_agent_factory=langchain_agent_factory,
        media_uploader=app_media_storage,
    )
    app_onboarding_service = onboarding_service or AgentOnboardingService(
        telegram_factory=app_telegram_factory,
        agent_store=agent_store,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database_engine = None
        should_build_database = app_settings.database_connection_string and (
            onboarding_service is None or agent_store is None
        )
        if should_build_database:
            database_engine = create_engine(app_settings.database_connection_string)
            session_factory = create_session_factory(database_engine)
            cipher = (
                FernetSecretCipher(app_settings.secret_key)
                if app_settings.secret_key is not None
                else None
            )
            database_agent_store = agent_store or DatabaseAgentStore(
                session_factory,
                cipher=cipher,
            )
            app.state.agent_store = database_agent_store
            if onboarding_service is None:
                app.state.onboarding_service = AgentOnboardingService(
                    repository=DatabaseOnboardingRepository(session_factory),
                    telegram_factory=app_telegram_factory,
                    cipher=cipher,
                    agent_store=database_agent_store,
                )
            if manager is None:
                agent_memory = long_term_memory or build_mem0_memory(app_settings.mem0_api_key)
                app.state.long_term_memory = agent_memory
                app.state.agent_manager = AgentManager(
                    memory_service_factory=lambda _config: RuntimeMemoryService(
                        short_term=DatabaseShortTermMemory(session_factory),
                        long_term=agent_memory,
                    ),
                    config_loader=database_agent_store.get_runtime_config,
                    status_sink=database_agent_store.update_status,
                    session_factory=session_factory,
                    telegram_client_factory=telegram_client_factory,
                    langchain_agent_factory=langchain_agent_factory,
                    media_uploader=app_media_storage,
                )
        try:
            # Restore running agents from database after restart
            logger.info(
                f"[lifespan] should_build={should_build_database}, manager_none={manager is None}"
            )
            if should_build_database and manager is None and app_settings.restore_running_agents:
                try:
                    agent_records = await database_agent_store.list_agents()
                    logger.info(f"[lifespan] Found {len(agent_records)} agents")
                    for record in agent_records:
                        logger.debug(f"[lifespan] Agent {record.agent_id} state={record.state}")
                        if record.state == AgentRuntimeState.RUNNING and record.restore_on_start:
                            try:
                                config = await database_agent_store.get_runtime_config(
                                    record.agent_id
                                )
                                logger.info(
                                    f"[lifespan] Restoring agent {record.agent_id} "
                                    f"with model {config.llm_model}"
                                )
                                await app.state.agent_manager.create_agent(config, start=True)
                                logger.info(
                                    f"[lifespan] Agent {record.agent_id} restored and started"
                                )
                            except Exception as exc:
                                logger.exception(
                                    f"[lifespan] Failed to restore agent {record.agent_id}: {exc}"
                                )
                        elif record.state == AgentRuntimeState.RUNNING:
                            logger.info(
                                "[lifespan] Skipping agent %s: restore_on_start is disabled",
                                record.agent_id,
                            )
                except Exception as exc:
                    logger.exception(f"[lifespan] Failed to restore running agents: {exc}")
            yield
        finally:
            await _get_agent_manager(app).shutdown()
            if database_engine is not None:
                await database_engine.dispose()

    app = FastAPI(title="Mimic42 API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.agent_manager = app_manager
    app.state.onboarding_service = app_onboarding_service
    app.state.agent_store = agent_store
    app.state.media_uploader = app_media_storage
    app.state.long_term_memory = None
    app.state.auth_verifier = auth_verifier or (
        SupabaseJWTVerifier(supabase_url=app_settings.supabase_url)
        if app_settings.supabase_url is not None
        else None
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "mimic42-api"}

    @app.get("/api/v1/agents", response_model=list[AgentRecord])
    async def list_agents(current_user: CurrentUserDep) -> list[AgentRecord]:
        store = _get_agent_store(app)
        if store is not None:
            return await store.list_agents(owner_id=current_user.user_id)
        statuses = await _get_agent_manager(app).list_agents(owner_id=current_user.user_id)
        return [
            AgentRecord(
                agent_id=status.agent_id,
                owner_id=status.owner_id,
                name="Runtime agent",
                state=status.state,
            )
            for status in statuses
        ]

    @app.post(
        "/api/v1/onboarding/telegram",
        response_model=OnboardingPublicStatus,
        status_code=status.HTTP_201_CREATED,
    )
    async def request_telegram_code(
        payload: TelegramLoginRequest,
        current_user: CurrentUserDep,
    ) -> OnboardingPublicStatus:
        api_id, api_hash = _resolve_telegram_app(app_settings, payload.api_id, payload.api_hash)
        credentials = TelegramCredentials(
            owner_id=current_user.user_id,
            api_id=api_id,
            api_hash=api_hash,
            phone_number=payload.phone_number,
        )
        try:
            return await _get_onboarding_service(app).request_telegram_code(
                credentials,
                onboarding_id=payload.onboarding_id,
            )
        except OnboardingNotFoundError as exc:
            raise _onboarding_not_found(exc.onboarding_id) from exc
        except OnboardingOwnershipError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Сессия онбординга принадлежит другому пользователю",
            ) from exc
        except Exception as exc:
            translated = _telegram_login_http_error(exc)
            if translated is not None:
                raise translated from exc
            raise exc

    @app.post(
        "/api/v1/onboarding/{onboarding_id}/telegram/code",
        response_model=OnboardingPublicStatus,
    )
    async def verify_telegram_code(
        onboarding_id: UUID,
        payload: TelegramCodeVerification,
        current_user: CurrentUserDep,
    ) -> OnboardingPublicStatus:
        try:
            status_result = await _get_onboarding_service(app).get_status(onboarding_id)
        except OnboardingNotFoundError as exc:
            raise _onboarding_not_found(onboarding_id) from exc
        # Unified owner check — do not leak session existence via status codes
        try:
            _ensure_owner(status_result.owner_id, current_user.user_id)
        except HTTPException:
            raise _onboarding_not_found(onboarding_id) from None
        try:
            result = await _get_onboarding_service(app).verify_telegram_code(onboarding_id, payload)
            return result
        except TelegramPasswordRequiredError as exc:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail=(
                    "Для этого аккаунта включена двухфакторная аутентификация. Введите пароль 2FA."
                ),
            ) from exc
        except Exception as exc:
            from telethon.errors import (
                PasswordHashInvalidError,
                PhoneCodeEmptyError,
                PhoneCodeExpiredError,
                PhoneCodeInvalidError,
                PhoneNumberUnoccupiedError,
                RPCError,
            )

            if isinstance(exc, PhoneNumberUnoccupiedError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Пользователя с таким номером нет в Telegram.",
                ) from exc
            if isinstance(exc, (PhoneCodeInvalidError, PhoneCodeEmptyError)):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Неверный код подтверждения. Пожалуйста, проверьте и введите код заново."
                    ),
                ) from exc
            if isinstance(exc, PhoneCodeExpiredError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Срок действия кода подтверждения истек. Запросите новый код.",
                ) from exc
            if isinstance(exc, PasswordHashInvalidError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неверный пароль двухфакторной аутентификации (2FA).",
                ) from exc
            if isinstance(exc, RPCError):
                logger.warning("Telegram RPC error: %s", exc.message)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Telegram отклонил запрос. Проверьте данные и попробуйте снова.",
                ) from exc
            raise exc

    @app.post(
        "/api/v1/onboarding/{onboarding_id}/agent",
        response_model=AgentStatus,
        status_code=status.HTTP_201_CREATED,
    )
    async def finalize_agent(
        onboarding_id: UUID,
        payload: AgentProfileInput,
        current_user: CurrentUserDep,
    ) -> AgentStatus:
        try:
            status_result = await _get_onboarding_service(app).get_status(onboarding_id)
        except OnboardingNotFoundError as exc:
            raise _onboarding_not_found(onboarding_id) from exc
        # Unified owner check — do not leak session existence via status codes
        try:
            _ensure_owner(status_result.owner_id, current_user.user_id)
        except HTTPException:
            raise _onboarding_not_found(onboarding_id) from None
        try:
            result = await _get_onboarding_service(app).finalize_agent(onboarding_id, payload)
            return result
        except TelegramAuthorizationIncompleteError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.get(
        "/api/v1/agents/{agent_id}/messages",
        response_model=list[AgentMessageRecord],
        deprecated=True,
    )
    async def list_agent_messages(
        agent_id: UUID,
        current_user: CurrentUserDep,
        limit: Annotated[int, Query(ge=1, le=1000)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[AgentMessageRecord]:
        """Deprecated: UI uses ``/conversation``; kept for external consumers."""
        store = _get_agent_store(app)
        if store is None:
            return []
        await _ensure_agent_owner(store, agent_id=agent_id, user_id=current_user.user_id)
        return await store.list_messages(agent_id=agent_id, limit=limit, offset=offset)

    @app.get(
        "/api/v1/agents/{agent_id}/actions",
        response_model=list[AgentActivity],
        deprecated=True,
    )
    async def list_agent_actions(
        agent_id: UUID,
        current_user: CurrentUserDep,
        limit: Annotated[int, Query(ge=1, le=1000)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[AgentActivity]:
        """Deprecated: UI uses ``/conversation``; kept for external consumers."""
        store = _get_agent_store(app)
        if store is None:
            return []
        await _ensure_agent_owner(store, agent_id=agent_id, user_id=current_user.user_id)
        return await store.list_activities(agent_id=agent_id, limit=limit, offset=offset)

    @app.get("/api/v1/agents/{agent_id}/conversation", response_model=ConversationPage)
    async def get_agent_conversation(
        agent_id: UUID,
        current_user: CurrentUserDep,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        before: Annotated[datetime | None, Query()] = None,
        before_id: Annotated[UUID | None, Query()] = None,
    ) -> ConversationPage:
        store = _get_agent_store(app)
        if store is None:
            return ConversationPage()
        await _ensure_agent_owner(store, agent_id=agent_id, user_id=current_user.user_id)
        return await store.get_conversation(
            agent_id=agent_id, limit=limit, before=before, before_id=before_id
        )

    @app.get("/api/v1/agents/{agent_id}/media/{media_path:path}")
    async def get_agent_media(
        agent_id: UUID,
        media_path: str,
        current_user: CurrentUserDep,
        request: Request,
    ) -> Response:
        store = _get_agent_store(app)
        media_storage: MediaUploader | None = getattr(app.state, "media_uploader", None)
        if store is None or media_storage is None:
            raise HTTPException(status_code=404, detail="Медиа недоступно")
        await _ensure_agent_owner(store, agent_id=agent_id, user_id=current_user.user_id)
        # Объект обязан лежать внутри папки агента — иначе доступ к чужому
        # файлу. `..`-сегменты отклоняются: URL-нормализация внутри storage-клиента
        # иначе увела бы запрос в чужую папку ({agent_id}/../{other}/file).
        path_segments = [segment for segment in media_path.split("/") if segment]
        if (
            not media_path.startswith(f"{agent_id}/")
            or ".." in path_segments
            or media_path.startswith("/")
        ):
            raise HTTPException(status_code=403, detail="Нет доступа к этому файлу")
        data = await media_storage.open(media_path)
        if data is None:
            raise HTTPException(status_code=404, detail="Файл не найден")
        extension = media_path.rsplit(".", 1)[-1].lower()
        content_types = {
            "jpeg": "image/jpeg",
            "jpg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
            "gif": "image/gif",
            "ogg": "audio/ogg",
            "mp4": "video/mp4",
            "pdf": "application/pdf",
        }
        media_type = content_types.get(extension, "application/octet-stream")
        cache_headers = {"Cache-Control": "private, max-age=300", "Accept-Ranges": "bytes"}
        # Range даёт браузеру листать видео/аудио без выкачивания всего файла.
        byte_range = _parse_byte_range(request.headers.get("range"), len(data))
        if byte_range == "invalid":
            return Response(
                status_code=416,
                headers={**cache_headers, "Content-Range": f"bytes */{len(data)}"},
            )
        if byte_range is not None:
            start, end = byte_range
            return Response(
                content=data[start : end + 1],
                status_code=206,
                media_type=media_type,
                headers={
                    **cache_headers,
                    "Content-Range": f"bytes {start}-{end}/{len(data)}",
                },
            )
        return Response(content=data, media_type=media_type, headers=cache_headers)

    @app.post(
        "/api/v1/agents",
        response_model=AgentStatus,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_agent(
        payload: CreateAgentRequest,
        current_user: CurrentUserDep,
    ) -> AgentStatus:
        api_id, api_hash = _resolve_telegram_app(
            app_settings, payload.telegram_api_id, payload.telegram_api_hash
        )
        try:
            manager_for_request = _get_agent_manager(app)
            await manager_for_request.create_agent(
                payload.to_runtime_config(
                    owner_id=current_user.user_id,
                    api_id=api_id,
                    api_hash=api_hash,
                ),
                start=payload.auto_start,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except TelegramAuthorizationRequired as exc:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail=str(exc),
            ) from exc
        return await _get_agent_manager(app).get_agent_status(payload.agent_id)

    @app.post(
        "/api/v1/agents/{agent_id}/telegram/rebind",
        response_model=OnboardingPublicStatus,
        status_code=status.HTTP_201_CREATED,
    )
    async def rebind_agent_telegram(
        agent_id: UUID,
        payload: TelegramRebindRequest,
        current_user: CurrentUserDep,
    ) -> OnboardingPublicStatus:
        """Начать перепривязку: запросить код Telegram для существующего агента.

        Онбординг-сессия агента переиспользуется: код/2FA идут по стандартным
        onboarding-эндпоинтам, а на confirm сессия переносится на агента.
        Используется серверное Telegram-приложение: api_id/hash агента
        заменяются деплойментными.
        """
        if _get_agent_store(app) is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Перепривязка недоступна: хранилище агентов не настроено.",
            )
        try:
            await _ensure_runtime_owner(app, agent_id=agent_id, user_id=current_user.user_id)
        except AgentNotFoundError as exc:
            raise _not_found(exc.agent_id) from exc
        api_id, api_hash = _resolve_telegram_app(app_settings, None, None)
        credentials = TelegramCredentials(
            owner_id=current_user.user_id,
            api_id=api_id,
            api_hash=api_hash,
            phone_number=payload.phone_number,
        )
        try:
            return await _get_onboarding_service(app).start_rebind(agent_id, credentials)
        except OnboardingOwnershipError as exc:
            raise _not_found(agent_id) from exc
        except Exception as exc:
            translated = _telegram_login_http_error(exc)
            if translated is not None:
                raise translated from exc
            raise exc

    @app.post(
        "/api/v1/agents/{agent_id}/telegram/rebind/confirm",
        response_model=AgentStatus,
    )
    async def confirm_agent_telegram_rebind(
        agent_id: UUID,
        payload: TelegramRebindConfirmRequest,
        current_user: CurrentUserDep,
    ) -> AgentStatus:
        """Завершить перепривязку: применить новую сессию к существующему агенту.

        Имя, характер, память и настройки не меняются. Рантайм пересобирается
        из свежего конфига: старый держал сломанную сессию в памяти.
        """
        if _get_agent_store(app) is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Перепривязка недоступна: хранилище агентов не настроено.",
            )
        try:
            await _ensure_runtime_owner(app, agent_id=agent_id, user_id=current_user.user_id)
        except AgentNotFoundError as exc:
            raise _not_found(exc.agent_id) from exc
        try:
            status_result = await _get_onboarding_service(app).get_status(payload.onboarding_id)
        except OnboardingNotFoundError as exc:
            raise _onboarding_not_found(payload.onboarding_id) from exc
        # Единый 404 — не раскрываем существование чужой сессии.
        try:
            _ensure_owner(status_result.owner_id, current_user.user_id)
        except HTTPException:
            raise _onboarding_not_found(payload.onboarding_id) from None
        try:
            result = await _get_onboarding_service(app).rebind_to_agent(
                payload.onboarding_id,
                agent_id,
                owner_id=current_user.user_id,
            )
        except OnboardingOwnershipError as exc:
            raise _onboarding_not_found(payload.onboarding_id) from exc
        except TelegramAuthorizationIncompleteError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Авторизация Telegram не завершена. Введите код подтверждения.",
            ) from exc
        manager = _get_agent_manager(app)
        # Останавливаем до пересборки: reload_agent перезапускает RUNNING-агента,
        # а по решению из issue агент остаётся остановленным.
        try:
            await manager.stop_agent(agent_id)
        except Exception:
            logger.exception("Failed to stop agent %s before rebind reload", agent_id)
        try:
            await manager.reload_agent(agent_id)
        except Exception:
            # Перепривязка уже применена в базе; reload_agent вынимает старый
            # рантайм из реестра до close, так что следующий start соберётся
            # из свежего конфига.
            logger.exception("Failed to reload agent %s after rebind", agent_id)
        return result

    @app.get("/api/v1/agents/{agent_id}", response_model=AgentStatus)
    async def get_agent(
        agent_id: UUID,
        current_user: CurrentUserDep,
    ) -> AgentStatus:
        try:
            status_result = await _get_agent_manager(app).get_agent_status(agent_id)
            try:
                _ensure_owner(status_result.owner_id, current_user.user_id)
            except HTTPException:
                # Unified 404 like sibling endpoints — do not leak existence.
                raise _not_found(agent_id) from None
            return status_result
        except AgentNotFoundError as exc:
            raise _not_found(exc.agent_id) from exc

    @app.delete(
        "/api/v1/agents/{agent_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_agent(
        agent_id: UUID,
        current_user: CurrentUserDep,
    ) -> Response:
        store = _get_agent_store(app)
        try:
            if store is not None:
                await _ensure_agent_owner(store, agent_id=agent_id, user_id=current_user.user_id)
            else:
                await _ensure_runtime_owner(app, agent_id=agent_id, user_id=current_user.user_id)
        except AgentNotFoundError as exc:
            raise _not_found(exc.agent_id) from exc

        await _get_agent_manager(app).remove_agent(agent_id)

        if store is not None:
            await store.delete_agent(agent_id)

        memory_store = _get_long_term_memory(app)
        if memory_store is not None:
            try:
                await memory_store.clear_all_memories(agent_id)
            except Exception:
                logger.exception("Failed to clear Mem0 memories for agent %s", agent_id)

        media_storage: MediaUploader | None = getattr(app.state, "media_uploader", None)
        if media_storage is not None:
            try:
                await media_storage.remove_prefix(agent_id)
            except Exception:
                logger.warning("Failed to remove media for agent %s", agent_id, exc_info=True)

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/api/v1/agents/{agent_id}/start",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def start_agent(
        agent_id: UUID,
        current_user: CurrentUserDep,
    ) -> Response:
        try:
            await _ensure_runtime_owner(app, agent_id=agent_id, user_id=current_user.user_id)
            await _get_agent_manager(app).start_agent(agent_id)
        except AgentNotFoundError as exc:
            raise _not_found(exc.agent_id) from exc
        except TelegramAuthorizationRequired as exc:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail=str(exc),
            ) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/api/v1/agents/{agent_id}/stop",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def stop_agent(
        agent_id: UUID,
        current_user: CurrentUserDep,
    ) -> Response:
        try:
            await _ensure_runtime_owner(app, agent_id=agent_id, user_id=current_user.user_id)
            await _get_agent_manager(app).stop_agent(agent_id)
        except AgentNotFoundError as exc:
            raise _not_found(exc.agent_id) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/api/v1/agents/{agent_id}/reload",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def reload_agent(
        agent_id: UUID,
        current_user: CurrentUserDep,
    ) -> Response:
        try:
            await _ensure_runtime_owner(app, agent_id=agent_id, user_id=current_user.user_id)
            await _get_agent_manager(app).reload_agent(agent_id)
        except AgentNotFoundError as exc:
            raise _not_found(exc.agent_id) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/api/v1/openrouter/reasoning")
    async def openrouter_reasoning(current_user: CurrentUserDep) -> dict[str, Any]:
        """Per-model reasoning metadata, proxied so users behind blocks or
        without direct access to openrouter.ai still get effort options."""
        try:
            models = await openrouter_catalog.fetch_reasoning_by_model()
        except Exception as exc:
            logger.exception("Failed to fetch OpenRouter reasoning metadata")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Не удалось получить данные о моделях OpenRouter.",
            ) from exc
        return {"models": models}

    @app.post(
        "/api/v1/agents/{agent_id}/messages/trigger",
        response_model=AgentTriggerResult,
    )
    async def trigger_message(
        agent_id: UUID,
        payload: TriggerMessageRequest,
        current_user: CurrentUserDep,
    ) -> AgentTriggerResult:
        try:
            await _ensure_runtime_owner(app, agent_id=agent_id, user_id=current_user.user_id)
            return await _get_agent_manager(app).trigger_message(agent_id, payload.to_trigger())
        except AgentNotFoundError as exc:
            raise _not_found(exc.agent_id) from exc
        except TelegramAuthorizationRequired as exc:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail=str(exc),
            ) from exc

    @app.get("/api/v1/agents/{agent_id}/memory", response_model=list[dict[str, Any]])
    async def list_agent_memories(
        agent_id: UUID,
        current_user: CurrentUserDep,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        store = _get_agent_store(app)
        if store is not None:
            await _ensure_agent_owner(store, agent_id=agent_id, user_id=current_user.user_id)
        else:
            await _ensure_runtime_owner(app, agent_id=agent_id, user_id=current_user.user_id)

        memory_store = _get_long_term_memory(app)
        if memory_store is None:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Долгосрочная память Mem0 не настроена на сервере.",
            )

        try:
            if query:
                return await memory_store.search_memories(agent_id, query)
            else:
                return await memory_store.get_all_memories(agent_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ошибка Mem0 API: {exc}",
            ) from exc

    @app.get(
        "/api/v1/agents/{agent_id}/memory/{memory_id}/history",
        response_model=list[dict[str, Any]],
    )
    async def get_agent_memory_history(
        agent_id: UUID,
        memory_id: str,
        current_user: CurrentUserDep,
    ) -> list[dict[str, Any]]:
        store = _get_agent_store(app)
        if store is not None:
            await _ensure_agent_owner(store, agent_id=agent_id, user_id=current_user.user_id)
        else:
            await _ensure_runtime_owner(app, agent_id=agent_id, user_id=current_user.user_id)

        memory_store = _get_long_term_memory(app)
        if memory_store is None:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Долгосрочная память Mem0 не настроена на сервере.",
            )

        # Scope memory_id to this agent: Mem0 history() is unscoped, so
        # verify membership first (ids are unguessable; defense in depth).
        try:
            owned = await memory_store.get_all_memories(agent_id)
        except Exception:
            logger.warning(
                "Memory ownership pre-check failed",
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Сервис памяти недоступен",
            ) from None
        owned_ids = {
            str(item.get("id"))
            for item in owned
            if isinstance(item, dict) and item.get("id") is not None
        }
        if not owned_ids or memory_id not in owned_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Воспоминание не найдено",
            )

        try:
            return await memory_store.get_memory_history(memory_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ошибка Mem0 API при получении истории: {exc}",
            ) from exc

    return app


def _not_found(agent_id: UUID) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Агент не найден",
    )


def _onboarding_not_found(onboarding_id: UUID) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Сессия онбординга не найдена",
    )


def _get_onboarding_service(app: FastAPI) -> AgentOnboardingService:
    return app.state.onboarding_service


def _get_agent_manager(app: FastAPI) -> AgentManagerLike:
    return app.state.agent_manager


def _get_agent_store(app: FastAPI) -> AgentStore | None:
    return app.state.agent_store


def _get_long_term_memory(app: FastAPI) -> LongTermMemoryLike | None:
    return getattr(app.state, "long_term_memory", None)


def _ensure_owner(owner_id: UUID, user_id: UUID) -> None:
    if owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Агент не принадлежит этому пользователю",
        )


async def _ensure_agent_owner(store: AgentStore, *, agent_id: UUID, user_id: UUID) -> None:
    owned_agents = await store.list_agents(owner_id=user_id)
    if not any(agent.agent_id == agent_id for agent in owned_agents):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Агент не найден",
        )


def _parse_byte_range(
    header: str | None, total: int
) -> tuple[int, int] | Literal["invalid"] | None:
    """Разобрать `Range: bytes=start-end` (единственный диапазон).

    Возвращает (start, end) для 206, None — заголовка нет/не поддержан,
    "invalid" — диапазон некорректен (ответ 416).
    """
    if header is None or total == 0:
        return None
    units, _, spec = header.partition("=")
    if units.strip().lower() != "bytes" or "," in spec:
        return None
    start_raw, dash, end_raw = spec.strip().partition("-")
    if not dash:
        return "invalid"
    try:
        if not start_raw:
            length = int(end_raw)
            if length <= 0:
                return "invalid"
            return max(0, total - length), total - 1
        start = int(start_raw)
        end = int(end_raw) if end_raw else total - 1
    except ValueError:
        return "invalid"
    if start < 0 or start > end or start >= total:
        return "invalid"
    return start, min(end, total - 1)


async def _ensure_runtime_owner(app: FastAPI, *, agent_id: UUID, user_id: UUID) -> None:
    store = _get_agent_store(app)
    if store is not None:
        await _ensure_agent_owner(store, agent_id=agent_id, user_id=user_id)
        return
    runtime_status = await _get_agent_manager(app).get_agent_status(agent_id)
    _ensure_owner(runtime_status.owner_id, user_id)
