from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Protocol, TypedDict
from uuid import UUID

from pydantic import BaseModel, SecretStr

from mimic42.core.agent_runtime import AgentRuntimeState


class AdminUnavailableError(Exception):
    """Administrative storage could not answer a request."""


class AdminNotFoundError(Exception):
    """An administrative operation could not find an accessible object."""


class AdminUserNotFoundError(AdminNotFoundError):
    """An administrative query could not find an accessible user."""


class AdminPage[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class AdminIdentity(BaseModel):
    user_id: UUID
    is_admin: bool


class AdminUserSummary(BaseModel):
    user_id: UUID
    email: str | None
    display_name: str | None
    created_at: datetime
    agents_total: int
    states: dict[AgentRuntimeState, int]


class AdminAgentSummary(BaseModel):
    agent_id: UUID
    name: str
    llm_model: str
    state: AgentRuntimeState


class AdminUserDetail(BaseModel):
    profile: AdminUserSummary
    agents: AdminPage[AdminAgentSummary]


class AdminPresetSummary(BaseModel):
    id: UUID
    owner_id: UUID | None
    owner_name: str | None
    title: str
    summary: str
    sort_order: int
    is_active: bool
    published_at: datetime | None
    updated_at: datetime


class AdminPresetDetail(AdminPresetSummary):
    body: str
    settings: dict[str, Any] | None


class PublicTelegramSettings(BaseModel):
    api_id: int | None
    has_api_hash: bool
    source: Literal["database", "environment", "unconfigured"]
    updated_at: datetime | None
    updated_by: UUID | None


class ActivityCounts(BaseModel):
    messages: int = 0
    actions: int = 0
    errors: int = 0


class DailyActivity(ActivityCounts):
    date: date


class AdminStatistics(BaseModel):
    users: int
    agents: int
    states: dict[AgentRuntimeState, int]
    input_tokens: int
    output_tokens: int
    period_days: Literal[7, 30]
    since: datetime
    until: datetime
    totals: ActivityCounts
    daily: list[DailyActivity]


class PresetCreateValues(TypedDict):
    title: str
    summary: str
    body: str
    settings: dict[str, Any] | None
    sort_order: int


class PresetPatchValues(TypedDict, total=False):
    title: str
    summary: str
    body: str
    settings: dict[str, Any] | None
    sort_order: int


AdminPresetKind = Literal["all", "official", "published"]
MAX_ADMIN_PAGE = 1_000_000
POSTGRES_INTEGER_MIN = -(2**31)
POSTGRES_INTEGER_MAX = 2**31 - 1


class StoredTelegramSettings(BaseModel):
    api_id: int
    api_hash_ciphertext: SecretStr
    updated_at: datetime
    updated_by: UUID | None


class AdminRepository(Protocol):
    async def is_admin(self, user_id: UUID) -> bool: ...

    async def list_users(
        self,
        *,
        q: str,
        page: int,
        page_size: int,
        runtime_states: dict[UUID, AgentRuntimeState],
    ) -> AdminPage[AdminUserSummary]: ...

    async def get_user(
        self,
        user_id: UUID,
        *,
        page: int,
        page_size: int,
        runtime_states: dict[UUID, AgentRuntimeState],
    ) -> AdminUserDetail: ...

    async def list_presets(
        self,
        *,
        q: str,
        kind: AdminPresetKind,
        page: int,
        page_size: int,
    ) -> AdminPage[AdminPresetSummary]: ...

    async def get_preset(self, preset_id: UUID) -> AdminPresetDetail: ...

    async def create_official_preset(
        self,
        values: PresetCreateValues,
        *,
        actor_user_id: UUID,
    ) -> AdminPresetDetail: ...

    async def update_official_preset(
        self,
        preset_id: UUID,
        values: PresetPatchValues,
        *,
        actor_user_id: UUID,
    ) -> AdminPresetDetail: ...

    async def set_preset_visibility(
        self,
        preset_id: UUID,
        is_active: bool,
        *,
        actor_user_id: UUID,
    ) -> AdminPresetDetail: ...

    async def read_telegram_settings(self) -> StoredTelegramSettings | None: ...

    async def read_telegram_settings_status(self) -> PublicTelegramSettings | None: ...

    async def save_telegram_settings(
        self,
        *,
        api_id: int,
        api_hash_ciphertext: str,
        actor_user_id: UUID,
    ) -> PublicTelegramSettings: ...

    async def statistics(
        self,
        *,
        days: Literal[7, 30],
        now: datetime,
        runtime_states: dict[UUID, AgentRuntimeState],
    ) -> AdminStatistics: ...
