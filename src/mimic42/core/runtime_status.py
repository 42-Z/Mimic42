from __future__ import annotations

from mimic42.core.agent_runtime import AgentRuntimeState

PERSISTED_ACTIVE_STATES = frozenset(
    {
        AgentRuntimeState.STARTING,
        AgentRuntimeState.RUNNING,
        AgentRuntimeState.STOPPING,
    }
)


def effective_runtime_state(
    saved: AgentRuntimeState | str,
    actual: AgentRuntimeState | None,
) -> AgentRuntimeState:
    if actual is not None:
        return actual
    try:
        saved_state = AgentRuntimeState(saved)
    except ValueError:
        return AgentRuntimeState.STOPPED
    if saved_state in PERSISTED_ACTIVE_STATES:
        return AgentRuntimeState.STOPPED
    return saved_state
