from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.admin import (
    AdminNotFoundError,
    AdminPage,
    AdminPresetDetail,
    AdminPresetKind,
    AdminPresetSummary,
    AdminUnavailableError,
    PresetCreateValues,
    PresetPatchValues,
    PublicTelegramSettings,
    StoredTelegramSettings,
)
from mimic42.integrations.database_models import (
    AdminAuditLogModel,
    AdminUserModel,
    PlatformTelegramSettingsModel,
    ProfileModel,
    PromptPresetModel,
)


class DatabaseAdminRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def is_admin(self, user_id: UUID) -> bool:
        statement = select(exists().where(AdminUserModel.user_id == user_id))
        try:
            async with self._session_factory() as session:
                return bool(await session.scalar(statement))
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None

    async def read_telegram_settings(self) -> StoredTelegramSettings | None:
        try:
            async with self._session_factory() as session:
                row = (
                    await session.execute(
                        select(
                            PlatformTelegramSettingsModel.api_id,
                            PlatformTelegramSettingsModel.api_hash_ciphertext,
                            PlatformTelegramSettingsModel.updated_at,
                            PlatformTelegramSettingsModel.updated_by,
                        ).where(PlatformTelegramSettingsModel.id == 1)
                    )
                ).one_or_none()
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None
        if row is None:
            return None
        return StoredTelegramSettings(
            api_id=row.api_id,
            api_hash_ciphertext=row.api_hash_ciphertext,
            updated_at=row.updated_at,
            updated_by=row.updated_by,
        )

    async def read_telegram_settings_status(self) -> PublicTelegramSettings | None:
        try:
            async with self._session_factory() as session:
                row = (
                    await session.execute(
                        select(
                            PlatformTelegramSettingsModel.api_id,
                            PlatformTelegramSettingsModel.updated_at,
                            PlatformTelegramSettingsModel.updated_by,
                        ).where(PlatformTelegramSettingsModel.id == 1)
                    )
                ).one_or_none()
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None
        if row is None:
            return None
        return PublicTelegramSettings(
            api_id=row.api_id,
            has_api_hash=True,
            source="database",
            updated_at=row.updated_at,
            updated_by=row.updated_by,
        )

    async def save_telegram_settings(
        self,
        *,
        api_id: int,
        api_hash_ciphertext: str,
        actor_user_id: UUID,
    ) -> PublicTelegramSettings:
        updated_at = datetime.now(UTC)
        statement = postgres_insert(PlatformTelegramSettingsModel).values(
            id=1,
            api_id=api_id,
            api_hash_ciphertext=api_hash_ciphertext,
            updated_by=actor_user_id,
            updated_at=updated_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[PlatformTelegramSettingsModel.id],
            set_={
                "api_id": statement.excluded.api_id,
                "api_hash_ciphertext": statement.excluded.api_hash_ciphertext,
                "updated_by": statement.excluded.updated_by,
                "updated_at": statement.excluded.updated_at,
            },
        ).returning(
            PlatformTelegramSettingsModel.api_id,
            PlatformTelegramSettingsModel.updated_at,
            PlatformTelegramSettingsModel.updated_by,
        )
        try:
            async with self._session_factory() as session, session.begin():
                row = (await session.execute(statement)).one()
                await self._append_audit(
                    session,
                    actor_user_id=actor_user_id,
                    action="telegram.settings_updated",
                    object_id=None,
                    metadata={"credentials_replaced": True},
                )
                result = PublicTelegramSettings(
                    api_id=row.api_id,
                    has_api_hash=True,
                    source="database",
                    updated_at=row.updated_at,
                    updated_by=row.updated_by,
                )
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None
        return result

    async def list_presets(
        self,
        *,
        q: str,
        kind: AdminPresetKind,
        page: int,
        page_size: int,
    ) -> AdminPage[AdminPresetSummary]:
        conditions = [
            or_(
                PromptPresetModel.owner_id.is_(None),
                PromptPresetModel.published_at.is_not(None),
            )
        ]
        if kind == "official":
            conditions.append(PromptPresetModel.owner_id.is_(None))
        elif kind == "published":
            conditions.extend(
                (
                    PromptPresetModel.owner_id.is_not(None),
                    PromptPresetModel.published_at.is_not(None),
                )
            )
        search = q.strip()
        if search:
            conditions.append(
                or_(
                    PromptPresetModel.title.icontains(search, autoescape=True),
                    PromptPresetModel.summary.icontains(search, autoescape=True),
                )
            )

        try:
            async with self._session_factory() as session:
                total = await session.scalar(
                    select(func.count()).select_from(PromptPresetModel).where(*conditions)
                )
                rows = (
                    await session.execute(
                        select(
                            PromptPresetModel.id,
                            PromptPresetModel.owner_id,
                            ProfileModel.display_name.label("owner_name"),
                            PromptPresetModel.title,
                            PromptPresetModel.summary,
                            PromptPresetModel.sort_order,
                            PromptPresetModel.is_active,
                            PromptPresetModel.published_at,
                            PromptPresetModel.updated_at,
                        )
                        .outerjoin(ProfileModel, ProfileModel.id == PromptPresetModel.owner_id)
                        .where(*conditions)
                        .order_by(
                            case((PromptPresetModel.owner_id.is_(None), 0), else_=1),
                            PromptPresetModel.sort_order,
                            PromptPresetModel.title,
                            PromptPresetModel.id,
                        )
                        .limit(page_size)
                        .offset((page - 1) * page_size)
                    )
                ).all()
                items = [AdminPresetSummary.model_validate(row._mapping) for row in rows]
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None

        return AdminPage(items=items, total=total or 0, page=page, page_size=page_size)

    async def get_preset(self, preset_id: UUID) -> AdminPresetDetail:
        try:
            async with self._session_factory() as session:
                row = (
                    await session.execute(
                        select(PromptPresetModel, ProfileModel.display_name.label("owner_name"))
                        .outerjoin(ProfileModel, ProfileModel.id == PromptPresetModel.owner_id)
                        .where(
                            PromptPresetModel.id == preset_id,
                            or_(
                                PromptPresetModel.owner_id.is_(None),
                                PromptPresetModel.published_at.is_not(None),
                            ),
                        )
                    )
                ).one_or_none()
                if row is None:
                    raise AdminNotFoundError
                preset, owner_name = row
                return self._preset_detail(preset, owner_name=owner_name)
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None

    async def create_official_preset(
        self,
        values: PresetCreateValues,
        *,
        actor_user_id: UUID,
    ) -> AdminPresetDetail:
        preset_id = uuid4()
        preset = PromptPresetModel(
            id=preset_id,
            slug=f"official_{preset_id.hex}",
            title=values["title"],
            summary=values["summary"],
            body=values["body"],
            settings=values["settings"],
            sort_order=values["sort_order"],
            owner_id=None,
            published_at=None,
            is_active=True,
        )
        try:
            async with self._session_factory() as session, session.begin():
                session.add(preset)
                await session.flush()
                await self._append_audit(
                    session,
                    actor_user_id=actor_user_id,
                    action="preset.created",
                    object_id=preset_id,
                    metadata={"fields": sorted(values)},
                )
                await session.refresh(preset)
                result = self._preset_detail(preset, owner_name=None)
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None
        return result

    async def update_official_preset(
        self,
        preset_id: UUID,
        values: PresetPatchValues,
        *,
        actor_user_id: UUID,
    ) -> AdminPresetDetail:
        try:
            async with self._session_factory() as session, session.begin():
                preset = await session.scalar(
                    select(PromptPresetModel)
                    .where(
                        PromptPresetModel.id == preset_id,
                        PromptPresetModel.owner_id.is_(None),
                    )
                    .with_for_update()
                )
                if preset is None:
                    raise AdminNotFoundError

                patch = dict(values)
                changed_fields = sorted(
                    key for key, value in patch.items() if getattr(preset, key) != value
                )
                for field in changed_fields:
                    setattr(preset, field, patch[field])
                if changed_fields:
                    await session.flush()
                    await self._append_audit(
                        session,
                        actor_user_id=actor_user_id,
                        action="preset.updated",
                        object_id=preset_id,
                        metadata={"fields": changed_fields},
                    )
                    await session.refresh(preset)
                result = self._preset_detail(preset, owner_name=None)
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None
        return result

    async def set_preset_visibility(
        self,
        preset_id: UUID,
        is_active: bool,
        *,
        actor_user_id: UUID,
    ) -> AdminPresetDetail:
        try:
            async with self._session_factory() as session, session.begin():
                preset = await session.scalar(
                    select(PromptPresetModel)
                    .where(
                        PromptPresetModel.id == preset_id,
                        or_(
                            PromptPresetModel.owner_id.is_(None),
                            PromptPresetModel.published_at.is_not(None),
                        ),
                    )
                    .with_for_update()
                )
                if preset is None:
                    raise AdminNotFoundError

                old_value = preset.is_active
                if old_value != is_active:
                    preset.is_active = is_active
                    await session.flush()
                    await self._append_audit(
                        session,
                        actor_user_id=actor_user_id,
                        action="preset.visibility_changed",
                        object_id=preset_id,
                        metadata={"before": old_value, "after": is_active},
                    )
                    await session.refresh(preset)
                owner_name = await self._owner_name(session, preset.owner_id)
                result = self._preset_detail(preset, owner_name=owner_name)
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None
        return result

    @staticmethod
    async def _append_audit(
        session: AsyncSession,
        *,
        actor_user_id: UUID,
        action: str,
        object_id: UUID | None,
        metadata: dict[str, Any],
    ) -> None:
        session.add(
            AdminAuditLogModel(
                actor_user_id=actor_user_id,
                action=action,
                object_type="telegram_settings" if object_id is None else "preset",
                object_id=object_id,
                metadata_=metadata,
            )
        )
        await session.flush()

    @staticmethod
    async def _owner_name(session: AsyncSession, owner_id: UUID | None) -> str | None:
        if owner_id is None:
            return None
        return await session.scalar(
            select(ProfileModel.display_name).where(ProfileModel.id == owner_id)
        )

    @staticmethod
    def _preset_detail(
        preset: PromptPresetModel,
        *,
        owner_name: str | None,
    ) -> AdminPresetDetail:
        return AdminPresetDetail(
            id=preset.id,
            owner_id=preset.owner_id,
            owner_name=owner_name,
            title=preset.title,
            summary=preset.summary,
            sort_order=preset.sort_order,
            is_active=preset.is_active,
            published_at=preset.published_at,
            updated_at=preset.updated_at,
            body=preset.body,
            settings=preset.settings,
        )
