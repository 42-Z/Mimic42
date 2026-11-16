"""HTTP API режима атаки: кампании, ростер и медиа пула.

Контракт повторяет ``frontend/src/types/index.ts``: сводка с участиями,
деталь с текстами и подписанными ссылками на картинки. Записывает только
``AttackService``; роутер проверяет владельца, переводит доменные ошибки в
HTTP и собирает ответ из представлений сервиса.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Protocol, Self, runtime_checkable
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from mimic42.api.auth import CurrentUser, require_user
from mimic42.api.uploads import read_limited_upload, safe_upload_name
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.attack import (
    MAX_TITLE_LENGTH,
    AttackAgentStatus,
    AttackConfig,
    AttackEndReason,
    AttackLimitType,
    AttackNotFoundError,
    AttackPatch,
    AttackStateError,
    AttackStatus,
    AttackVersionConflictError,
    AttackView,
    ExitReason,
    MessagesLimit,
    MinutesLimit,
    ParticipationView,
    TargetRef,
    parse_target_link,
    validate_config,
)
from mimic42.core.attack_service import AttackService
from mimic42.core.media import (
    MAX_PHOTO_BYTES,
    MEDIA_LINK_TTL,
    MediaFile,
    detect_photo_type,
)

logger = logging.getLogger("mimic42.api.attacks")

CurrentUserDep = Annotated[CurrentUser, Depends(require_user)]

router = APIRouter(prefix="/api/v1", tags=["attacks"])

_IMAGE_CONTENT_TYPES = {
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


@runtime_checkable
class AttackMediaUploader(Protocol):
    """Хранилище, умеющее положить файл в папку владельца, а не агента."""

    async def upload_at_prefix(
        self,
        *,
        path_prefix: str,
        filename: str,
        data: bytes,
        mime_type: str,
        kind: str = "doc",
    ) -> MediaFile | None: ...


@runtime_checkable
class AttackMediaReader(Protocol):
    async def open(self, path: str) -> bytes | None: ...


class AttackImageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    name: str = Field(min_length=1)


class _AttackContent(BaseModel):
    """Общие поля создания и правки: лимит ровно один, ссылки здесь нет."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)
    texts: list[str]
    images: list[AttackImageInput] = Field(default_factory=list)
    limit_kind: AttackLimitType
    message_limit: int | None = Field(default=None, ge=1)
    duration_minutes: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _exactly_one_limit(self) -> Self:
        has_messages = self.message_limit is not None
        has_minutes = self.duration_minutes is not None
        if has_messages == has_minutes:
            raise ValueError("Задайте ровно один лимит: сообщения или минуты")
        if self.limit_kind is AttackLimitType.MESSAGES and not has_messages:
            raise ValueError("Укажите лимит сообщений")
        if self.limit_kind is AttackLimitType.MINUTES and not has_minutes:
            raise ValueError("Укажите длительность в минутах")
        return self

    def build_limit(self) -> MessagesLimit | MinutesLimit:
        if self.limit_kind is AttackLimitType.MESSAGES:
            assert self.message_limit is not None
            return MessagesLimit(self.message_limit)
        assert self.duration_minutes is not None
        return MinutesLimit(self.duration_minutes)


class AttackCreateRequest(_AttackContent):
    target_link: str = Field(min_length=1)
    agent_ids: list[UUID] = Field(default_factory=list)


class AttackPatchRequest(_AttackContent):
    version: int = Field(ge=1)


class AttackAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID


class AttackAgent(BaseModel):
    id: UUID
    attack_id: UUID
    agent_id: UUID
    name: str
    status: AttackAgentStatus
    sent_count: int
    next_at: datetime | None
    last_error: str | None
    exit_reason: ExitReason | None
    note_written_at: datetime | None


