from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import case, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.admin import (
    ActivityCounts,
    AdminAgentNotFoundError,
    AdminAgentProxy,
    AdminAgentSummary,
    AdminNotFoundError,
    AdminPage,
    AdminPresetDetail,
    AdminPresetKind,
    AdminPresetSummary,
    AdminProxyDetail,
    AdminProxyNotFoundError,
    AdminProxySummary,
    AdminProxyValidationError,
    AdminSecretStorageError,
    AdminStatistics,
    AdminUnavailableError,
    AdminUserDetail,
    AdminUserNotFoundError,
    AdminUserSummary,
    DailyActivity,
    PresetCreateValues,
    PresetPatchValues,
    ProxyCreateValues,
    ProxyPatchValues,
    PublicTelegramSettings,
    StoredTelegramSettings,
    statistics_window,
)
from mimic42.core.agent_runtime import AgentRuntimeState, TelegramProxyConfig
from mimic42.core.model_catalog import DEFAULT_LLM_MODEL
from mimic42.core.onboarding import SecretCipher
from mimic42.integrations.database_admin_statistics import (
    effective_agents_cte,
    runtime_state_parameters,
    statistics_statement,
)
from mimic42.integrations.database_models import (
    AdminAuditLogModel,
    AdminUserModel,
    AgentModel,
    AgentOnboardingSessionModel,
    PlatformTelegramSettingsModel,
    ProfileModel,
    PromptPresetModel,
    TelegramProxyModel,
    TelegramSessionModel,
)
from mimic42.integrations.database_proxies import telegram_proxy_config


class DatabaseAdminRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        cipher: SecretCipher | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher

    async def is_admin(self, user_id: UUID) -> bool:
        statement = select(exists().where(AdminUserModel.user_id == user_id))
        try:
            async with self._session_factory() as session:
                return bool(await session.scalar(statement))
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None

    async def list_users(
        self,
        *,
        q: str,
        page: int,
        page_size: int,
        runtime_states: dict[UUID, AgentRuntimeState],
    ) -> AdminPage[AdminUserSummary]:
        search = q.strip()
        conditions = []
        if search:
            conditions.append(
                or_(
                    ProfileModel.email.icontains(search, autoescape=True),
                    ProfileModel.display_name.icontains(search, autoescape=True),
                )
            )

        try:
            async with self._session_factory() as session:
                total = await session.scalar(
                    select(func.count()).select_from(ProfileModel).where(*conditions)
                )
                profile_rows = (
                    await session.execute(
                        select(
                            ProfileModel.id,
                            ProfileModel.email,
                            ProfileModel.display_name,
                            ProfileModel.created_at,
                        )
                        .where(*conditions)
                        .order_by(ProfileModel.created_at.desc(), ProfileModel.id.desc())
                        .limit(page_size)
                        .offset((page - 1) * page_size)
                    )
                ).all()

                owner_ids = [row.id for row in profile_rows]
                state_rows = []
                if owner_ids:
                    effective_agents = effective_agents_cte()
                    state_rows = (
                        await session.execute(
                            select(
                                effective_agents.c.owner_id,
                                effective_agents.c.state,
                                func.count().label("agents_count"),
                            )
                            .where(effective_agents.c.owner_id.in_(owner_ids))
                            .group_by(effective_agents.c.owner_id, effective_agents.c.state),
                            runtime_state_parameters(runtime_states),
                        )
                    ).all()
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None

        states_by_owner: dict[UUID, dict[AgentRuntimeState, int]] = {}
        for row in state_rows:
            states_by_owner.setdefault(row.owner_id, {})[AgentRuntimeState(row.state)] = (
                row.agents_count
            )
        items = []
        for row in profile_rows:
            states = states_by_owner.get(row.id, {})
            items.append(
                AdminUserSummary(
                    user_id=row.id,
                    email=row.email,
                    display_name=row.display_name,
                    created_at=row.created_at,
                    agents_total=sum(states.values()),
                    states=states,
                )
            )
        return AdminPage(items=items, total=total or 0, page=page, page_size=page_size)

    async def get_user(
        self,
        user_id: UUID,
        *,
        page: int,
        page_size: int,
        runtime_states: dict[UUID, AgentRuntimeState],
    ) -> AdminUserDetail:
        try:
            async with self._session_factory() as session:
                profile = (
                    await session.execute(
                        select(
                            ProfileModel.id,
                            ProfileModel.email,
                            ProfileModel.display_name,
                            ProfileModel.created_at,
                        ).where(ProfileModel.id == user_id)
                    )
                ).one_or_none()
                if profile is None:
                    raise AdminUserNotFoundError

                effective_agents = effective_agents_cte()
                parameters = runtime_state_parameters(runtime_states)
                state_rows = (
                    await session.execute(
                        select(
                            effective_agents.c.state,
                            func.count().label("agents_count"),
                        )
                        .where(effective_agents.c.owner_id == user_id)
                        .group_by(effective_agents.c.state),
                        parameters,
                    )
                ).all()
                states = {AgentRuntimeState(row.state): row.agents_count for row in state_rows}
                agents_total = sum(states.values())
                model = func.coalesce(
                    func.nullif(effective_agents.c.settings["model"].as_string(), ""),
                    DEFAULT_LLM_MODEL,
                ).label("llm_model")
                agent_rows = (
                    await session.execute(
                        select(
                            effective_agents.c.agent_id,
                            effective_agents.c.name,
                            model,
                            effective_agents.c.state,
                            TelegramProxyModel.id.label("proxy_id"),
                            TelegramProxyModel.label.label("proxy_label"),
                            TelegramProxyModel.protocol.label("proxy_protocol"),
                            TelegramProxyModel.host.label("proxy_host"),
                            TelegramProxyModel.port.label("proxy_port"),
                            TelegramProxyModel.is_active.label("proxy_is_active"),
                        )
                        .outerjoin(
                            TelegramSessionModel,
                            TelegramSessionModel.agent_id == effective_agents.c.agent_id,
                        )
                        .outerjoin(
                            TelegramProxyModel,
                            TelegramProxyModel.id == TelegramSessionModel.proxy_id,
                        )
                        .where(effective_agents.c.owner_id == user_id)
                        .order_by(
                            effective_agents.c.created_at.desc(),
                            effective_agents.c.agent_id.desc(),
                        )
                        .limit(page_size)
                        .offset((page - 1) * page_size),
                        parameters,
                    )
                ).all()
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None

        profile_summary = AdminUserSummary(
            user_id=profile.id,
            email=profile.email,
            display_name=profile.display_name,
            created_at=profile.created_at,
            agents_total=agents_total,
            states=states,
        )
        agents = AdminPage(
            items=[
                AdminAgentSummary(
                    agent_id=row.agent_id,
                    name=row.name,
                    llm_model=row.llm_model,
                    state=AgentRuntimeState(row.state),
                    proxy=(
                        AdminAgentProxy(
                            id=row.proxy_id,
                            label=row.proxy_label,
                            protocol=row.proxy_protocol,
                            host=row.proxy_host,
                            port=row.proxy_port,
                            is_active=row.proxy_is_active,
                        )
                        if row.proxy_id is not None
                        else None
                    ),
                )
                for row in agent_rows
            ],
            total=agents_total,
            page=page,
            page_size=page_size,
        )
        return AdminUserDetail(profile=profile_summary, agents=agents)

    async def statistics(
        self,
        *,
        days: Literal[7, 30],
        now: datetime,
        runtime_states: dict[UUID, AgentRuntimeState],
    ) -> AdminStatistics:
        since, until = statistics_window(days, now)
        statement = statistics_statement(since, until)
        try:
            async with self._session_factory() as session:
                rows = (
                    await session.execute(
                        statement,
                        runtime_state_parameters(runtime_states),
                    )
                ).all()
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None
        if not rows:
            raise AdminUnavailableError("Administrative storage returned no statistics row")

        row = rows[0]
        states = {
            AgentRuntimeState(state): int(count) for state, count in (row.states or {}).items()
        }
        activity_by_date = {
            daily.date: ActivityCounts(
                messages=int(daily.messages or 0),
                actions=int(daily.actions or 0),
                errors=int(daily.errors or 0),
            )
            for daily in rows
            if daily.date is not None
        }
        daily_activity = []
        for offset in range(days):
            activity_date = since.date() + timedelta(days=offset)
            counts = activity_by_date.get(activity_date, ActivityCounts())
            daily_activity.append(
                DailyActivity(
                    date=activity_date,
                    messages=counts.messages,
                    actions=counts.actions,
                    errors=counts.errors,
                )
            )
        totals = ActivityCounts(
            messages=sum(day.messages for day in daily_activity),
            actions=sum(day.actions for day in daily_activity),
            errors=sum(day.errors for day in daily_activity),
        )
        return AdminStatistics(
            users=int(row.users),
            agents=int(row.agents),
            states=states,
            input_tokens=int(row.input_tokens or 0),
            output_tokens=int(row.output_tokens or 0),
            period_days=days,
            since=since,
            until=until,
            totals=totals,
            daily=daily_activity,
        )

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
                    object_type="telegram_settings",
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
                    object_type="preset",
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
                        object_type="preset",
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
                        object_type="preset",
                        object_id=preset_id,
                        metadata={"before": old_value, "after": is_active},
                    )
                    await session.refresh(preset)
                owner_name = await self._owner_name(session, preset.owner_id)
                result = self._preset_detail(preset, owner_name=owner_name)
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None
        return result

    async def list_proxies(
        self,
        *,
        page: int,
        page_size: int,
    ) -> AdminPage[AdminProxySummary]:
        agents_total = func.count(TelegramSessionModel.id).label("agents_total")
        pending_onboarding_total = (
            select(func.count())
            .select_from(AgentOnboardingSessionModel)
            .where(
                AgentOnboardingSessionModel.proxy_id == TelegramProxyModel.id,
                AgentOnboardingSessionModel.completed_agent_id.is_(None),
            )
            .correlate(TelegramProxyModel)
            .scalar_subquery()
            .label("onboarding_total")
        )
        try:
            async with self._session_factory() as session:
                total = await session.scalar(select(func.count()).select_from(TelegramProxyModel))
                rows = (
                    await session.execute(
                        select(TelegramProxyModel, agents_total, pending_onboarding_total)
                        .outerjoin(
                            TelegramSessionModel,
                            TelegramSessionModel.proxy_id == TelegramProxyModel.id,
                        )
                        .group_by(TelegramProxyModel.id)
                        .order_by(
                            TelegramProxyModel.created_at.desc(),
                            TelegramProxyModel.id.desc(),
                        )
                        .limit(page_size)
                        .offset((page - 1) * page_size)
                    )
                ).all()
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None

        return AdminPage(
            items=[
                self._proxy_summary(
                    row[0],
                    agents_total=row.agents_total,
                    onboarding_total=row.onboarding_total,
                )
                for row in rows
            ],
            total=total or 0,
            page=page,
            page_size=page_size,
        )

    async def list_proxy_options(self) -> list[AdminAgentProxy]:
        statement = (
            select(TelegramProxyModel)
            .where(TelegramProxyModel.is_active.is_(True))
            .order_by(
                TelegramProxyModel.label, TelegramProxyModel.created_at, TelegramProxyModel.id
            )
        )
        try:
            async with self._session_factory() as session:
                proxies = list(await session.scalars(statement))
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None
        return [self._agent_proxy(proxy) for proxy in proxies]

    async def read_proxy_config(self, proxy_id: UUID) -> TelegramProxyConfig:
        try:
            async with self._session_factory() as session:
                proxy = await session.get(TelegramProxyModel, proxy_id)
                if proxy is None:
                    raise AdminProxyNotFoundError
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None
        try:
            return telegram_proxy_config(proxy, self._cipher)
        except Exception as exc:
            raise AdminSecretStorageError(str(exc)) from None

    async def proxy_exists(
        self,
        *,
        protocol: Literal["socks5", "http"],
        host: str,
        port: int,
        username: str | None,
    ) -> bool:
        conditions = [
            TelegramProxyModel.protocol == protocol,
            TelegramProxyModel.host == host,
            TelegramProxyModel.port == port,
        ]
        if username is None:
            conditions.append(TelegramProxyModel.username.is_(None))
        else:
            conditions.append(TelegramProxyModel.username == username)
        try:
            async with self._session_factory() as session:
                return bool(await session.scalar(select(exists().where(*conditions))))
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None

    async def create_proxy(
        self,
        values: ProxyCreateValues,
        *,
        actor_user_id: UUID,
    ) -> AdminProxyDetail:
        password_ciphertext = self._encrypt_proxy_password(values.get("password"))
        if password_ciphertext is not None and not values.get("username"):
            raise AdminProxyValidationError("Для пароля укажите логин прокси")
        proxy = TelegramProxyModel(
            id=uuid4(),
            label=values["label"],
            protocol=values["protocol"],
            host=values["host"],
            port=values["port"],
            username=values.get("username"),
            password_ciphertext=password_ciphertext,
            is_active=values["is_active"],
            created_by=actor_user_id,
        )
        try:
            async with self._session_factory() as session, session.begin():
                session.add(proxy)
                await session.flush()
                await self._append_audit(
                    session,
                    actor_user_id=actor_user_id,
                    action="proxy.created",
                    object_type="proxy",
                    object_id=proxy.id,
                    metadata={
                        "fields": sorted(values),
                        "password_set": password_ciphertext is not None,
                    },
                )
                await session.refresh(proxy)
                result = self._proxy_detail(proxy, agents_total=0)
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None
        return result

    async def update_proxy(
        self,
        proxy_id: UUID,
        values: ProxyPatchValues,
        *,
        actor_user_id: UUID,
    ) -> AdminProxyDetail:
        try:
            async with self._session_factory() as session, session.begin():
                proxy = await session.scalar(
                    select(TelegramProxyModel)
                    .where(TelegramProxyModel.id == proxy_id)
                    .with_for_update()
                )
                if proxy is None:
                    raise AdminProxyNotFoundError

                changed_fields: list[str] = []
                for field in ("label", "protocol", "host", "port", "username", "is_active"):
                    if field not in values:
                        continue
                    value = values[field]
                    if getattr(proxy, field) != value:
                        setattr(proxy, field, value)
                        changed_fields.append(field)

                password = values.get("password")
                if password:
                    proxy.password_ciphertext = self._encrypt_proxy_password(password)
                    changed_fields.append("password")

                if proxy.password_ciphertext is not None and not proxy.username:
                    raise AdminProxyValidationError("Для пароля укажите логин прокси")

                if changed_fields:
                    proxy.updated_at = datetime.now(UTC)
                    await session.flush()
                    await self._append_audit(
                        session,
                        actor_user_id=actor_user_id,
                        action="proxy.updated",
                        object_type="proxy",
                        object_id=proxy_id,
                        metadata={"fields": changed_fields},
                    )
                    await session.refresh(proxy)

                agents_total = await session.scalar(
                    select(func.count())
                    .select_from(TelegramSessionModel)
                    .where(TelegramSessionModel.proxy_id == proxy_id)
                )
                onboarding_total = await session.scalar(
                    select(func.count())
                    .select_from(AgentOnboardingSessionModel)
                    .where(
                        AgentOnboardingSessionModel.proxy_id == proxy_id,
                        AgentOnboardingSessionModel.completed_agent_id.is_(None),
                    )
                )
                result = self._proxy_detail(
                    proxy,
                    agents_total=agents_total or 0,
                    onboarding_total=onboarding_total or 0,
                )
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None
        return result

    async def delete_proxy(self, proxy_id: UUID, *, actor_user_id: UUID) -> list[UUID]:
        try:
            async with self._session_factory() as session, session.begin():
                proxy = await session.scalar(
                    select(TelegramProxyModel)
                    .where(TelegramProxyModel.id == proxy_id)
                    .with_for_update()
                )
                if proxy is None:
                    raise AdminProxyNotFoundError

                agent_ids = list(
                    await session.scalars(
                        select(TelegramSessionModel.agent_id).where(
                            TelegramSessionModel.proxy_id == proxy_id
                        )
                    )
                )
                pending_onboarding = await session.scalar(
                    select(func.count())
                    .select_from(AgentOnboardingSessionModel)
                    .where(
                        AgentOnboardingSessionModel.proxy_id == proxy_id,
                        AgentOnboardingSessionModel.completed_agent_id.is_(None),
                    )
                )
                # Сначала уводим трафик на другой активный прокси, чтобы
                # удаление не оставило работающих мимиков без сети.
                replacement_id = await self._least_loaded_proxy_id(
                    session,
                    exclude_id=proxy_id,
                )
                if replacement_id is not None:
                    await session.execute(
                        update(TelegramSessionModel)
                        .where(TelegramSessionModel.proxy_id == proxy_id)
                        .values(proxy_id=replacement_id)
                    )
                    await session.execute(
                        update(AgentOnboardingSessionModel)
                        .where(
                            AgentOnboardingSessionModel.proxy_id == proxy_id,
                            AgentOnboardingSessionModel.completed_agent_id.is_(None),
                        )
                        .values(proxy_id=replacement_id)
                    )

                for agent_id in agent_ids:
                    await self._append_audit(
                        session,
                        actor_user_id=actor_user_id,
                        action="agent.proxy_changed",
                        object_type="agent",
                        object_id=agent_id,
                        metadata={
                            "before": str(proxy_id),
                            "after": (str(replacement_id) if replacement_id is not None else None),
                            "reason": "proxy_deleted",
                        },
                    )

                label = proxy.label
                await session.delete(proxy)
                await self._append_audit(
                    session,
                    actor_user_id=actor_user_id,
                    action="proxy.deleted",
                    object_type="proxy",
                    object_id=proxy_id,
                    metadata={
                        "label": label,
                        "affected_agents": len(agent_ids),
                        "pending_onboarding": pending_onboarding or 0,
                        "reassigned_to": (
                            str(replacement_id) if replacement_id is not None else None
                        ),
                    },
                )
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None
        return agent_ids

    async def _least_loaded_proxy_id(
        self,
        session: AsyncSession,
        *,
        exclude_id: UUID,
    ) -> UUID | None:
        agent_load = (
            select(func.count(TelegramSessionModel.id))
            .where(TelegramSessionModel.proxy_id == TelegramProxyModel.id)
            .correlate(TelegramProxyModel)
            .scalar_subquery()
        )
        onboarding_load = (
            select(func.count(AgentOnboardingSessionModel.id))
            .where(
                AgentOnboardingSessionModel.proxy_id == TelegramProxyModel.id,
                AgentOnboardingSessionModel.completed_agent_id.is_(None),
            )
            .correlate(TelegramProxyModel)
            .scalar_subquery()
        )
        return await session.scalar(
            select(TelegramProxyModel.id)
            .where(
                TelegramProxyModel.is_active.is_(True),
                TelegramProxyModel.id != exclude_id,
            )
            .order_by(
                agent_load + onboarding_load,
                TelegramProxyModel.created_at,
                TelegramProxyModel.id,
            )
            .limit(1)
        )

    async def assign_agent_proxy(
        self,
        agent_id: UUID,
        proxy_id: UUID | None,
        *,
        actor_user_id: UUID,
    ) -> AdminAgentProxy | None:
        try:
            async with self._session_factory() as session, session.begin():
                agent = await session.get(AgentModel, agent_id)
                if agent is None:
                    raise AdminAgentNotFoundError

                proxy: TelegramProxyModel | None = None
                if proxy_id is not None:
                    proxy = await session.get(TelegramProxyModel, proxy_id)
                    if proxy is None:
                        raise AdminProxyNotFoundError

                telegram_session = await session.scalar(
                    select(TelegramSessionModel)
                    .where(TelegramSessionModel.agent_id == agent_id)
                    .with_for_update()
                )
                if telegram_session is None:
                    raise AdminAgentNotFoundError

                previous_proxy_id = telegram_session.proxy_id
                if previous_proxy_id != proxy_id:
                    telegram_session.proxy_id = proxy_id
                    await session.flush()
                    await self._append_audit(
                        session,
                        actor_user_id=actor_user_id,
                        action="agent.proxy_changed",
                        object_type="agent",
                        object_id=agent_id,
                        metadata={
                            "before": (
                                str(previous_proxy_id) if previous_proxy_id is not None else None
                            ),
                            "after": str(proxy_id) if proxy_id is not None else None,
                        },
                    )

                result = self._agent_proxy(proxy) if proxy is not None else None
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None
        return result

    def _encrypt_proxy_password(self, password: str | None) -> str | None:
        if not password:
            return None
        if self._cipher is None:
            raise AdminSecretStorageError(
                "SECRET_KEY не настроен: пароль прокси нельзя сохранить зашифрованным"
            )
        return self._cipher.encrypt(password)

    @staticmethod
    def _agent_proxy(proxy: TelegramProxyModel) -> AdminAgentProxy:
        return AdminAgentProxy(
            id=proxy.id,
            label=proxy.label,
            protocol=cast(Literal["socks5", "http"], proxy.protocol),
            host=proxy.host,
            port=proxy.port,
            is_active=proxy.is_active,
        )

    @staticmethod
    def _proxy_summary(
        proxy: TelegramProxyModel,
        *,
        agents_total: int,
        onboarding_total: int = 0,
    ) -> AdminProxySummary:
        return AdminProxySummary(
            id=proxy.id,
            label=proxy.label,
            protocol=cast(Literal["socks5", "http"], proxy.protocol),
            host=proxy.host,
            port=proxy.port,
            username=proxy.username,
            has_password=proxy.password_ciphertext is not None,
            is_active=proxy.is_active,
            agents_total=agents_total,
            onboarding_total=onboarding_total,
            created_at=proxy.created_at,
            updated_at=proxy.updated_at,
        )

    @classmethod
    def _proxy_detail(
        cls,
        proxy: TelegramProxyModel,
        *,
        agents_total: int,
        onboarding_total: int = 0,
    ) -> AdminProxyDetail:
        return AdminProxyDetail(
            **cls._proxy_summary(
                proxy,
                agents_total=agents_total,
                onboarding_total=onboarding_total,
            ).model_dump(),
            created_by=proxy.created_by,
        )

    @staticmethod
    async def _append_audit(
        session: AsyncSession,
        *,
        actor_user_id: UUID,
        action: str,
        object_type: str,
        object_id: UUID | None,
        metadata: dict[str, Any],
    ) -> None:
        session.add(
            AdminAuditLogModel(
                actor_user_id=actor_user_id,
                action=action,
                object_type=object_type,
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
