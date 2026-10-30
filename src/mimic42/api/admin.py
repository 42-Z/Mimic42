from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from mimic42.api.auth import CurrentUser, require_user
from mimic42.core.admin import (
    MAX_ADMIN_PAGE,
    POSTGRES_INTEGER_MAX,
    POSTGRES_INTEGER_MIN,
    AdminIdentity,
    AdminNotFoundError,
    AdminPage,
    AdminPresetDetail,
    AdminPresetKind,
    AdminPresetSummary,
    AdminRepository,
    AdminStatistics,
    AdminUnavailableError,
    AdminUserDetail,
    AdminUserNotFoundError,
    AdminUserSummary,
    PresetCreateValues,
    PresetPatchValues,
    PublicTelegramSettings,
)
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.telegram_app_settings import TelegramAppSettings

logger = logging.getLogger(__name__)


class PresetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1000)
    body: str = Field(min_length=1, max_length=20_000)
    settings: dict[str, Any] | None = None
    sort_order: int = Field(
        default=0,
        strict=True,
        ge=POSTGRES_INTEGER_MIN,
        le=POSTGRES_INTEGER_MAX,
    )

    @field_validator("title", "summary", "body")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Значение не может состоять только из пробелов")
        return value


class PresetPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, min_length=1, max_length=1000)
    body: str | None = Field(default=None, min_length=1, max_length=20_000)
    settings: dict[str, Any] | None = None
    sort_order: int | None = Field(
        default=None,
        strict=True,
        ge=POSTGRES_INTEGER_MIN,
        le=POSTGRES_INTEGER_MAX,
    )

    @field_validator("title", "summary", "body")
    @classmethod
    def reject_null_or_blank_text(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("Поле должно содержать непустой текст")
        return value

    @field_validator("sort_order")
    @classmethod
    def reject_null_sort_order(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("Поле не может быть null")
        return value

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> PresetPatchRequest:
        if not self.model_fields_set:
            raise ValueError("PATCH должен содержать хотя бы одно поле")
        return self


class PresetVisibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool = Field(strict=True)


class TelegramSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_id: int = Field(strict=True, gt=0, le=POSTGRES_INTEGER_MAX)
    api_hash: SecretStr = Field(min_length=1, max_length=256)

    @field_validator("api_hash")
    @classmethod
    def reject_blank_api_hash(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("HASH не может состоять только из пробелов")
        return value


class AdminRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def safe_handler(request: Request) -> Response:
            try:
                response = await handler(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={"detail": "Проверьте поля запроса"},
                    headers={"Cache-Control": "no-store"},
                )
            except StarletteHTTPException as exc:
                response = await http_exception_handler(request, exc)
            response.headers["Cache-Control"] = "no-store"
            return response

        return safe_handler


def _admin_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Администрирование временно недоступно",
    )


async def _check_admin_role(request: Request, user_id: UUID) -> bool:
    repository: AdminRepository | None = getattr(request.app.state, "admin_repository", None)
    if repository is None:
        raise _admin_unavailable()

    try:
        return await repository.is_admin(user_id)
    except AdminUnavailableError as exc:
        logger.warning("Administrator role lookup unavailable (%s)", type(exc).__name__)
        raise _admin_unavailable() from None
    except Exception as exc:
        logger.error(
            "Unexpected administrator role lookup error (%s)",
            type(exc).__name__,
        )
        raise _admin_unavailable() from None


async def require_admin(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(require_user)],
) -> CurrentUser:
    if not await _check_admin_role(request, current_user.user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только администраторам",
        )
    return current_user


def _get_admin_repository(request: Request) -> AdminRepository:
    repository: AdminRepository | None = getattr(request.app.state, "admin_repository", None)
    if repository is None:
        raise _admin_unavailable()
    return repository


async def _admin_result[ResultT](operation: Awaitable[ResultT]) -> ResultT:
    try:
        return await operation
    except AdminUserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        ) from None
    except AdminNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пресет не найден",
        ) from None
    except AdminUnavailableError as exc:
        logger.warning("Administrative operation unavailable (%s)", type(exc).__name__)
        raise _admin_unavailable() from None
    except Exception as exc:
        logger.error("Unexpected administrative operation error (%s)", type(exc).__name__)
        raise _admin_unavailable() from None


async def get_admin_identity(request: Request, current_user: CurrentUser) -> AdminIdentity:
    return AdminIdentity(
        user_id=current_user.user_id,
        is_admin=await _check_admin_role(request, current_user.user_id),
    )


router = APIRouter(
    prefix="/api/v1/admin",
    dependencies=[Depends(require_admin)],
    route_class=AdminRoute,
)


