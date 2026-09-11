"""Shared test doubles for API tests (single home for FakeAgentManager)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentRuntimeState,
    AgentStatus,
    AgentTrigger,
    AgentTriggerResult,
)


@dataclass
class FakeAgentRecord:
    config: AgentRuntimeConfig
    state: AgentRuntimeState


class FakeAgentManager:
    def __init__(self, default_owner_id: UUID | None = None) -> None:
        self._default_owner_id = default_owner_id
        self.created: dict[UUID, FakeAgentRecord] = {}
        self.started: list[UUID] = []
        self.stopped: list[UUID] = []
        self.removed: list[UUID] = []
        self.reloaded: list[UUID] = []
        self.triggers: list[tuple[UUID, str, str]] = []

    async def create_agent(
        self,
        config: AgentRuntimeConfig,
        *,
        start: bool = False,
    ) -> object:
        self.created[config.agent_id] = FakeAgentRecord(
            config=config,
            state=AgentRuntimeState.STOPPED,
        )
        if start:
            await self.start_agent(config.agent_id)
        return self

    async def start_agent(self, agent_id: UUID) -> None:
        self.started.append(agent_id)
        self.created[agent_id].state = AgentRuntimeState.RUNNING

    async def stop_agent(self, agent_id: UUID) -> None:
        self.stopped.append(agent_id)
        self.created[agent_id].state = AgentRuntimeState.STOPPED

    async def remove_agent(self, agent_id: UUID) -> None:
        self.removed.append(agent_id)

    async def reload_agent(self, agent_id: UUID) -> None:
        self.reloaded.append(agent_id)

    async def get_agent_status(self, agent_id: UUID) -> AgentStatus:
        item = self.created.get(agent_id)
        if item is None:
            # Tests that never create the agent (e.g. memory endpoints with
            # an InMemory store) still need an owner-consistent status.
            if self._default_owner_id is None:
                raise KeyError(agent_id)
            return AgentStatus(
                agent_id=agent_id,
                owner_id=self._default_owner_id,
                state=AgentRuntimeState.RUNNING,
            )
        return AgentStatus(
            agent_id=item.config.agent_id,
            owner_id=item.config.owner_id,
            state=item.state,
        )

    async def list_agents(self, *, owner_id: UUID | None = None) -> list[AgentStatus]:
        statuses = []
        for item in self.created.values():
            if owner_id is None or item.config.owner_id == owner_id:
                statuses.append(
                    AgentStatus(
                        agent_id=item.config.agent_id,
                        owner_id=item.config.owner_id,
                        state=item.state,
                    )
                )
        return statuses

    async def trigger_message(
        self,
        agent_id: UUID,
        trigger: AgentTrigger,
    ) -> AgentTriggerResult:
        self.triggers.append((agent_id, trigger.peer, trigger.text))
        return AgentTriggerResult(
            agent_id=agent_id,
            peer=trigger.peer,
            input_text=trigger.text,
            response_text="api response",
            telegram_message_id="42",
        )

    async def shutdown(self) -> None:
        return None
