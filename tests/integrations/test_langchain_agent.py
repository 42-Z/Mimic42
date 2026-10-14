from __future__ import annotations

import asyncio
from contextvars import Context
from typing import Any, cast
from uuid import uuid4

import pytest
from braintrust.integrations.langchain import BraintrustCallbackHandler
from braintrust.integrations.langchain.context import set_global_handler
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_openrouter import ChatOpenRouter
from pydantic import SecretStr

import mimic42.integrations.langchain_agent as langchain_agent_module
from mimic42.core.agent_runtime import AgentRuntimeConfig
from mimic42.core.model_catalog import ignored_providers
from mimic42.integrations import tracing
from mimic42.integrations.activity_middleware import ActivityMiddleware
from mimic42.integrations.langchain_agent import (
    MODEL_CALLS_PER_TURN,
    REQUEST_TIMEOUT_MS,
    LangChainGraphAgent,
    build_chat_model,
    build_langchain_agent,
)
from mimic42.integrations.model_retry_middleware import ModelRetryMiddleware
from mimic42.integrations.token_usage_middleware import TokenUsageMiddleware
from mimic42.integrations.tool_access_middleware import ToolAccessMiddleware
from mimic42.integrations.tool_image_middleware import ToolImageMiddleware


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
    build_chat_model(_config("nvidia/nemotron-3.5-lightning"))

    assert recorded == [
        {
            "model": "nvidia/nemotron-3.5-lightning:free",
            "api_key": None,
            "timeout": REQUEST_TIMEOUT_MS,
            "reasoning": {"effort": "high"},
            "model_kwargs": {
                "models": ["nvidia/nemotron-3.5-lightning:free", "nvidia/nemotron-3.5-lightning"]
            },
            "openrouter_provider": {"ignore": ignored_providers("nvidia/nemotron-3.5-lightning")},
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
            "openrouter_provider": {"ignore": ignored_providers("z-ai/glm-5.3-flash")},
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
            "openrouter_provider": {"ignore": ignored_providers("z-ai/glm-5.3-flash")},
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


def test_build_langchain_agent_retries_model_failures_after_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Повторы после уровней записи и до переписи картинок.

    Временные 429/5xx не попадают в ленту и учёт: ActivityMiddleware видит только
    итог, а каждый повторный запрос идёт уже переписанным ToolImageMiddleware."""
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
    retry_index = next(i for i, m in enumerate(middleware) if isinstance(m, ModelRetryMiddleware))
    usage_index = next(
        index for index, m in enumerate(middleware) if isinstance(m, TokenUsageMiddleware)
    )
    image_index = len(middleware) - 1

    assert usage_index < retry_index < image_index
    assert isinstance(middleware[image_index], ToolImageMiddleware)


def test_build_langchain_agent_moves_tool_pictures_into_user_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "graph"

    monkeypatch.setattr(langchain_agent_module, "create_agent", fake_create_agent)

    build_langchain_agent(_config("mistral-small"))

    assert isinstance(captured["middleware"][-1], ToolImageMiddleware)


def test_build_langchain_agent_limits_model_calls_without_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "graph"

    monkeypatch.setattr(langchain_agent_module, "create_agent", fake_create_agent)

    build_langchain_agent(_config("mistral-small"))

    [limit] = [m for m in captured["middleware"] if isinstance(m, ModelCallLimitMiddleware)]
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


@pytest.mark.parametrize("with_context", [False, True])
async def test_graph_agent_traces_when_lifespan_handler_is_not_in_request_context(
    monkeypatch: pytest.MonkeyPatch, with_context: bool
) -> None:
    class Graph:
        async def ainvoke(self, input_data: Any, **kwargs: Any) -> Any:
            return input_data, kwargs

    monkeypatch.setattr(tracing, "_enabled", True)
    Context().run(
        set_global_handler,
        BraintrustCallbackHandler(),  # ty: ignore[invalid-argument-type]
    )
    agent = LangChainGraphAgent(Graph())

    async def invoke() -> Any:
        return await agent.ainvoke({"messages": []}, context="turn" if with_context else None)

    _, kwargs = await asyncio.create_task(invoke(), context=Context())

    assert len(kwargs["config"]["callbacks"]) == 1
    assert isinstance(kwargs["config"]["callbacks"][0], BraintrustCallbackHandler)
    assert kwargs.get("context") == ("turn" if with_context else None)


async def test_graph_agent_does_not_duplicate_global_braintrust_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Graph:
        async def ainvoke(self, input_data: Any, **kwargs: Any) -> Any:
            return kwargs

    monkeypatch.setattr(tracing, "_enabled", True)
    agent = LangChainGraphAgent(Graph())

    async def invoke() -> Any:
        set_global_handler(BraintrustCallbackHandler())  # ty: ignore[invalid-argument-type]
        return await agent.ainvoke({"messages": []})

    kwargs = await asyncio.create_task(invoke(), context=Context())

    assert "config" not in kwargs or kwargs["config"] is None


async def test_graph_agent_does_not_create_handler_when_tracing_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Graph:
        async def ainvoke(self, input_data: Any, **kwargs: Any) -> Any:
            return kwargs

    monkeypatch.setattr(tracing, "_enabled", False)
    agent = LangChainGraphAgent(Graph())
    kwargs: dict[str, Any] = await asyncio.create_task(
        agent.ainvoke({"messages": []}), context=Context()
    )  # ty: ignore[invalid-assignment]

    assert "config" not in kwargs or kwargs["config"] is None


async def test_graph_agent_closes_the_openrouter_http_client() -> None:
    """ChatOpenRouter отдаёт SDK собственный httpx-клиент, и SDK его не закрывает."""
    model = ChatOpenRouter(model="vendor/model", api_key=SecretStr("key"))
    agent = LangChainGraphAgent(graph=object(), model=model)

    await agent.aclose()

    assert model.client.sdk_configuration.async_client.is_closed


def test_build_langchain_agent_guards_disabled_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "graph"

    monkeypatch.setattr(langchain_agent_module, "create_agent", fake_create_agent)

    config = _config("mistral-small")
    config.enabled_tools = frozenset({"send_text_message"})
    build_langchain_agent(config)

    assert any(isinstance(m, ToolAccessMiddleware) for m in captured["middleware"])


def test_build_langchain_agent_without_allowlist_has_no_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "graph"

    monkeypatch.setattr(langchain_agent_module, "create_agent", fake_create_agent)

    build_langchain_agent(_config("mistral-small"))

    assert not any(isinstance(m, ToolAccessMiddleware) for m in captured["middleware"])


def test_build_langchain_agent_guards_before_activity_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "graph"

    monkeypatch.setattr(langchain_agent_module, "create_agent", fake_create_agent)

    config = _config("mistral-small")
    config.enabled_tools = frozenset({"send_text_message"})
    build_langchain_agent(config, session_factory=cast(Any, object()))

    middleware = captured["middleware"]
    guard_index = next(
        index for index, m in enumerate(middleware) if isinstance(m, ToolAccessMiddleware)
    )
    activity_index = next(
        index for index, m in enumerate(middleware) if isinstance(m, ActivityMiddleware)
    )

    assert guard_index < activity_index
