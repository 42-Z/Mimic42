from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from mimic42.core.admin import (
    AdminNotFoundError,
    AdminPage,
    AdminPresetDetail,
    AdminPresetSummary,
    PresetCreateValues,
    PresetPatchValues,
)


class FakeAdminRepository:
    """In-memory administrator repository for API contract tests."""

    def __init__(
        self,
        *,
        admin_ids: set[UUID] | None = None,
        unavailable: bool = False,
        presets: list[AdminPresetDetail] | None = None,
    ) -> None:
        self.admin_ids = set(admin_ids or ())
        self.unavailable = unavailable
        self.calls: list[UUID] = []
        self.presets = {preset.id: preset for preset in presets or []}
        self.preset_calls: list[tuple[str, dict[str, Any]]] = []

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
