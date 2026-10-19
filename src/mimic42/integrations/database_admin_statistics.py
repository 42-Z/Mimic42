from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Date,
    Text,
    bindparam,
    case,
    cast,
    func,
    literal,
    literal_column,
    or_,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.sql.selectable import CTE, Select

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.runtime_status import PERSISTED_ACTIVE_STATES
from mimic42.integrations.database_models import (
    AgentEventModel,
    AgentMessageModel,
    AgentModel,
    AgentTokenUsageModel,
    ProfileModel,
)

STALE_DATABASE_STATES = sorted({"draft", *(state.value for state in PERSISTED_ACTIVE_STATES)})


def effective_agents_cte() -> CTE:
    runtime_rows = (
        func.unnest(
            bindparam("runtime_ids", type_=ARRAY(PostgreSQLUUID(as_uuid=True))),
            bindparam("runtime_states", type_=ARRAY(Text())),
        )
        .table_valued("agent_id", "state")
        .render_derived(name="runtime_rows")
    )
    runtime = select(runtime_rows.c.agent_id, runtime_rows.c.state).cte("runtime")
    saved_state = case(
        (
            AgentModel.status.in_(STALE_DATABASE_STATES),
            AgentRuntimeState.STOPPED.value,
        ),
        else_=cast(AgentModel.status, Text()),
    )

    return (
        select(
            AgentModel.id.label("agent_id"),
            AgentModel.owner_id,
            AgentModel.name,
            AgentModel.settings,
            AgentModel.created_at,
            func.coalesce(runtime.c.state, saved_state).label("state"),
        )
        .outerjoin(runtime, runtime.c.agent_id == AgentModel.id)
        .cte("effective_agents")
    )


def runtime_state_parameters(
    runtime_states: dict[UUID, AgentRuntimeState],
) -> dict[str, Any]:
    pairs = list(runtime_states.items())
    return {
        "runtime_ids": [agent_id for agent_id, _ in pairs],
        "runtime_states": [state.value for _, state in pairs],
    }


def statistics_statement(since: datetime, until: datetime) -> Select[Any]:
    effective_agents = effective_agents_cte()
    users = select(func.count().label("users")).select_from(ProfileModel).cte("user_totals")
    agents = select(func.count().label("agents")).select_from(effective_agents).cte("agent_totals")
    state_counts = (
        select(
            effective_agents.c.state,
            func.count().label("agents_count"),
        )
        .group_by(effective_agents.c.state)
        .cte("agent_state_counts")
    )
    states = select(
        cast(
            func.coalesce(
                func.jsonb_object_agg(state_counts.c.state, state_counts.c.agents_count),
                literal({}, type_=JSONB),
            ),
            JSONB,
        ).label("states")
    ).cte("state_totals")
    token_totals = (
        select(
            func.coalesce(func.sum(AgentTokenUsageModel.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(AgentTokenUsageModel.output_tokens), 0).label("output_tokens"),
        )
        .select_from(AgentTokenUsageModel)
        .cte("token_totals")
    )

    message_date = cast(func.timezone("UTC", AgentMessageModel.created_at), Date).label("date")
    daily_messages = (
        select(
            message_date,
            func.count().label("messages"),
        )
        .where(
            AgentMessageModel.created_at >= since,
            AgentMessageModel.created_at < until,
            AgentMessageModel.direction.in_(
                (literal_column("'incoming'"), literal_column("'agent_response'"))
            ),
        )
        .group_by(message_date)
        .cte("daily_messages")
    )
    event_date = cast(func.timezone("UTC", AgentEventModel.created_at), Date).label("date")
    daily_events = (
        select(
            event_date,
            func.count()
            .filter(AgentEventModel.event_type.like(literal_column("'tool.%'")))
            .label("actions"),
            func.count()
            .filter(AgentEventModel.status == literal_column("'failed'"))
            .label("errors"),
        )
        .where(
            AgentEventModel.created_at >= since,
            AgentEventModel.created_at < until,
            or_(
                AgentEventModel.event_type.like(literal_column("'tool.%'")),
                AgentEventModel.status == literal_column("'failed'"),
            ),
        )
        .group_by(event_date)
        .cte("daily_events")
    )
    daily_activity = (
        select(
            func.coalesce(daily_messages.c.date, daily_events.c.date).label("date"),
            func.coalesce(daily_messages.c.messages, 0).label("messages"),
            func.coalesce(daily_events.c.actions, 0).label("actions"),
            func.coalesce(daily_events.c.errors, 0).label("errors"),
        )
        .select_from(
            daily_messages.join(
                daily_events,
                daily_messages.c.date == daily_events.c.date,
                full=True,
            )
        )
        .cte("daily_activity")
    )
    summary = (
        select(
            users.c.users,
            agents.c.agents,
            states.c.states,
            token_totals.c.input_tokens,
            token_totals.c.output_tokens,
        )
        .select_from(users.join(agents, true()).join(states, true()).join(token_totals, true()))
        .cte("summary")
    )

    return (
        select(
            summary.c.users,
            summary.c.agents,
            summary.c.states,
            summary.c.input_tokens,
            summary.c.output_tokens,
            daily_activity.c.date,
            daily_activity.c.messages,
            daily_activity.c.actions,
            daily_activity.c.errors,
        )
        .select_from(summary.outerjoin(daily_activity, true()))
        .order_by(daily_activity.c.date)
    )
