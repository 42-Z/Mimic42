from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from mimic42.core.admin import statistics_window
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.integrations.database_admin import DatabaseAdminRepository
from mimic42.integrations.database_models import (
    AgentEventModel,
    AgentMessageModel,
    AgentModel,
    AgentTokenUsageModel,
)
from mimic42.testing.slots import Slot


@pytest.mark.asyncio
async def test_statistics_uses_independent_aggregates_and_one_consistent_snapshot(
    admin_db_factory: async_sessionmaker[Any],
    test_slot: Slot,
) -> None:
    repository = DatabaseAdminRepository(admin_db_factory)
    now = datetime.now(UTC)
    since, _ = statistics_window(7, now)
    activity_at = since + timedelta(days=3, hours=12)
    first_agent_id = uuid4()
    second_agent_id = uuid4()
    first_owner = test_slot.persona("empty").user_id
    second_owner = test_slot.persona("full").user_id
    runtime_states: dict[UUID, AgentRuntimeState] = {}

    baseline_7 = await repository.statistics(days=7, now=now, runtime_states=runtime_states)
    baseline_30 = await repository.statistics(days=30, now=now, runtime_states=runtime_states)

    async with admin_db_factory() as session, session.begin():
        session.add_all(
            [
                AgentModel(
                    id=first_agent_id,
                    owner_id=first_owner,
                    name="Statistics first",
                    soul_prompt="private prompt",
                    status="running",
                    settings={"model": "openrouter/statistics-test"},
                ),
                AgentModel(
                    id=second_agent_id,
                    owner_id=second_owner,
                    name="Statistics second",
                    soul_prompt="private prompt",
                    status="stopped",
                    settings={},
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                AgentMessageModel(
                    agent_id=first_agent_id,
                    direction="incoming",
                    role="user",
                    content="first incoming",
                    created_at=activity_at,
                ),
                AgentMessageModel(
                    agent_id=first_agent_id,
                    direction="incoming",
                    role="user",
                    content="second incoming",
                    created_at=activity_at,
                ),
                AgentMessageModel(
                    agent_id=first_agent_id,
                    direction="agent_response",
                    role="assistant",
                    content="reply",
                    created_at=activity_at,
                ),
                AgentMessageModel(
                    agent_id=first_agent_id,
                    direction="tool_call",
                    role="assistant",
                    content="tool call is not a message",
                    created_at=activity_at,
                ),
                AgentMessageModel(
                    agent_id=first_agent_id,
                    direction="incoming",
                    role="user",
                    content="future message excluded",
                    created_at=now + timedelta(days=1),
                ),
                AgentEventModel(
                    agent_id=first_agent_id,
                    event_type="tool.send_text_message",
                    status="succeeded",
                    payload={},
                    created_at=activity_at,
                ),
                AgentEventModel(
                    agent_id=second_agent_id,
                    event_type="tool.send_text_message",
                    status="failed",
                    payload={},
                    created_at=activity_at + timedelta(days=1),
                ),
                AgentEventModel(
                    agent_id=second_agent_id,
                    event_type="model.failed",
                    status="failed",
                    payload={},
                    created_at=activity_at + timedelta(days=2),
                ),
                AgentTokenUsageModel(
                    agent_id=first_agent_id,
                    input_tokens=100,
                    output_tokens=30,
                ),
            ]
        )

    current_7 = await repository.statistics(days=7, now=now, runtime_states=runtime_states)
    current_30 = await repository.statistics(days=30, now=now, runtime_states=runtime_states)

    assert current_7.users == baseline_7.users
    assert current_7.agents == baseline_7.agents + 2
    expected_states = dict(baseline_7.states)
    expected_states[AgentRuntimeState.STOPPED] = (
        expected_states.get(AgentRuntimeState.STOPPED, 0) + 2
    )
    assert current_7.states == expected_states
    assert current_7.totals.messages - baseline_7.totals.messages == 3
    assert current_7.totals.actions - baseline_7.totals.actions == 2
    assert current_7.totals.errors - baseline_7.totals.errors == 2
    assert current_7.input_tokens - baseline_7.input_tokens == 100
    assert current_7.output_tokens - baseline_7.output_tokens == 30
    assert len(current_7.daily) == 7
    assert sum(day.messages for day in current_7.daily) == current_7.totals.messages
    assert sum(day.actions for day in current_7.daily) == current_7.totals.actions
    assert sum(day.errors for day in current_7.daily) == current_7.totals.errors
    baseline_by_date = {day.date: day for day in baseline_7.daily}
    daily_by_date = {day.date: day for day in current_7.daily}
    assert (
        daily_by_date[activity_at.date()].messages - baseline_by_date[activity_at.date()].messages
        == 3
    )
    assert (
        daily_by_date[activity_at.date()].actions - baseline_by_date[activity_at.date()].actions
        == 1
    )
    next_day = (activity_at + timedelta(days=1)).date()
    assert daily_by_date[next_day].messages - baseline_by_date[next_day].messages == 0
    assert daily_by_date[next_day].actions - baseline_by_date[next_day].actions == 1
    assert daily_by_date[next_day].errors - baseline_by_date[next_day].errors == 1
    final_day = (activity_at + timedelta(days=2)).date()
    assert daily_by_date[final_day].actions - baseline_by_date[final_day].actions == 0
    assert daily_by_date[final_day].errors - baseline_by_date[final_day].errors == 1
    assert current_30.input_tokens - baseline_30.input_tokens == 100
    assert current_30.output_tokens - baseline_30.output_tokens == 30
    assert current_30.totals.messages - baseline_30.totals.messages == 3
    assert current_30.totals.actions - baseline_30.totals.actions == 2
    assert current_30.totals.errors - baseline_30.totals.errors == 2

    async with admin_db_factory() as session, session.begin():
        await session.execute(delete(AgentModel).where(AgentModel.id == first_agent_id))

    after_delete = await repository.statistics(days=7, now=now, runtime_states=runtime_states)

    assert after_delete.agents == current_7.agents - 1
    assert after_delete.states[AgentRuntimeState.STOPPED] == (
        current_7.states[AgentRuntimeState.STOPPED] - 1
    )
    assert after_delete.totals.messages == current_7.totals.messages - 3
    assert after_delete.totals.actions == current_7.totals.actions - 1
    assert after_delete.totals.errors == current_7.totals.errors
    assert after_delete.input_tokens == current_7.input_tokens - 100
    assert after_delete.output_tokens == current_7.output_tokens - 30
