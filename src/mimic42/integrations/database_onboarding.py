from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import case, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.onboarding import (
    OnboardingAlreadyCompletedError,
    OnboardingNotFoundError,
    OnboardingOwnershipError,
    OnboardingSession,
    SecretCipher,
    TelegramAuthorizationRef,
    TelegramCredentials,
    TelegramLoginAttempt,
    TelegramLoginRouteChangedError,
    TelegramLoginStaleError,
    TelegramLoginStatus,
    TelegramRebindUnavailableError,
    _validate_verification,
)
from mimic42.core.telegram_proxy import TelegramProxyAssignment, TelegramProxyUnavailableError
from mimic42.integrations.database_models import (
    AgentModel,
    AgentOnboardingSessionModel,
    TelegramProxyModel,
    TelegramSessionModel,
)
from mimic42.integrations.database_proxies import (
    least_loaded_proxy_id,
    lock_proxy_pool,
    telegram_proxy_config,
)


class DatabaseOnboardingRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        cipher: SecretCipher | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher

    async def create(self, session: OnboardingSession) -> None:
        """Insert an explicit initial row. Auth results must use record_auth instead."""
        async with self._session_factory() as db, db.begin():
            await lock_proxy_pool(db)
            db.add(
                AgentOnboardingSessionModel(
                    id=session.onboarding_id,
                    owner_id=session.owner_id,
                    api_id=session.api_id,
                    api_hash_ciphertext=session.api_hash_secret,
                    phone_number=session.phone_number,
                    username=session.username,
                    phone_code_hash_ciphertext=session.phone_code_hash_secret,
                    session_ciphertext=session.session_secret,
                    authorization_status=session.authorization_status.value,
                    agent_name=session.name,
                    soul_prompt=session.soul_prompt,
                    settings=session.settings,
                    completed_agent_id=session.completed_agent_id,
                    proxy_id=session.proxy_id,
                    auth_generation=session.auth_generation,
                    applied_auth_generation=session.applied_auth_generation,
                )
            )

    async def begin_login(
        self,
        credentials: TelegramCredentials,
        *,
        api_hash_secret: str,
        onboarding_id: UUID | None = None,
    ) -> OnboardingSession:
        async with self._session_factory() as db, db.begin():
            await lock_proxy_pool(db)
            if onboarding_id is None:
                model = AgentOnboardingSessionModel(
                    id=uuid4(), owner_id=credentials.owner_id, authorization_status="not_started"
                )
                db.add(model)
                await db.flush()
            else:
                model = await db.scalar(
                    select(AgentOnboardingSessionModel)
                    .where(AgentOnboardingSessionModel.id == onboarding_id)
                    .with_for_update()
                )
                if model is None:
                    raise OnboardingNotFoundError(onboarding_id)
                if model.owner_id != credentials.owner_id:
                    raise OnboardingOwnershipError(onboarding_id)
                if model.completed_agent_id is not None:
                    raise OnboardingAlreadyCompletedError(onboarding_id)
            proxy_id = model.proxy_id
            if proxy_id is None:
                proxy_id = await least_loaded_proxy_id(db)
            saved = await db.scalar(
                update(AgentOnboardingSessionModel)
                .where(AgentOnboardingSessionModel.id == model.id)
                .values(
                    api_id=credentials.api_id,
                    api_hash_ciphertext=api_hash_secret,
                    phone_number=credentials.phone_number,
                    proxy_id=proxy_id,
                    authorization_status="not_started",
                )
                .returning(AgentOnboardingSessionModel)
                .execution_options(populate_existing=True)
            )
            assert saved is not None
            return _model_to_session(saved)

    async def begin_rebind(self, agent_id: UUID, *, owner_id: UUID) -> OnboardingSession:
        async with self._session_factory() as db, db.begin():
            await lock_proxy_pool(db)
            agent = await db.scalar(
                select(AgentModel).where(AgentModel.id == agent_id).with_for_update()
            )
            if agent is None:
                raise TelegramRebindUnavailableError("Нет сохранённых реквизитов Telegram")
            if agent.owner_id != owner_id:
                raise OnboardingOwnershipError(agent_id)
            telegram = await db.scalar(
                select(TelegramSessionModel)
                .where(TelegramSessionModel.agent_id == agent_id)
                .with_for_update()
            )
            if (
                telegram is None
                or telegram.api_id is None
                or telegram.api_hash_ciphertext is None
                or telegram.phone_number is None
            ):
                raise TelegramRebindUnavailableError("Нет сохранённых реквизитов Telegram")
            model = await db.scalar(
                select(AgentOnboardingSessionModel)
                .where(
                    or_(
                        AgentOnboardingSessionModel.id == agent_id,
                        AgentOnboardingSessionModel.completed_agent_id == agent_id,
                    )
                )
                .order_by(AgentOnboardingSessionModel.completed_agent_id.is_(None))
                .limit(1)
                .with_for_update()
            )
            if model is None:
                model = AgentOnboardingSessionModel(
                    id=agent_id,
                    owner_id=owner_id,
                    completed_agent_id=agent_id,
                    authorization_status="not_started",
                )
                db.add(model)
                await db.flush()
            if model.owner_id != owner_id or model.completed_agent_id not in (None, agent_id):
                raise OnboardingOwnershipError(model.id)
            saved = await db.scalar(
                update(AgentOnboardingSessionModel)
                .where(AgentOnboardingSessionModel.id == model.id)
                .values(
                    api_id=telegram.api_id,
                    api_hash_ciphertext=telegram.api_hash_ciphertext,
                    phone_number=telegram.phone_number,
                    completed_agent_id=agent_id,
                    proxy_id=None,
                    authorization_status="not_started",
                )
                .returning(AgentOnboardingSessionModel)
                .execution_options(populate_existing=True)
            )
            assert saved is not None
            return _model_to_session(saved)

    async def claim_verification(
        self,
        onboarding_id: UUID,
        *,
        password: bool,
        owner_id: UUID | None = None,
    ) -> OnboardingSession:
        async with self._session_factory() as db, db.begin():
            await lock_proxy_pool(db)
            model = await db.scalar(
                select(AgentOnboardingSessionModel)
                .where(AgentOnboardingSessionModel.id == onboarding_id)
                .with_for_update()
            )
            if model is None:
                raise OnboardingNotFoundError(onboarding_id)
            _validate_verification(_model_to_session(model), password=password, owner_id=owner_id)
            saved = await db.scalar(
                update(AgentOnboardingSessionModel)
                .where(AgentOnboardingSessionModel.id == onboarding_id)
                .values(auth_generation=uuid4())
                .returning(AgentOnboardingSessionModel)
                .execution_options(populate_existing=True)
            )
            assert saved is not None
            return _model_to_session(saved)

    async def load_attempt(self, ref: TelegramAuthorizationRef) -> TelegramLoginAttempt:
        route_id = case(
            (
                AgentOnboardingSessionModel.completed_agent_id.is_not(None),
                TelegramSessionModel.proxy_id,
            ),
            else_=AgentOnboardingSessionModel.proxy_id,
        )
        try:
            async with self._session_factory() as db:
                row = (
                    await db.execute(
                        select(
                            AgentOnboardingSessionModel,
                            TelegramSessionModel.id,
                            route_id,
                            TelegramProxyModel,
                        )
                        .outerjoin(
                            TelegramSessionModel,
                            TelegramSessionModel.agent_id
                            == AgentOnboardingSessionModel.completed_agent_id,
                        )
                        .outerjoin(TelegramProxyModel, TelegramProxyModel.id == route_id)
                        .where(AgentOnboardingSessionModel.id == ref.onboarding_id)
                    )
                ).first()
                if row is None:
                    raise TelegramLoginStaleError()
                model, telegram_id, proxy_id, proxy = row
                current = _model_to_session(model)
                ref.check(current)
                if current.completed_agent_id is not None and telegram_id is None:
                    raise TelegramLoginStaleError()
                assignment = None
                if proxy_id is not None:
                    if proxy is None:
                        raise TelegramProxyUnavailableError("Назначенный прокси не найден")
                    assignment = TelegramProxyAssignment(
                        proxy_id=proxy_id, config=telegram_proxy_config(proxy, self._cipher)
                    )
                return TelegramLoginAttempt(session=current, assignment=assignment)
        except SQLAlchemyError:
            raise TelegramProxyUnavailableError(
                "Хранилище маршрута Telegram временно недоступно"
            ) from None

    async def check_attempt(self, attempt: TelegramLoginAttempt) -> None:
        ref = attempt.session.authorization_ref()
        async with self._session_factory() as db:
            row = (
                await db.execute(
                    select(AgentOnboardingSessionModel, TelegramSessionModel)
                    .outerjoin(
                        TelegramSessionModel,
                        TelegramSessionModel.agent_id
                        == AgentOnboardingSessionModel.completed_agent_id,
                    )
                    .where(AgentOnboardingSessionModel.id == ref.onboarding_id)
                )
            ).first()
            if row is None:
                raise TelegramLoginStaleError()
            model, telegram = row
            ref.check(_model_to_session(model))
            if model.completed_agent_id is not None:
                if telegram is None:
                    raise TelegramLoginStaleError()
                proxy_id = telegram.proxy_id
            else:
                proxy_id = model.proxy_id
            if proxy_id != attempt.proxy_id:
                raise TelegramLoginRouteChangedError()

    async def record_auth(
        self,
        ref: TelegramAuthorizationRef,
        *,
        status: TelegramLoginStatus,
        session_secret: str,
        phone_code_hash_secret: str | None = None,
    ) -> OnboardingSession:
        values = {"authorization_status": status.value, "session_ciphertext": session_secret}
        if phone_code_hash_secret is not None:
            values["phone_code_hash_ciphertext"] = phone_code_hash_secret
        async with self._session_factory() as db, db.begin():
            await lock_proxy_pool(db)
            model = await db.scalar(
                update(AgentOnboardingSessionModel)
                .where(*_ref_conditions(ref))
                .values(**values)
                .returning(AgentOnboardingSessionModel)
            )
            if model is None:
                raise TelegramLoginStaleError()
            return _model_to_session(model)

    async def record_username(self, ref: TelegramAuthorizationRef, username: str | None) -> None:
        async with self._session_factory() as db, db.begin():
            await lock_proxy_pool(db)
            matched = await db.scalar(
                update(AgentOnboardingSessionModel)
                .where(*_ref_conditions(ref))
                .values(username=username)
                .returning(AgentOnboardingSessionModel.id)
            )
            if matched is None:
                raise TelegramLoginStaleError()

    async def get(self, onboarding_id: UUID) -> OnboardingSession:
        async with self._session_factory() as db:
            model = await db.get(AgentOnboardingSessionModel, onboarding_id)
            if model is None:
                raise OnboardingNotFoundError(onboarding_id)
            return _model_to_session(model)

    async def get_for_agent(self, agent_id: UUID) -> OnboardingSession:
        async with self._session_factory() as db:
            model = await db.scalar(
                select(AgentOnboardingSessionModel)
                .where(
                    or_(
                        AgentOnboardingSessionModel.id == agent_id,
                        AgentOnboardingSessionModel.completed_agent_id == agent_id,
                    )
                )
                .order_by(AgentOnboardingSessionModel.completed_agent_id.is_(None))
                .limit(1)
            )
            if model is None:
                raise OnboardingNotFoundError(agent_id)
            return _model_to_session(model)


def _ref_conditions(ref: TelegramAuthorizationRef) -> tuple:
    return (
        AgentOnboardingSessionModel.id == ref.onboarding_id,
        AgentOnboardingSessionModel.owner_id == ref.owner_id,
        AgentOnboardingSessionModel.auth_generation == ref.generation,
        AgentOnboardingSessionModel.completed_agent_id.is_not_distinct_from(ref.completed_agent_id),
    )


def _model_to_session(model: AgentOnboardingSessionModel) -> OnboardingSession:
    return OnboardingSession(
        onboarding_id=model.id,
        owner_id=model.owner_id,
        api_id=model.api_id,
        api_hash_secret=model.api_hash_ciphertext,
        phone_number=model.phone_number,
        username=model.username,
        authorization_status=TelegramLoginStatus(model.authorization_status),
        phone_code_hash_secret=model.phone_code_hash_ciphertext,
        session_secret=model.session_ciphertext,
        name=model.agent_name,
        soul_prompt=model.soul_prompt,
        settings=model.settings or {},
        completed_agent_id=model.completed_agent_id,
        proxy_id=model.proxy_id,
        auth_generation=model.auth_generation,
        applied_auth_generation=model.applied_auth_generation,
    )
