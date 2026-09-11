from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

import mimic42.integrations.langchain_agent as langchain_agent_module
from mimic42.core.agent_runtime import AgentRuntimeConfig
from mimic42.integrations.langchain_agent import build_chat_model


def _config(llm_model: str, reasoning_effort: str = "high") -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_session_name="sess",
        telegram_api_id=12345,
        telegram_api_hash="hash",
        system_prompt="system",
        llm_model=llm_model,
        reasoning_effort=reasoning_effort,
    )


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_chat_open_router(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return kwargs

    class StubSettings:
        openrouter_api_key: str | None = None

    monkeypatch.setattr(langchain_agent_module, "ChatOpenRouter", fake_chat_open_router)
    # Tests must not depend on a local .env providing OPENROUTER_API_KEY.
    monkeypatch.setattr(langchain_agent_module, "Settings", StubSettings)
    return calls


def test_model_with_free_variant_builds_fallback_chain(recorded: list[dict[str, Any]]) -> None:
    build_chat_model(_config("poolside/laguna-s-2.1"))

    assert recorded == [
        {
            "model": "poolside/laguna-s-2.1:free",
            "api_key": None,
            "reasoning": {"effort": "high"},
            "model_kwargs": {"models": ["poolside/laguna-s-2.1:free", "poolside/laguna-s-2.1"]},
        }
    ]


def test_paid_only_model_gets_single_slug(recorded: list[dict[str, Any]]) -> None:
    build_chat_model(_config("z-ai/glm-5.3-flash"))

    assert recorded == [
        {
            "model": "z-ai/glm-5.3-flash",
            "api_key": None,
            "reasoning": {"effort": "high"},
            "model_kwargs": {},
        }
    ]


def test_unknown_slash_slug_passes_through(recorded: list[dict[str, Any]]) -> None:
    build_chat_model(_config("vendor/legacy-model"))

    assert recorded == [
        {
            "model": "vendor/legacy-model",
            "api_key": None,
            "reasoning": {"effort": "high"},
            "model_kwargs": {},
        }
    ]


def test_openrouter_free_stays_special(recorded: list[dict[str, Any]]) -> None:
    build_chat_model(_config("openrouter/free", reasoning_effort="none"))

    assert recorded == [{"model": "openrouter/free", "api_key": None, "model_kwargs": {}}]


def test_plain_name_without_slash_is_returned_as_string() -> None:
    assert build_chat_model(_config("mistral-small", reasoning_effort="none")) == "mistral-small"
