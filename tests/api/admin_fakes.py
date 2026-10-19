from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import SecretStr

from mimic42.core.admin import (
    AdminNotFoundError,
    AdminPage,
    AdminPresetDetail,
    AdminPresetSummary,
    AdminUserDetail,
    AdminUserNotFoundError,
    AdminUserSummary,
    PresetCreateValues,
    PresetPatchValues,
    PublicTelegramSettings,
    StoredTelegramSettings,
)
from mimic42.core.agent_runtime import AgentRuntimeState


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

    async def read_telegram_settings_status(self) -> PublicTelegramSettings | None:
        self.telegram_calls.append(("status", {}))
        if self.telegram_settings_error is not None:
            raise self.telegram_settings_error
        if self.telegram_settings is None:
            return None
        return PublicTelegramSettings(
            api_id=self.telegram_settings.api_id,
            has_api_hash=True,
            source="database",
            updated_at=self.telegram_settings.updated_at,
            updated_by=self.telegram_settings.updated_by,
        )

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
