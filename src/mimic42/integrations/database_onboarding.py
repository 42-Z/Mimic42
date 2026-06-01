from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.onboarding import (
    OnboardingNotFoundError,
    OnboardingSession,
    TelegramLoginStatus,
)
from mimic42.integrations.database_models import AgentOnboardingSessionModel


class DatabaseOnboardingRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, session: OnboardingSession) -> None:
        async with self._session_factory() as db_session:
            model = await db_session.get(AgentOnboardingSessionModel, session.onboarding_id)
            if model is None:
                model = AgentOnboardingSessionModel(id=session.onboarding_id)
                db_session.add(model)

            model.owner_id = session.owner_id
            model.api_id = session.api_id
            model.api_hash_ciphertext = session.api_hash_secret
            model.phone_number = session.phone_number
            model.phone_code_hash_ciphertext = session.phone_code_hash_secret
            model.session_ciphertext = session.session_secret
            model.authorization_status = session.authorization_status.value
            model.agent_name = session.name
            model.soul_prompt = session.soul_prompt
            await db_session.commit()

    async def get(self, onboarding_id: UUID) -> OnboardingSession:
        async with self._session_factory() as db_session:
            model = await db_session.scalar(
                select(AgentOnboardingSessionModel).where(
                    AgentOnboardingSessionModel.id == onboarding_id
                )
            )
            if model is None:
                raise OnboardingNotFoundError(onboarding_id)
            return _model_to_session(model)

    async def get_latest_by_owner(self, owner_id: UUID) -> OnboardingSession | None:
        async with self._session_factory() as db_session:
            model = await db_session.scalar(
                select(AgentOnboardingSessionModel)
                .where(AgentOnboardingSessionModel.owner_id == owner_id)
                .order_by(AgentOnboardingSessionModel.created_at.desc())
                .limit(1)
            )
            if model is None:
                return None
            return _model_to_session(model)


def _model_to_session(model: AgentOnboardingSessionModel) -> OnboardingSession:
    return OnboardingSession(
        onboarding_id=model.id,
        owner_id=model.owner_id,
        api_id=model.api_id,
        api_hash_secret=model.api_hash_ciphertext,
        phone_number=model.phone_number,
        authorization_status=TelegramLoginStatus(model.authorization_status),
        phone_code_hash_secret=model.phone_code_hash_ciphertext,
        session_secret=model.session_ciphertext,
        name=model.agent_name,
        soul_prompt=model.soul_prompt,
    )