@router.get("/presets", response_model=AdminPage[AdminPresetSummary])
async def list_presets(
    request: Request,
    q: Annotated[str, Query(max_length=200)] = "",
    kind: AdminPresetKind = "all",
    page: Annotated[int, Query(ge=1, le=MAX_ADMIN_PAGE)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> AdminPage[AdminPresetSummary]:
    repository = _get_admin_repository(request)
    return await _admin_result(
        repository.list_presets(
            q=q.strip(),
            kind=kind,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/presets/{preset_id}", response_model=AdminPresetDetail)
async def get_preset(request: Request, preset_id: UUID) -> AdminPresetDetail:
    repository = _get_admin_repository(request)
    return await _admin_result(repository.get_preset(preset_id))


@router.post(
    "/presets",
    response_model=AdminPresetDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_preset(
    request: Request,
    values: PresetCreateRequest,
    current_user: Annotated[CurrentUser, Depends(require_admin)],
) -> AdminPresetDetail:
    repository = _get_admin_repository(request)
    create_values = cast(PresetCreateValues, values.model_dump())
    return await _admin_result(
        repository.create_official_preset(create_values, actor_user_id=current_user.user_id)
    )


@router.patch("/presets/{preset_id}/visibility", response_model=AdminPresetDetail)
async def set_preset_visibility(
    request: Request,
    preset_id: UUID,
    values: PresetVisibilityRequest,
    current_user: Annotated[CurrentUser, Depends(require_admin)],
) -> AdminPresetDetail:
    repository = _get_admin_repository(request)
    return await _admin_result(
        repository.set_preset_visibility(
            preset_id,
            values.is_active,
            actor_user_id=current_user.user_id,
        )
    )


@router.patch("/presets/{preset_id}", response_model=AdminPresetDetail)
async def update_preset(
    request: Request,
    preset_id: UUID,
    values: PresetPatchRequest,
    current_user: Annotated[CurrentUser, Depends(require_admin)],
) -> AdminPresetDetail:
    repository = _get_admin_repository(request)
    patch_values = cast(PresetPatchValues, values.model_dump(exclude_unset=True))
    return await _admin_result(
        repository.update_official_preset(
            preset_id,
            patch_values,
            actor_user_id=current_user.user_id,
        )
    )


def _get_telegram_app_settings(request: Request) -> TelegramAppSettings:
    provider: TelegramAppSettings | None = getattr(
        request.app.state,
        "telegram_app_settings",
        None,
    )
    if provider is None:
        raise _admin_unavailable()
    return provider


async def _runtime_state_snapshot(request: Request) -> dict[UUID, AgentRuntimeState]:
    manager = getattr(request.app.state, "agent_manager", None)
    if manager is None:
        raise _admin_unavailable()
    try:
        statuses = await manager.list_agents()
    except Exception as exc:
        logger.warning("Administrator runtime snapshot unavailable (%s)", type(exc).__name__)
        raise _admin_unavailable() from None
    return {status.agent_id: status.state for status in statuses}


@router.get("/users", response_model=AdminPage[AdminUserSummary])
async def list_users(
    request: Request,
    q: Annotated[str, Query(max_length=200)] = "",
    page: Annotated[int, Query(ge=1, le=MAX_ADMIN_PAGE)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> AdminPage[AdminUserSummary]:
    runtime_states = await _runtime_state_snapshot(request)
    repository = _get_admin_repository(request)
    return await _admin_result(
        repository.list_users(
            q=q.strip(),
            page=page,
            page_size=page_size,
            runtime_states=runtime_states,
        )
    )


@router.get("/users/{user_id}", response_model=AdminUserDetail)
async def get_user(
    request: Request,
    user_id: UUID,
    page: Annotated[int, Query(ge=1, le=MAX_ADMIN_PAGE)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> AdminUserDetail:
    runtime_states = await _runtime_state_snapshot(request)
    repository = _get_admin_repository(request)
    return await _admin_result(
        repository.get_user(
            user_id,
            page=page,
            page_size=page_size,
            runtime_states=runtime_states,
        )
    )


@router.get("/statistics", response_model=AdminStatistics)
async def get_statistics(
    request: Request,
    days: Annotated[int, Query(ge=7, le=30)] = 7,
) -> AdminStatistics:
    if days not in (7, 30):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Период статистики должен быть 7 или 30 дней",
        )
    runtime_states = await _runtime_state_snapshot(request)
    repository = _get_admin_repository(request)
    return await _admin_result(
        repository.statistics(
            days=cast(Literal[7, 30], days),
            now=datetime.now(UTC),
            runtime_states=runtime_states,
        )
    )


@router.get("/telegram-settings", response_model=PublicTelegramSettings)
async def get_telegram_settings(request: Request) -> PublicTelegramSettings:
    return await _admin_result(_get_telegram_app_settings(request).status())


@router.put("/telegram-settings", response_model=PublicTelegramSettings)
async def update_telegram_settings(
    request: Request,
    values: TelegramSettingsRequest,
    current_user: Annotated[CurrentUser, Depends(require_admin)],
) -> PublicTelegramSettings:
    return await _admin_result(
        _get_telegram_app_settings(request).save(
            api_id=values.api_id,
            api_hash=values.api_hash,
            actor_user_id=current_user.user_id,
        )
    )
