from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol, TypedDict
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_serializer

from mimic42.core.agent_runtime import AgentRuntimeState, TelegramProxyConfig


class AdminUnavailableError(Exception):
    """Administrative storage could not answer a request."""


class AdminNotFoundError(Exception):
    """An administrative operation could not find an accessible object."""


class AdminUserNotFoundError(AdminNotFoundError):
    """An administrative query could not find an accessible user."""


class AdminProxyNotFoundError(AdminNotFoundError):
    """An administrative proxy operation could not find the proxy."""


class AdminAgentNotFoundError(AdminNotFoundError):
    """An administrative proxy operation could not find the agent."""


class AdminSecretStorageError(Exception):
    """A secret cannot be stored or read because SECRET_KEY is unavailable."""


class AdminProxyValidationError(ValueError):
    """Proxy fields are inconsistent, e.g. a password without a username."""


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


class AdminAgentProxy(BaseModel):
    id: UUID
    label: str | None
    protocol: Literal["socks5", "http"]
    host: str
    port: int
    is_active: bool


class AdminAgentSummary(BaseModel):
    agent_id: UUID
    name: str
    llm_model: str
    state: AgentRuntimeState
    proxy: AdminAgentProxy | None = None


class AdminUserDetail(BaseModel):
    profile: AdminUserSummary
    agents: AdminPage[AdminAgentSummary]


class AdminProxySummary(BaseModel):
    id: UUID
    label: str | None
    protocol: Literal["socks5", "http"]
    host: str
    port: int
    username: str | None
    has_password: bool
    is_active: bool
    agents_total: int
    onboarding_total: int = 0
    created_at: datetime
    updated_at: datetime


class AdminProxyDetail(AdminProxySummary):
    created_by: UUID | None


class ProxyImportResult(BaseModel):
    imported: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


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
    # Расшифрованное значение — только для админ-формы. SecretStr маскирует его
    # в repr и логах; сериализатор отдаёт реальное значение в JSON ответа.
    api_hash: SecretStr | None = None
    has_api_hash: bool
    source: Literal["database", "unconfigured"]
    updated_at: datetime | None
    updated_by: UUID | None

    @field_serializer("api_hash", when_used="json")
    def _reveal_api_hash(self, value: SecretStr | None) -> str | None:
        return value.get_secret_value() if value is not None else None


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


def statistics_window(days: int, now: datetime) -> tuple[datetime, datetime]:
    if days not in (7, 30):
        raise ValueError("Статистика поддерживает периоды 7 или 30 дней")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Статистике требуется время с часовым поясом")
    utc_now = now.astimezone(UTC)
    utc_start = utc_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return utc_start - timedelta(days=days - 1), utc_now


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


class ProxyCreateValues(TypedDict):
    label: str | None
    protocol: Literal["socks5", "http"]
    host: str
    port: int
    username: str | None
    password: str | None
    is_active: bool


class ProxyPatchValues(TypedDict, total=False):
    label: str | None
    protocol: Literal["socks5", "http"]
    host: str
    port: int
    username: str | None
    password: str | None
    is_active: bool


AdminPresetKind = Literal["all", "official", "published"]
MAX_ADMIN_PAGE = 1_000_000
POSTGRES_INTEGER_MIN = -(2**31)
POSTGRES_INTEGER_MAX = 2**31 - 1


class StoredTelegramSettings(BaseModel):
    api_id: int
    api_hash_ciphertext: SecretStr
    updated_at: datetime
    updated_by: UUID | None


class TelegramSettingsStore(Protocol):
    """Хранилище пары Telegram-приложения — узкий срез AdminRepository."""

    async def read_telegram_settings(self) -> StoredTelegramSettings | None: ...

    async def save_telegram_settings(
        self,
        *,
        api_id: int,
        api_hash_ciphertext: str,
        actor_user_id: UUID,
    ) -> PublicTelegramSettings: ...


class AdminRepository(TelegramSettingsStore, Protocol):
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

    async def list_proxies(
        self,
        *,
        page: int,
        page_size: int,
    ) -> AdminPage[AdminProxySummary]: ...

    async def list_proxy_options(self) -> list[AdminAgentProxy]: ...

    async def read_proxy_config(self, proxy_id: UUID) -> TelegramProxyConfig: ...

    async def proxy_exists(
        self,
        *,
        protocol: Literal["socks5", "http"],
        host: str,
        port: int,
        username: str | None,
    ) -> bool: ...

    async def create_proxy(
        self,
        values: ProxyCreateValues,
        *,
        actor_user_id: UUID,
    ) -> AdminProxyDetail: ...

    async def update_proxy(
        self,
        proxy_id: UUID,
        values: ProxyPatchValues,
        *,
        actor_user_id: UUID,
    ) -> AdminProxyDetail: ...

    async def delete_proxy(self, proxy_id: UUID, *, actor_user_id: UUID) -> list[UUID]: ...

    async def assign_agent_proxy(
        self,
        agent_id: UUID,
        proxy_id: UUID | None,
        *,
        actor_user_id: UUID,
    ) -> AdminAgentProxy | None: ...

    async def statistics(
        self,
        *,
        days: Literal[7, 30],
        now: datetime,
        runtime_states: dict[UUID, AgentRuntimeState],
    ) -> AdminStatistics: ...
