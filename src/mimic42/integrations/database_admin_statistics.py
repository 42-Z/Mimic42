from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Text, bindparam, case, cast, func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.sql.selectable import CTE

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.runtime_status import PERSISTED_ACTIVE_STATES
from mimic42.integrations.database_models import AgentModel

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
