from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import AgentRuntimeConfig, AgentRuntimeState
from mimic42.core.agent_store import AgentActivity, AgentMessageRecord, AgentRecord
from mimic42.core.onboarding import OnboardingSession, SecretCipher
from mimic42.integrations.database_models import (
    AgentEventModel,
    AgentMessageModel,
    AgentModel,
    TelegramSessionModel,
)


class DatabaseAgentStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        cipher: SecretCipher | None = None,
        llm_model: str = "mistralai/mistral-small-2603",
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher
        self._llm_model = llm_model

    async def create_from_onboarding(self, session: OnboardingSession) -> AgentRecord:
        if not session.name or not session.soul_prompt:
            raise ValueError("Onboarding session is missing agent profile fields")

        async with self._session_factory() as db_session:
            agent = await db_session.get(AgentModel, session.onboarding_id)
            if agent is None:
                agent = AgentModel(id=session.onboarding_id)
                db_session.add(agent)

            agent.owner_id = session.owner_id
            agent.name = session.name
            agent.status = AgentRuntimeState.STOPPED.value
            agent.soul_prompt = session.soul_prompt

            telegram_session = await db_session.scalar(
                select(TelegramSessionModel).where(
                    TelegramSessionModel.agent_id == session.onboarding_id
                )
            )
            if telegram_session is None:
                telegram_session = TelegramSessionModel(agent_id=session.onboarding_id)
                db_session.add(telegram_session)

            telegram_session.session_name = session.onboarding_id.hex
            telegram_session.phone_number = session.phone_number
            telegram_session.api_id = session.api_id
            telegram_session.api_hash_ciphertext = session.api_hash_secret
            telegram_session.session_ciphertext = session.session_secret
            telegram_session.authorization_status = "authorized"
            telegram_session.last_authorized_at = _now()

            await db_session.commit()
            return _agent_record(agent)

    async def get_runtime_config(self, agent_id: UUID) -> AgentRuntimeConfig:
        async with self._session_factory() as db_session:
            row = await db_session.execute(
                select(AgentModel, TelegramSessionModel)
                .join(TelegramSessionModel, TelegramSessionModel.agent_id == AgentModel.id)
                .where(AgentModel.id == agent_id)
            )
            item = row.first()
            if item is None:
                raise KeyError(f"Agent {agent_id} does not have a runtime config")
            agent, telegram_session = item
            from mimic42.core.onboarding import load_default_system_prompt

            return AgentRuntimeConfig(
                agent_id=agent.id,
                owner_id=agent.owner_id,
                telegram_session_name=telegram_session.session_name,
                telegram_api_id=telegram_session.api_id or 0,
                telegram_api_hash=(
                    self._cipher.decrypt(telegram_session.api_hash_ciphertext)
                    if self._cipher and telegram_session.api_hash_ciphertext
                    else telegram_session.api_hash_ciphertext or ""
                ),
                telegram_session_string=(
                    self._cipher.decrypt(telegram_session.session_ciphertext)
                    if self._cipher and telegram_session.session_ciphertext
                    else telegram_session.session_ciphertext
                ),
                llm_model=(
                    agent.settings.get("model", self._llm_model)
                    if agent.settings
                    else self._llm_model
                ),
                reasoning_effort=agent.settings.get("reasoning_effort", "high")
                if agent.settings
                else "high",
                system_prompt=load_default_system_prompt(),
                soul_prompt=agent.soul_prompt,
                name=agent.name,
            )

    async def list_agents(self, *, owner_id: UUID | None = None) -> list[AgentRecord]:
        statement = select(AgentModel).order_by(AgentModel.created_at.desc())
        if owner_id is not None:
            statement = statement.where(AgentModel.owner_id == owner_id)
        async with self._session_factory() as db_session:
            return [_agent_record(agent) for agent in await db_session.scalars(statement)]

    async def update_status(self, agent_id: UUID, state: AgentRuntimeState) -> None:
        async with self._session_factory() as db_session:
            agent = await db_session.get(AgentModel, agent_id)
            if agent is None:
                return
            agent.status = state.value
            if state is AgentRuntimeState.RUNNING:
                agent.last_started_at = _now()
            if state is AgentRuntimeState.STOPPED:
                agent.last_stopped_at = _now()
            await db_session.commit()

    async def list_messages(self, *, agent_id: UUID, limit: int = 50) -> list[AgentMessageRecord]:
        async with self._session_factory() as db_session:
            messages = await db_session.scalars(
                select(AgentMessageModel)
                .where(AgentMessageModel.agent_id == agent_id)
                .order_by(AgentMessageModel.created_at.desc())
                .limit(limit)
            )
            records = []
            for message in messages:
                content = message.content
                # With structured output the assistant message content is empty.
                # Present the human-readable text from the stored schema instead.
                if not content and message.role == "assistant":
                    structured = message.payload.get("structured_response")
                    if isinstance(structured, dict):
                        content = structured.get("text", "")
                records.append(
                    AgentMessageRecord(
                        id=message.id,
                        agent_id=message.agent_id,
                        peer=str(message.payload.get("peer", "")),
                        role=message.role,
                        content=content,
                        direction=message.direction,
                        created_at=message.created_at,
                    )
                )
            return records

    async def list_activities(self, *, agent_id: UUID, limit: int = 50) -> list[AgentActivity]:
        async with self._session_factory() as db_session:
            activities = await db_session.scalars(
                select(AgentEventModel)
                .where(AgentEventModel.agent_id == agent_id)
                .order_by(AgentEventModel.created_at.desc())
                .limit(limit)
            )
            return [
                AgentActivity(
                    id=activity.id,
                    agent_id=activity.agent_id,
                    event_type=activity.event_type,
                    status=activity.status,
                    created_at=activity.created_at,
                    error=activity.error,
                )
                for activity in activities
            ]


def _agent_record(agent: AgentModel) -> AgentRecord:
    return AgentRecord(
        agent_id=agent.id,
        owner_id=agent.owner_id,
        name=agent.name,
        state=AgentRuntimeState(agent.status),
    )


def _now() -> datetime:
    return datetime.now(UTC)