class AttackSummary(BaseModel):
    id: UUID
    owner_id: UUID
    title: str | None
    target_link: str
    status: AttackStatus
    limit_kind: AttackLimitType
    limit_value: int
    sent_count: int
    claimed_count: int
    version: int
    started_at: datetime | None
    finished_at: datetime | None
    deadline_at: datetime | None
    end_reason: AttackEndReason | None
    slowmode_seconds: int | None
    agents: list[AttackAgent]


class AttackMedia(BaseModel):
    """Картинка детали: ``url`` не приходит, если Storage не настроен или файла нет."""

    path: str
    name: str
    url: str | None = None

    @model_serializer
    def _omit_missing_url(self) -> dict[str, str]:
        data = {"path": self.path, "name": self.name}
        if self.url is not None:
            data["url"] = self.url
        return data


class AttackDetail(AttackSummary):
    texts: list[str]
    media: list[AttackMedia]


class AttackList(BaseModel):
    active: list[AttackSummary]
    archive: list[AttackSummary]


class AttackAgentAvailability(BaseModel):
    agent_id: UUID
    name: str
    state: AgentRuntimeState
    telegram_authorized: bool
    warmup_restricted_at: datetime | None
    active_attack_id: UUID | None


class UploadedAttackMedia(BaseModel):
    storage_path: str
    name: str
    mime_type: str
    size: int


class AttackMediaLink(BaseModel):
    url: str
    expires_in: int


def _get_attack_service(request: Request) -> AttackService:
    manager = getattr(request.app.state, "agent_manager", None)
    service = getattr(manager, "attacks", None) if manager is not None else None
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Режим атаки недоступен.",
        )
    return service


def _attack_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Атака не найдена",
    )


def _attack_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AttackNotFoundError):
        return _attack_not_found()
    if isinstance(exc, AttackVersionConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Атака уже изменена. Обновите страницу и повторите правку.",
        )
    if isinstance(exc, AttackStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


_ATTACK_ERRORS = (
    AttackNotFoundError,
    AttackVersionConflictError,
    AttackStateError,
    ValueError,
)


async def _owned_attack(service: AttackService, attack_id: UUID, user_id: UUID) -> AttackView:
    """Атака только своего владельца: чужая неотличима от несуществующей."""
    view = await service.get(attack_id)
    if view is None or view.owner_id != user_id:
        raise _attack_not_found()
    return view


async def _agent_names(service: AttackService, owner_id: UUID) -> dict[UUID, str]:
    rows = await service.agent_availability(owner_id)
    return {row.agent_id: row.name for row in rows}


def _clean_title(title: str | None) -> str | None:
    if title is None:
        return None
    cleaned = title.strip()
    return cleaned or None


def _ensure_attack_media_path(owner_id: UUID, path: str) -> None:
    """Картинка атаки обязана лежать в папке владельца.

    ``..``-сегменты отклоняются так же, как в медиа агента: URL-нормализация
    внутри Storage-клиента иначе увела бы запрос в чужую папку.
    """
    segments = [segment for segment in path.split("/") if segment]
    if not path.startswith(f"attacks/{owner_id}/") or ".." in segments or path.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к этому файлу",
        )


def _config_from(payload: AttackCreateRequest, owner_id: UUID) -> AttackConfig:
    for image in payload.images:
        _ensure_attack_media_path(owner_id, image.path)
    config = AttackConfig(
        title=_clean_title(payload.title),
        target=parse_target_link(payload.target_link),
        texts=tuple(payload.texts),
        media_paths=tuple(image.path for image in payload.images),
        limit=payload.build_limit(),
    )
    validate_config(config)
    return config


def _patch_from(payload: AttackPatchRequest, owner_id: UUID, target: TargetRef) -> AttackPatch:
    for image in payload.images:
        _ensure_attack_media_path(owner_id, image.path)
    title = _clean_title(payload.title)
    texts = tuple(payload.texts)
    media_paths = tuple(image.path for image in payload.images)
    limit = payload.build_limit()
    validate_config(
        AttackConfig(
            title=title,
            target=target,
            texts=texts,
            media_paths=media_paths,
            limit=limit,
        )
    )
    return AttackPatch(
        version=payload.version,
        title=title,
        texts=texts,
        media_paths=media_paths,
        limit=limit,
    )


