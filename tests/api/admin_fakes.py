from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import SecretStr

from mimic42.core.admin import (
    AdminAgentNotFoundError,
    AdminAgentProxy,
    AdminNotFoundError,
    AdminPage,
    AdminPresetDetail,
    AdminPresetSummary,
    AdminProxyDetail,
    AdminProxyInUseError,
    AdminProxyNotFoundError,
    AdminProxySummary,
    AdminProxyValidationError,
    AdminSecretStorageError,
    AdminStatistics,
    AdminUserDetail,
    AdminUserNotFoundError,
    AdminUserSummary,
    PresetCreateValues,
    PresetPatchValues,
    ProxyCreateValues,
    ProxyPatchValues,
    PublicTelegramSettings,
    StoredTelegramSettings,
)
from mimic42.core.agent_runtime import AgentRuntimeState, TelegramProxyConfig


class FakeAdminRepository:
    """In-memory administrator repository for API contract tests."""

    def __init__(
        self,
        *,
        admin_ids: set[UUID] | None = None,
        unavailable: bool = False,
        presets: list[AdminPresetDetail] | None = None,
        telegram_settings: StoredTelegramSettings | None = None,
        users: list[AdminUserSummary] | None = None,
        user_details: dict[UUID, AdminUserDetail] | None = None,
        statistics_value: AdminStatistics | None = None,
        proxies: list[AdminProxyDetail] | None = None,
        proxy_configs: dict[UUID, TelegramProxyConfig] | None = None,
        agent_proxies: dict[UUID, AdminAgentProxy | None] | None = None,
        has_cipher: bool = True,
    ) -> None:
        self.admin_ids = set(admin_ids or ())
        self.unavailable = unavailable
        self.calls: list[UUID] = []
        self.presets = {preset.id: preset for preset in presets or []}
        self.preset_calls: list[tuple[str, dict[str, Any]]] = []
        self.telegram_settings = telegram_settings
        self.telegram_settings_error: Exception | None = None
        self.telegram_write_count = 0
        self.telegram_calls: list[tuple[str, dict[str, Any]]] = []
        self.users = {user.user_id: user for user in users or []}
        self.user_details = dict(user_details or {})
        self.user_calls: list[tuple[str, dict[str, Any]]] = []
        self.statistics_value = statistics_value
        self.statistics_error: Exception | None = None
        self.statistics_calls: list[dict[str, Any]] = []
        self.proxies = {proxy.id: proxy for proxy in proxies or []}
        self.proxy_configs = dict(proxy_configs or {})
        self.agent_proxies = dict(agent_proxies or {})
        self.has_cipher = has_cipher
        self.proxy_calls: list[tuple[str, dict[str, Any]]] = []

    async def is_admin(self, user_id: UUID) -> bool:
        self.calls.append(user_id)
        if self.unavailable:
            raise RuntimeError("postgresql://private-dsn SELECT from private_table")
        return user_id in self.admin_ids

    async def list_presets(
        self,
        *,
        q: str,
        kind: Literal["all", "official", "published"],
        page: int,
        page_size: int,
    ) -> AdminPage[AdminPresetSummary]:
        self.preset_calls.append(
            ("list", {"q": q, "kind": kind, "page": page, "page_size": page_size})
        )
        presets = [
            preset
            for preset in self.presets.values()
            if (preset.owner_id is None or preset.published_at is not None)
            and (kind == "all" or (kind == "official") == (preset.owner_id is None))
            and (not q or q.casefold() in f"{preset.title} {preset.summary}".casefold())
        ]
        presets.sort(
            key=lambda preset: (preset.sort_order, -preset.updated_at.timestamp(), str(preset.id))
        )
        start = (page - 1) * page_size
        items = [
            AdminPresetSummary.model_validate(preset.model_dump(exclude={"body", "settings"}))
            for preset in presets[start : start + page_size]
        ]
        return AdminPage(items=items, total=len(presets), page=page, page_size=page_size)

    async def get_preset(self, preset_id: UUID) -> AdminPresetDetail:
        self.preset_calls.append(("get", {"preset_id": preset_id}))
        preset = self.presets.get(preset_id)
        if preset is None or (preset.owner_id is not None and preset.published_at is None):
            raise AdminNotFoundError
        return preset

    async def create_official_preset(
        self,
        values: PresetCreateValues,
        *,
        actor_user_id: UUID,
    ) -> AdminPresetDetail:
        self.preset_calls.append(
            ("create", {"values": dict(values), "actor_user_id": actor_user_id})
        )
        now = datetime.now(UTC)
        preset = AdminPresetDetail(
            id=UUID(int=len(self.presets) + 1),
            owner_id=None,
            owner_name=None,
            title=values["title"],
            summary=values["summary"],
            sort_order=values["sort_order"],
            is_active=True,
            published_at=None,
            updated_at=now,
            body=values["body"],
            settings=values["settings"],
        )
        self.presets[preset.id] = preset
        return preset

    async def update_official_preset(
        self,
        preset_id: UUID,
        values: PresetPatchValues,
        *,
        actor_user_id: UUID,
    ) -> AdminPresetDetail:
        self.preset_calls.append(
            (
                "update",
                {
                    "preset_id": preset_id,
                    "values": dict(values),
                    "actor_user_id": actor_user_id,
                },
            )
        )
        preset = self.presets.get(preset_id)
        if preset is None or preset.owner_id is not None:
            raise AdminNotFoundError
        updated = preset.model_copy(update={**values, "updated_at": datetime.now(UTC)})
        self.presets[preset_id] = updated
        return updated

    async def set_preset_visibility(
        self,
        preset_id: UUID,
        is_active: bool,
        *,
        actor_user_id: UUID,
    ) -> AdminPresetDetail:
        self.preset_calls.append(
            (
                "visibility",
                {
                    "preset_id": preset_id,
                    "is_active": is_active,
                    "actor_user_id": actor_user_id,
                },
            )
        )
        preset = self.presets.get(preset_id)
        if preset is None or (preset.owner_id is not None and preset.published_at is None):
            raise AdminNotFoundError
        updated = preset.model_copy(
            update={"is_active": is_active, "updated_at": datetime.now(UTC)}
        )
        self.presets[preset_id] = updated
        return updated

    async def read_telegram_settings(self) -> StoredTelegramSettings | None:
        self.telegram_calls.append(("read", {}))
        if self.telegram_settings_error is not None:
            raise self.telegram_settings_error
        return self.telegram_settings

    async def save_telegram_settings(
        self,
        *,
        api_id: int,
        api_hash_ciphertext: str,
        actor_user_id: UUID,
    ) -> PublicTelegramSettings:
        self.telegram_calls.append(
            (
                "save",
                {
                    "api_id": api_id,
                    "api_hash_ciphertext": api_hash_ciphertext,
                    "actor_user_id": actor_user_id,
                },
            )
        )
        if self.telegram_settings_error is not None:
            raise self.telegram_settings_error
        self.telegram_write_count += 1
        self.telegram_settings = StoredTelegramSettings(
            api_id=api_id,
            api_hash_ciphertext=SecretStr(api_hash_ciphertext),
            updated_at=datetime.now(UTC),
            updated_by=actor_user_id,
        )
        return PublicTelegramSettings(
            api_id=api_id,
            has_api_hash=True,
            source="database",
            updated_at=self.telegram_settings.updated_at,
            updated_by=actor_user_id,
        )

    async def list_users(
        self,
        *,
        q: str,
        page: int,
        page_size: int,
        runtime_states: dict[UUID, AgentRuntimeState],
    ) -> AdminPage[AdminUserSummary]:
        self.user_calls.append(
            (
                "list",
                {
                    "q": q,
                    "page": page,
                    "page_size": page_size,
                    "runtime_states": dict(runtime_states),
                },
            )
        )
        needle = q.strip().casefold()
        users = [
            user
            for user in self.users.values()
            if not needle or needle in f"{user.email or ''} {user.display_name or ''}".casefold()
        ]
        users.sort(key=lambda user: (user.created_at, str(user.user_id)), reverse=True)
        start = (page - 1) * page_size
        return AdminPage(
            items=users[start : start + page_size],
            total=len(users),
            page=page,
            page_size=page_size,
        )

    async def get_user(
        self,
        user_id: UUID,
        *,
        page: int,
        page_size: int,
        runtime_states: dict[UUID, AgentRuntimeState],
    ) -> AdminUserDetail:
        self.user_calls.append(
            (
                "get",
                {
                    "user_id": user_id,
                    "page": page,
                    "page_size": page_size,
                    "runtime_states": dict(runtime_states),
                },
            )
        )
        detail = self.user_details.get(user_id)
        if detail is None:
            raise AdminUserNotFoundError
        return detail

    async def list_proxies(
        self,
        *,
        page: int,
        page_size: int,
    ) -> AdminPage[AdminProxySummary]:
        self.proxy_calls.append(("list", {"page": page, "page_size": page_size}))
        proxies = sorted(
            self.proxies.values(),
            key=lambda proxy: (proxy.created_at, str(proxy.id)),
            reverse=True,
        )
        start = (page - 1) * page_size
        items = [
            AdminProxySummary.model_validate(proxy.model_dump())
            for proxy in proxies[start : start + page_size]
        ]
        return AdminPage(items=items, total=len(proxies), page=page, page_size=page_size)

    async def list_proxy_options(self) -> list[AdminAgentProxy]:
        self.proxy_calls.append(("options", {}))
        return [
            AdminAgentProxy(
                id=proxy.id,
                label=proxy.label,
                protocol=proxy.protocol,
                host=proxy.host,
                port=proxy.port,
                is_active=proxy.is_active,
            )
            for proxy in self.proxies.values()
            if proxy.is_active
        ]

    async def read_proxy_config(self, proxy_id: UUID) -> TelegramProxyConfig:
        self.proxy_calls.append(("config", {"proxy_id": proxy_id}))
        if proxy_id not in self.proxies:
            raise AdminProxyNotFoundError
        config = self.proxy_configs.get(proxy_id)
        if config is None:
            raise AdminSecretStorageError("Пароль прокси недоступен")
        return config

    async def create_proxy(
        self,
        values: ProxyCreateValues,
        *,
        actor_user_id: UUID,
    ) -> AdminProxyDetail:
        self.proxy_calls.append(
            ("create", {"values": dict(values), "actor_user_id": actor_user_id})
        )
        if values.get("password") and not self.has_cipher:
            raise AdminSecretStorageError("SECRET_KEY не настроен")
        if values.get("password") and not values.get("username"):
            raise AdminProxyValidationError("Для пароля укажите логин прокси")
        now = datetime.now(UTC)
        proxy = AdminProxyDetail(
            id=UUID(int=len(self.proxies) + 1),
            label=values["label"],
            protocol=values["protocol"],
            host=values["host"],
            port=values["port"],
            username=values.get("username"),
            has_password=bool(values.get("password")),
            is_active=values["is_active"],
            agents_total=0,
            onboarding_total=0,
            created_at=now,
            updated_at=now,
            created_by=actor_user_id,
        )
        self.proxies[proxy.id] = proxy
        return proxy

    async def update_proxy(
        self,
        proxy_id: UUID,
        values: ProxyPatchValues,
        *,
        actor_user_id: UUID,
    ) -> AdminProxyDetail:
        self.proxy_calls.append(
            (
                "update",
                {"proxy_id": proxy_id, "values": dict(values), "actor_user_id": actor_user_id},
            )
        )
        proxy = self.proxies.get(proxy_id)
        if proxy is None:
            raise AdminProxyNotFoundError
        if values.get("password") and not self.has_cipher:
            raise AdminSecretStorageError("SECRET_KEY не настроен")
        updated = proxy.model_copy(
            update={
                **{key: value for key, value in values.items() if key != "password"},
                "has_password": proxy.has_password or bool(values.get("password")),
                "updated_at": datetime.now(UTC),
            }
        )
        if updated.has_password and not updated.username:
            raise AdminProxyValidationError("Для пароля укажите логин прокси")
        self.proxies[proxy_id] = updated
        return updated

    async def delete_proxy(self, proxy_id: UUID, *, actor_user_id: UUID) -> None:
        self.proxy_calls.append(("delete", {"proxy_id": proxy_id, "actor_user_id": actor_user_id}))
        proxy = self.proxies.get(proxy_id)
        if proxy is None:
            raise AdminProxyNotFoundError
        if proxy.agents_total > 0:
            raise AdminProxyInUseError
        del self.proxies[proxy_id]

    async def assign_agent_proxy(
        self,
        agent_id: UUID,
        proxy_id: UUID | None,
        *,
        actor_user_id: UUID,
    ) -> AdminAgentProxy | None:
        self.proxy_calls.append(
            (
                "assign",
                {"agent_id": agent_id, "proxy_id": proxy_id, "actor_user_id": actor_user_id},
            )
        )
        if agent_id not in self.agent_proxies and agent_id not in {
            agent.agent_id for detail in self.user_details.values() for agent in detail.agents.items
        }:
            raise AdminAgentNotFoundError
        if proxy_id is None:
            self.agent_proxies[agent_id] = None
            return None
        proxy = self.proxies.get(proxy_id)
        if proxy is None:
            raise AdminProxyNotFoundError
        assigned = AdminAgentProxy(
            id=proxy.id,
            label=proxy.label,
            protocol=proxy.protocol,
            host=proxy.host,
            port=proxy.port,
            is_active=proxy.is_active,
        )
        self.agent_proxies[agent_id] = assigned
        return assigned

    async def statistics(
        self,
        *,
        days: Literal[7, 30],
        now: datetime,
        runtime_states: dict[UUID, AgentRuntimeState],
    ) -> AdminStatistics:
        self.statistics_calls.append(
            {
                "days": days,
                "now": now,
                "runtime_states": dict(runtime_states),
            }
        )
        if self.statistics_error is not None:
            raise self.statistics_error
        if self.statistics_value is None:
            raise RuntimeError("Statistics fake value was not configured")
        return self.statistics_value
