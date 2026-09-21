from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from langchain.agents.middleware import ModelCallLimitMiddleware

import mimic42.integrations.langchain_agent as langchain_agent_module
from mimic42.core.agent_runtime import AgentRuntimeConfig
from mimic42.integrations.langchain_agent import (
    MODEL_CALLS_PER_TURN,
    REQUEST_TIMEOUT_MS,
    build_chat_model,
    build_langchain_agent,
)
from mimic42.integrations.token_usage_middleware import TokenUsageMiddleware


def _config(llm_model: str, reasoning_effort: str = "high") -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_session_string="sess",
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
    build_chat_model(_config("inclusionai/ling-3.0-flash-vl"))

    assert recorded == [
        {
            "model": "inclusionai/ling-3.0-flash-vl:free",
            "api_key": None,
            "timeout": REQUEST_TIMEOUT_MS,
            "reasoning": {"effort": "high"},
            "model_kwargs": {
                "models": ["inclusionai/ling-3.0-flash-vl:free", "inclusionai/ling-3.0-flash-vl"]
            },
        }
    ]


def test_paid_only_model_gets_single_slug(recorded: list[dict[str, Any]]) -> None:
    build_chat_model(_config("deepseek/deepseek-v4-flash-0731"))

    assert recorded == [
        {
            "model": "deepseek/deepseek-v4-flash-0731",
            "api_key": None,
            "timeout": REQUEST_TIMEOUT_MS,
            "reasoning": {"effort": "high"},
            "model_kwargs": {},
        }
    ]


def test_ignored_providers_are_excluded_from_routing(recorded: list[dict[str, Any]]) -> None:
    build_chat_model(_config("z-ai/glm-5.3-flash"))

    assert recorded == [
        {
            "model": "z-ai/glm-5.3-flash",
            "api_key": None,
            "timeout": REQUEST_TIMEOUT_MS,
            "reasoning": {"effort": "high"},
            "model_kwargs": {},
            "openrouter_provider": {"ignore": ["morph"]},
        }
    ]


def test_ignored_providers_apply_without_reasoning(recorded: list[dict[str, Any]]) -> None:
    build_chat_model(_config("z-ai/glm-5.3-flash", reasoning_effort="none"))

    assert recorded == [
        {
            "model": "z-ai/glm-5.3-flash",
            "api_key": None,
            "timeout": REQUEST_TIMEOUT_MS,
            "model_kwargs": {},
            "openrouter_provider": {"ignore": ["morph"]},
        }
    ]


def test_unknown_slash_slug_passes_through(recorded: list[dict[str, Any]]) -> None:
    build_chat_model(_config("vendor/legacy-model"))

    assert recorded == [
        {
            "model": "vendor/legacy-model",
            "api_key": None,
            "timeout": REQUEST_TIMEOUT_MS,
            "reasoning": {"effort": "high"},
            "model_kwargs": {},
        }
    ]


def test_openrouter_free_stays_special(recorded: list[dict[str, Any]]) -> None:
    build_chat_model(_config("openrouter/free", reasoning_effort="none"))

    assert recorded == [
        {
            "model": "openrouter/free",
            "api_key": None,
            "timeout": REQUEST_TIMEOUT_MS,
            "model_kwargs": {},
        }
    ]


def test_plain_name_without_slash_is_returned_as_string() -> None:
    assert build_chat_model(_config("mistral-small", reasoning_effort="none")) == "mistral-small"


def test_build_langchain_agent_registers_token_usage_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "graph"

    monkeypatch.setattr(langchain_agent_module, "create_agent", fake_create_agent)

    build_langchain_agent(
        _config("mistral-small"),
        session_factory=object(),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    )

    middleware = captured["middleware"]
    assert any(isinstance(m, TokenUsageMiddleware) for m in middleware)


def test_build_langchain_agent_limits_model_calls_without_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "graph"

    monkeypatch.setattr(langchain_agent_module, "create_agent", fake_create_agent)

    build_langchain_agent(_config("mistral-small"))

    [limit] = captured["middleware"]
    assert isinstance(limit, ModelCallLimitMiddleware)
    assert limit.run_limit == MODEL_CALLS_PER_TURN
    # "end" would let the runtime send LangChain's limit notice to the chat.
    assert limit.exit_behavior == "error"


def test_build_langchain_agent_limits_model_calls_with_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "graph"

    monkeypatch.setattr(langchain_agent_module, "create_agent", fake_create_agent)

    build_langchain_agent(
        _config("mistral-small"),
        session_factory=object(),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    )

    assert any(isinstance(m, ModelCallLimitMiddleware) for m in captured["middleware"])


def test_request_timeout_is_two_minutes() -> None:
    # Без таймаута зависший у провайдера запрос держит ход агента бесконечно.
    assert REQUEST_TIMEOUT_MS == 120_000