def _media_name(path: str) -> str:
    return path.rsplit("/", 1)[-1] or path


async def _signed_url(request: Request, path: str) -> str | None:
    signer = getattr(request.app.state, "media_link_signer", None)
    if signer is None:
        return None
    try:
        return await signer.sign_link(path, ttl=MEDIA_LINK_TTL)
    except Exception:
        logger.warning("Не удалось подписать ссылку на %s", path, exc_info=True)
        return None


async def _detail_media(request: Request, paths: Sequence[str]) -> list[AttackMedia]:
    return [
        AttackMedia(path=path, name=_media_name(path), url=await _signed_url(request, path))
        for path in paths
    ]


def _agent(participation: ParticipationView, names: Mapping[UUID, str]) -> AttackAgent:
    return AttackAgent(
        id=participation.id,
        attack_id=participation.attack_id,
        agent_id=participation.agent_id,
        name=names.get(participation.agent_id, "Мимик"),
        status=participation.status,
        sent_count=participation.sent_count,
        next_at=participation.next_at,
        last_error=participation.last_error,
        exit_reason=participation.exit_reason,
        note_written_at=participation.note_written_at,
    )


def _summary(view: AttackView, names: Mapping[UUID, str]) -> AttackSummary:
    return AttackSummary(
        id=view.id,
        owner_id=view.owner_id,
        title=view.config.title,
        target_link=view.config.target.link,
        status=view.status,
        limit_kind=view.config.limit_type,
        limit_value=view.config.limit_value,
        sent_count=view.sent_count,
        claimed_count=view.claimed_count,
        version=view.version,
        started_at=view.started_at,
        finished_at=view.finished_at,
        deadline_at=view.deadline_at,
        end_reason=view.end_reason,
        slowmode_seconds=view.slowmode_seconds,
        agents=[_agent(row, names) for row in view.participations],
    )


async def _detail(
    request: Request,
    view: AttackView,
    names: Mapping[UUID, str],
) -> AttackDetail:
    media = await _detail_media(request, view.config.media_paths)
    base = _summary(view, names)
    return AttackDetail(
        **base.model_dump(),
        texts=list(view.config.texts),
        media=media,
    )


async def _load_detail(
    request: Request,
    service: AttackService,
    attack_id: UUID,
    user_id: UUID,
) -> AttackDetail:
    view = await _owned_attack(service, attack_id, user_id)
    return await _detail(request, view, await _agent_names(service, user_id))


@router.get("/attacks/agents", response_model=list[AttackAgentAvailability])
async def list_attack_agents(
    request: Request,
    current_user: CurrentUserDep,
) -> list[AttackAgentAvailability]:
    """Мимики владельца для пикера: ограничение и чужая атака видны сразу."""
    service = _get_attack_service(request)
    rows = await service.agent_availability(current_user.user_id)
    manager = getattr(request.app.state, "agent_manager", None)
    runtime_states: dict[UUID, AgentRuntimeState] = {}
    if manager is not None:
        statuses = await manager.list_agents(owner_id=current_user.user_id)
        runtime_states = {item.agent_id: item.state for item in statuses}
    return [
        AttackAgentAvailability(
            agent_id=item.agent_id,
            name=item.name,
            state=runtime_states.get(item.agent_id, item.state),
            telegram_authorized=item.telegram_authorized,
            warmup_restricted_at=item.warmup_restricted_at,
            active_attack_id=item.active_attack_id,
        )
        for item in rows
    ]


