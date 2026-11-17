from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from mimic42.api.app import CreateAgentRequest
from mimic42.core.agent_store import InMemoryAgentStore
from mimic42.core.onboarding import (
    AgentOnboardingService,
    AgentProfileInput,
    InMemoryOnboardingRepository,
    OnboardingSession,
    TelegramLoginStatus,
)
from mimic42.core.tool_config import (
    DEFAULT_CONVERSATIONAL_TOOLS,
    parse_enabled_tools,
    with_default_tools,
)
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramAuthClientFactory

REMOVED_DEFAULT_TOOLS = (
    "send_voice_note",
    "send_video_note",
    "send_sticker",
    "send_poll",
    "pin_message",
    "unpin_message",
)

SELECTIONS = (
    ({}, frozenset(DEFAULT_CONVERSATIONAL_TOOLS)),
    ({"enabled_tools": None}, None),
    ({"enabled_tools": []}, frozenset()),
    ({"enabled_tools": ["send_reaction", "unknown"]}, frozenset({"send_reaction", "unknown"})),
    ({"enabled_tools": list(REMOVED_DEFAULT_TOOLS)}, frozenset(REMOVED_DEFAULT_TOOLS)),
    ({"enabled_tools": "broken"}, None),
    ({"enabled_tools": [42]}, None),
)


@pytest.mark.parametrize(("selection", "expected"), SELECTIONS)
def test_materialization_preserves_explicit_selection_and_other_keys(
    selection: dict[str, Any], expected: frozenset[str] | None
) -> None:
    original = {"model": "custom/model", "warmup": {"enabled": True}, **selection}
    before = json.dumps(original)
    result = with_default_tools(original)
    assert parse_enabled_tools(result["enabled_tools"]) == expected
    assert result["model"] == original["model"]
    assert result["warmup"] == original["warmup"]
    assert json.dumps(original) == before
    assert result is not original
    if "enabled_tools" in selection:
        assert result["enabled_tools"] == selection["enabled_tools"]


def test_default_lists_are_independent_and_match_official_preset_migration() -> None:
    first = with_default_tools(None)
    second = with_default_tools({})
    first["enabled_tools"].clear()
    assert second["enabled_tools"] == list(DEFAULT_CONVERSATIONAL_TOOLS)
    assert len(DEFAULT_CONVERSATIONAL_TOOLS) == len(set(DEFAULT_CONVERSATIONAL_TOOLS)) == 31
    migration = max(
        Path("supabase/migrations").glob("*_conversational_tool_defaults.sql"),
        key=lambda path: path.name,
    ).read_text()
    payload = migration.split("'[", 1)[1].split("]'::jsonb", 1)[0]
    assert json.loads("[" + payload + "]") == list(DEFAULT_CONVERSATIONAL_TOOLS)
    assert "where owner_id is null" in migration
    assert "jsonb_set(" in migration
    assert "coalesce(settings, '{}'::jsonb)" in migration


def test_defaults_preserve_incoming_media_tools_without_removed_actions() -> None:
    enabled = frozenset(with_default_tools(None)["enabled_tools"])
    assert enabled.isdisjoint(REMOVED_DEFAULT_TOOLS)
    assert {
        "get_messages",
        "view_image",
        "transcribe_voice_note",
        "get_sticker_sets",
        "get_stickers_in_set",
        "search_sticker_sets",
    } <= enabled


@pytest.mark.parametrize(("selection", "expected"), SELECTIONS)
async def test_preview_and_in_memory_creation_share_defaults_without_mutating_draft(
    selection: dict[str, Any], expected: frozenset[str] | None
) -> None:
    repository = InMemoryOnboardingRepository()
    store = InMemoryAgentStore()
    service = AgentOnboardingService(
        repository=repository,
        agent_store=store,
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
    )
    draft = OnboardingSession(
        onboarding_id=uuid4(),
        owner_id=uuid4(),
        api_id=12345,
        api_hash_secret="hash",
        session_secret="session",
        authorization_status=TelegramLoginStatus.AUTHORIZED,
        name="Mimic",
        soul_prompt="Short replies",
        settings={"other": True, **selection},
    )
    await repository.save(draft)
    preview = await service.build_runtime_config(draft.onboarding_id)
    assert preview.enabled_tools == expected
    assert (await repository.get(draft.onboarding_id)).settings == draft.settings
    profile = AgentProfileInput(name="Mimic", soul_prompt="Short replies")
    await store.finalize_onboarding(draft.authorization_ref(), profile)
    created = await store.get_runtime_config(draft.onboarding_id)
    assert created.enabled_tools == expected
    await store.finalize_onboarding(draft.authorization_ref(), profile)
    assert await store.get_runtime_config(draft.onboarding_id) == created
    assert (await service.build_runtime_config(draft.onboarding_id)).enabled_tools == expected


def test_direct_creation_defaults_do_not_change_legacy_runtime_configs() -> None:
    config = CreateAgentRequest().to_runtime_config(owner_id=uuid4(), api_id=12345, api_hash="hash")
    assert config.enabled_tools == frozenset(DEFAULT_CONVERSATIONAL_TOOLS)
    legacy = config.model_dump(exclude={"enabled_tools"})
    assert type(config).model_validate(legacy).enabled_tools is None
