from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete

from mimic42.core.agent_store import AgentRecord
from mimic42.core.onboarding import OnboardingSession
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.integrations.database_models import AgentOnboardingSessionModel
from mimic42.integrations.database_onboarding import DatabaseOnboardingRepository
from mimic42.integrations.database_proxies import lock_proxy_pool


async def seed_agent(store: DatabaseAgentStore, session: OnboardingSession) -> AgentRecord:
    """Create a synthetic saved agent without a wizard row for test fixtures."""
    repository = DatabaseOnboardingRepository(store._session_factory)
    await repository.create(session)
    try:
        return await store.create_from_onboarding(session)
    finally:
        async with store._session_factory() as db, db.begin():
            await lock_proxy_pool(db)
            await db.execute(
                delete(AgentOnboardingSessionModel).where(
                    AgentOnboardingSessionModel.id == session.onboarding_id
                )
            )


async def seed_rebind(
    store: DatabaseAgentStore, agent_id: UUID, session: OnboardingSession
) -> None:
    current = session.model_copy(update={"completed_agent_id": agent_id})
    repository = DatabaseOnboardingRepository(store._session_factory)
    await repository.create(current)
    try:
        await store.apply_rebind(current.authorization_ref(), agent_id)
    finally:
        async with store._session_factory() as db, db.begin():
            await lock_proxy_pool(db)
            await db.execute(
                delete(AgentOnboardingSessionModel).where(
                    AgentOnboardingSessionModel.id == current.onboarding_id
                )
            )