@router.post(
    "/attacks",
    response_model=AttackDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_attack(
    payload: AttackCreateRequest,
    request: Request,
    current_user: CurrentUserDep,
) -> AttackDetail:
    service = _get_attack_service(request)
    try:
        config = _config_from(payload, current_user.user_id)
        view = await service.create_attack(current_user.user_id, config, payload.agent_ids)
    except HTTPException:
        raise
    except _ATTACK_ERRORS as exc:
        raise _attack_http_error(exc) from exc
    return await _detail(request, view, await _agent_names(service, current_user.user_id))


@router.get("/attacks", response_model=AttackList)
async def list_attacks(
    request: Request,
    current_user: CurrentUserDep,
) -> AttackList:
    service = _get_attack_service(request)
    views = await service.list(current_user.user_id)
    names = await _agent_names(service, current_user.user_id)
    active = [
        _summary(view, names)
        for view in views
        if view.status in (AttackStatus.DRAFT, AttackStatus.RUNNING)
    ]
    archive = [
        _summary(view, names)
        for view in views
        if view.status in (AttackStatus.CANCELLED, AttackStatus.FINISHED)
    ]
    return AttackList(active=active, archive=archive)


@router.get("/attacks/{attack_id}", response_model=AttackDetail)
async def get_attack(
    attack_id: UUID,
    request: Request,
    current_user: CurrentUserDep,
) -> AttackDetail:
    return await _load_detail(
        request,
        _get_attack_service(request),
        attack_id,
        current_user.user_id,
    )


@router.patch("/attacks/{attack_id}", response_model=AttackDetail)
async def update_attack(
    attack_id: UUID,
    payload: AttackPatchRequest,
    request: Request,
    current_user: CurrentUserDep,
) -> AttackDetail:
    service = _get_attack_service(request)
    current = await _owned_attack(service, attack_id, current_user.user_id)
    try:
        patch = _patch_from(payload, current_user.user_id, current.config.target)
        view = await service.update_attack(attack_id, patch)
    except HTTPException:
        raise
    except _ATTACK_ERRORS as exc:
        raise _attack_http_error(exc) from exc
    return await _detail(request, view, await _agent_names(service, current_user.user_id))


@router.post("/attacks/{attack_id}/start", response_model=AttackDetail)
async def start_attack(
    attack_id: UUID,
    request: Request,
    current_user: CurrentUserDep,
) -> AttackDetail:
    service = _get_attack_service(request)
    await _owned_attack(service, attack_id, current_user.user_id)
    try:
        await service.start_attack(attack_id)
    except _ATTACK_ERRORS as exc:
        raise _attack_http_error(exc) from exc
    return await _load_detail(request, service, attack_id, current_user.user_id)


@router.post("/attacks/{attack_id}/cancel", response_model=AttackDetail)
async def cancel_attack(
    attack_id: UUID,
    request: Request,
    current_user: CurrentUserDep,
) -> AttackDetail:
    service = _get_attack_service(request)
    await _owned_attack(service, attack_id, current_user.user_id)
    try:
        await service.cancel_attack(attack_id, AttackEndReason.CANCELLED_BY_USER)
    except _ATTACK_ERRORS as exc:
        raise _attack_http_error(exc) from exc
    return await _load_detail(request, service, attack_id, current_user.user_id)


@router.post(
    "/attacks/{attack_id}/repeat",
    response_model=AttackDetail,
    status_code=status.HTTP_201_CREATED,
)
async def repeat_attack(
    attack_id: UUID,
    request: Request,
    current_user: CurrentUserDep,
) -> AttackDetail:
    service = _get_attack_service(request)
    await _owned_attack(service, attack_id, current_user.user_id)
    try:
        view = await service.repeat_attack(attack_id)
    except _ATTACK_ERRORS as exc:
        raise _attack_http_error(exc) from exc
    return await _detail(request, view, await _agent_names(service, current_user.user_id))


@router.post("/attacks/{attack_id}/agents", response_model=AttackDetail)
async def add_attack_agent(
    attack_id: UUID,
    payload: AttackAgentRequest,
    request: Request,
    current_user: CurrentUserDep,
) -> AttackDetail:
    service = _get_attack_service(request)
    await _owned_attack(service, attack_id, current_user.user_id)
    try:
        await service.assign_agent(attack_id, payload.agent_id)
    except AttackNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Мимик не найден",
        ) from exc
    except _ATTACK_ERRORS as exc:
        raise _attack_http_error(exc) from exc
    return await _load_detail(request, service, attack_id, current_user.user_id)


