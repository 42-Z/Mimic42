from __future__ import annotations

import pytest

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.runtime_status import effective_runtime_state


@pytest.mark.parametrize(
    "saved",
    [
        AgentRuntimeState.STARTING,
        AgentRuntimeState.RUNNING,
        AgentRuntimeState.STOPPING,
    ],
)
def test_stale_active_database_state_becomes_stopped(saved: AgentRuntimeState) -> None:
    assert effective_runtime_state(saved, actual=None) is AgentRuntimeState.STOPPED


@pytest.mark.parametrize(
    ("saved", "expected"),
    [
        (AgentRuntimeState.ERROR, AgentRuntimeState.ERROR),
        (AgentRuntimeState.STOPPED, AgentRuntimeState.STOPPED),
        ("draft", AgentRuntimeState.STOPPED),
        ("unexpected", AgentRuntimeState.STOPPED),
    ],
)
def test_non_active_or_unknown_saved_states_are_preserved_or_safely_stopped(
    saved: AgentRuntimeState | str,
    expected: AgentRuntimeState,
) -> None:
    assert effective_runtime_state(saved, actual=None) is expected


@pytest.mark.parametrize(
    "actual",
    list(AgentRuntimeState),
)
def test_loaded_runtime_state_always_overrides_persisted_state(
    actual: AgentRuntimeState,
) -> None:
    assert effective_runtime_state(AgentRuntimeState.RUNNING, actual=actual) is actual
