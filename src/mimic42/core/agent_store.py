from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from mimic42.core.agent_runtime import AgentRuntimeConfig, AgentRuntimeState

if TYPE_CHECKING:
    from mimic42.core.onboarding import OnboardingSession


class AgentRecord(BaseModel):
    agent_id: UUID
    owner_id: UUID
    name: str
    state: AgentRuntimeState


class AgentMessageRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    peer: str
    role: str
    content: str
    direction: str = "inbound"
    created_at: datetime


class AgentActivity(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    event_type: str
    status: str
    created_at: datetime
    error: str | None = None


class AgentStore(Protocol):
    async def create_from_onboarding(self, session: OnboardingSession) -> AgentRecord: ...

    async def get_runtime_config(self, agent_id: UUID) -> AgentRuntimeConfig: ...

    async def list_agents(self, *, owner_id: UUID | None = None) -> list[AgentRecord]: ...

    async def update_status(self, agent_id: UUID, state: AgentRuntimeState) -> None: ...

    async def list_messages(
        self,
        *,
        agent_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentMessageRecord]: ...

    async def list_activities(self, *, agent_id: UUID, limit: int = 50, offset: int = 0) -> list[AgentActivity]: ...


class InMemoryAgentStore:
    def __init__(
        self,
        *,
        agents: list[AgentRecord] | None = None,
        messages: list[AgentMessageRecord] | None = None,
        activities: list[AgentActivity] | None = None,
    ) -> None:
        self._agents = {agent.agent_id: agent for agent in agents or []}
        self._configs: dict[UUID, AgentRuntimeConfig] = {}
        self._messages = messages or []
        self._activities = activities or []

    async def create_from_onboarding(self, session: OnboardingSession) -> AgentRecord:
        if (
            not session.name
            or not session.soul_prompt
            or session.api_id is None
            or session.api_hash_secret is None
        ):
            raise ValueError(
                "Onboarding session is missing agent profile fields or Telegram credentials"
            )
        record = AgentRecord(
            agent_id=session.onboarding_id,
            owner_id=session.owner_id,
            name=session.name,
            state=AgentRuntimeState.STOPPED,
        )
        self._agents[record.agent_id] = record
        from mimic42.core.onboarding import load_default_system_prompt

        self._configs[record.agent_id] = AgentRuntimeConfig(
            agent_id=session.onboarding_id,
            owner_id=session.owner_id,
            telegram_session_name=session.onboarding_id.hex,
            telegram_api_id=session.api_id,
            telegram_api_hash=session.api_hash_secret,
            telegram_session_string=session.session_secret,
            system_prompt=load_default_system_prompt(),
            soul_prompt=session.soul_prompt,
            name=session.name or "AI",
        )
        return record

    async def get_runtime_config(self, agent_id: UUID) -> AgentRuntimeConfig:
        try:
            return self._configs[agent_id]
        except KeyError as exc:
            raise KeyError(f"Agent {agent_id} does not have a runtime config") from exc

    async def list_agents(self, *, owner_id: UUID | None = None) -> list[AgentRecord]:
        records = list(self._agents.values())
        if owner_id is not None:
            records = [record for record in records if record.owner_id == owner_id]
        return records

    async def update_status(self, agent_id: UUID, state: AgentRuntimeState) -> None:
        if agent_id in self._agents:
            self._agents[agent_id] = self._agents[agent_id].model_copy(update={"state": state})

    async def list_messages(self, *, agent_id: UUID, limit: int = 50, offset: int = 0) -> list[AgentMessageRecord]:
        filtered = [message for message in self._messages if message.agent_id == agent_id]
        # In-memory store keeps ascending order; return from the end for DESC semantics
        start = max(0, len(filtered) - offset - limit)
        end = max(0, len(filtered) - offset)
        return filtered[start:end]

    async def list_activities(self, *, agent_id: UUID, limit: int = 50, offset: int = 0) -> list[AgentActivity]:
        filtered = [activity for activity in self._activities if activity.agent_id == agent_id]
        start = max(0, len(filtered) - offset - limit)
        end = max(0, len(filtered) - offset)
        return filtered[start:end]
