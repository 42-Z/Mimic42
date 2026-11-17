from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.onboarding import AgentProfileInput, OnboardingSession, TelegramLoginStatus
from mimic42.core.tool_config import DEFAULT_CONVERSATIONAL_TOOLS, parse_enabled_tools
from mimic42.core.warmup import WarmupState
from mimic42.integrations import database_agent_store
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.integrations.database_models import (
    AgentModel,
    AgentOnboardingSessionModel,
    TelegramSessionModel,
)


@pytest.mark.parametrize(
    "selection",
    [
        {},
        {"enabled_tools": None},
        {"enabled_tools": []},
        {"enabled_tools": ["send_reaction"]},
        {"enabled_tools": "broken"},
    ],
)
async def test_database_creation_materializes_defaults_only_once(
    monkeypatch: pytest.MonkeyPatch, selection: dict[str, Any]
) -> None:
    draft = OnboardingSession(
        onboarding_id=uuid4(),
        owner_id=uuid4(),
        api_id=12345,
        api_hash_secret="hash",
        session_secret="session",
        authorization_status=TelegramLoginStatus.AUTHORIZED,
        settings={"model": "custom/model", **selection},
    )
    model = AgentOnboardingSessionModel(
        id=draft.onboarding_id,
        owner_id=draft.owner_id,
        api_id=draft.api_id,
        api_hash_ciphertext="hash",
        session_ciphertext="session",
        authorization_status="authorized",
        settings=dict(draft.settings),
        auth_generation=draft.auth_generation,
    )
    db = MagicMock(spec=AsyncSession)
    db.__aenter__.return_value = db
    db.begin.return_value = AsyncMock()
    db.scalar = AsyncMock(side_effect=[None, None, model])
    db.flush = AsyncMock()

    def apply_insert_defaults(row: Any) -> None:
        if isinstance(row, AgentModel):
            row.restore_on_start = False

    db.add.side_effect = apply_insert_defaults
    factory = MagicMock(return_value=db)
    monkeypatch.setattr(database_agent_store, "lock_proxy_pool", AsyncMock())
    monkeypatch.setattr(
        database_agent_store, "load_warmup_state", AsyncMock(return_value=WarmupState())
    )
    store = DatabaseAgentStore(cast(async_sessionmaker[AsyncSession], factory))

    profile = AgentProfileInput(name="Mimic", soul_prompt="Soul")
    await store.finalize_onboarding(draft.authorization_ref(), profile)
    added = [call.args[0] for call in db.add.call_args_list]
    [agent] = [row for row in added if isinstance(row, AgentModel)]
    [telegram] = [row for row in added if isinstance(row, TelegramSessionModel)]
    expected = selection.get("enabled_tools", list(DEFAULT_CONVERSATIONAL_TOOLS))
    assert agent.settings == {"model": "custom/model", "enabled_tools": expected}
    assert model.settings == draft.settings

    db.scalar.side_effect = [agent, telegram, model]
    db.add.reset_mock()
    await store.finalize_onboarding(draft.authorization_ref(), profile)
    db.add.assert_not_called()
    assert agent.settings["enabled_tools"] == expected

    rows = MagicMock()
    rows.first.return_value = (agent, telegram, None)
    db.execute = AsyncMock(return_value=rows)
    config = await store.get_runtime_config(agent.id)
    assert config.enabled_tools == parse_enabled_tools(expected)
    agent.settings = {"model": "custom/model"}
    legacy = await store.get_runtime_config(agent.id)
    assert legacy.enabled_tools is None
    assert agent.settings == {"model": "custom/model"}