@router.delete("/attacks/{attack_id}/agents/{agent_id}", response_model=AttackDetail)
async def remove_attack_agent(
    attack_id: UUID,
    agent_id: UUID,
    request: Request,
    current_user: CurrentUserDep,
) -> AttackDetail:
    service = _get_attack_service(request)
    await _owned_attack(service, attack_id, current_user.user_id)
    try:
        await service.pause_agent(attack_id, agent_id)
    except AttackNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Мимик не участвует в этой атаке",
        ) from exc
    except _ATTACK_ERRORS as exc:
        raise _attack_http_error(exc) from exc
    return await _load_detail(request, service, attack_id, current_user.user_id)


def _media_uploader(request: Request) -> AttackMediaUploader:
    storage = getattr(request.app.state, "media_uploader", None)
    if not isinstance(storage, AttackMediaUploader):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Медиа недоступно.",
        )
    return storage


def _media_reader(request: Request) -> AttackMediaReader:
    storage = getattr(request.app.state, "media_uploader", None)
    if not isinstance(storage, AttackMediaReader):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Медиа недоступно.",
        )
    return storage


@router.post(
    "/attack-media",
    response_model=UploadedAttackMedia,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attack_media(
    request: Request,
    current_user: CurrentUserDep,
    file: Annotated[UploadFile, File()],
) -> UploadedAttackMedia:
    storage = _media_uploader(request)
    data = await read_limited_upload(file, MAX_PHOTO_BYTES)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Картинка больше {MAX_PHOTO_BYTES // (1024 * 1024)} МБ",
        )
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Файл пуст")
    photo_type = await asyncio.to_thread(detect_photo_type, data)
    if photo_type is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Поддерживаются только изображения JPEG и PNG",
        )
    mime_type, extension = photo_type
    uploaded = await storage.upload_at_prefix(
        path_prefix=f"attacks/{current_user.user_id}",
        filename=safe_upload_name(file.filename, extension),
        data=data,
        mime_type=mime_type,
        kind="photo",
    )
    if uploaded is None or uploaded.storage_path is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Не удалось сохранить файл",
        )
    return UploadedAttackMedia(
        storage_path=uploaded.storage_path,
        name=uploaded.name,
        mime_type=uploaded.mime_type,
        size=uploaded.size,
    )


@router.get("/attack-media/{path:path}")
async def get_attack_media(
    path: str,
    request: Request,
    current_user: CurrentUserDep,
) -> Response:
    storage = _media_reader(request)
    _ensure_attack_media_path(current_user.user_id, path)
    data = await storage.open(path)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    extension = path.rsplit(".", 1)[-1].lower()
    media_type = _IMAGE_CONTENT_TYPES.get(extension, "application/octet-stream")
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/attack-media-link/{path:path}", response_model=AttackMediaLink)
async def get_attack_media_link(
    path: str,
    request: Request,
    current_user: CurrentUserDep,
    response: Response,
) -> AttackMediaLink:
    _ensure_attack_media_path(current_user.user_id, path)
    signer = getattr(request.app.state, "media_link_signer", None)
    if signer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Медиа недоступно.",
        )
    url = await signer.sign_link(path, ttl=MEDIA_LINK_TTL)
    if url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    response.headers["Cache-Control"] = "no-store"
    return AttackMediaLink(url=url, expires_in=int(MEDIA_LINK_TTL.total_seconds()))
