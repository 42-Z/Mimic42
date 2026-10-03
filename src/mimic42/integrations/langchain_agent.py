from __future__ import annotations

import logging
from typing import Any

from braintrust.integrations.langchain import BraintrustCallbackHandler
from braintrust.integrations.langchain.context import get_global_handler
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.tools import BaseTool
from langchain_openrouter import ChatOpenRouter
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.config import Settings
from mimic42.core.activity import ActivityRecorder
from mimic42.core.agent_runtime import AgentRuntimeConfig, LangChainAgentLike, TurnContext
from mimic42.core.model_catalog import ignored_providers, resolve_model_chain
from mimic42.core.token_usage import TokenUsageRecorder
from mimic42.integrations.activity_middleware import ActivityMiddleware
from mimic42.integrations.agent_response_schema import AgentResponse
from mimic42.integrations.token_usage_middleware import TokenUsageMiddleware
from mimic42.integrations.tool_access_middleware import ToolAccessMiddleware
from mimic42.integrations.tracing import tracing_enabled

logger = logging.getLogger("mimic42.tracing")

# A request stuck at the provider otherwise holds the agent's turn forever; the
# client retries a timed-out request itself (max_retries).
REQUEST_TIMEOUT_MS = 120_000

# Model calls allowed in one turn. Real turns take up to ~7 (six tool calls
# plus the answer); a model that keeps ignoring the required response tool
# would otherwise be re-asked until LangGraph's 1000-step recursion limit.
MODEL_CALLS_PER_TURN = 20


class LangChainGraphAgent:
    def __init__(self, graph: Any, model: str | ChatOpenRouter | None = None) -> None:
        self._graph = graph
        self._model = model

    async def aclose(self) -> None:
        """Release the model's HTTP connections.

        ChatOpenRouter hands the OpenRouter SDK its own httpx clients, and the
        SDK only closes clients it created itself, so nothing else closes them.
        Called once the runtime is discarded, never on stop: a stopped runtime
        is started again with the same agent.
        """
        if not isinstance(self._model, ChatOpenRouter):
            return
        configuration = self._model.client.sdk_configuration
        if configuration.async_client is not None:
            await configuration.async_client.aclose()
        if configuration.client is not None:
            configuration.client.close()

    async def ainvoke(
        self,
        input_data: dict[str, object],
        context: object | None = None,
    ) -> object:
        config = None
        if tracing_enabled():
            try:
                # Uvicorn's lifespan and request tasks have separate ContextVar contexts.
                # Restored agents already inherit the global handler; API-created ones may not.
                if get_global_handler() is None:
                    config = {"callbacks": [BraintrustCallbackHandler()]}
            except Exception:
                logger.warning("Braintrust graph callback unavailable", exc_info=True)
        if context is not None:
            return await self._graph.ainvoke(input_data, config=config, context=context)
        return await self._graph.ainvoke(input_data, config=config)


def build_chat_model(
    config: AgentRuntimeConfig,
) -> str | ChatOpenRouter:
    """Build the chat model, wiring the OpenRouter fallback chain.

    Models with a free variant are requested through the free slug with the
    ``models`` parameter carrying ``[free, paid]``: OpenRouter switches to
    the paid model itself when the free variant is rate-limited. Unknown
    slugs keep the historical behaviour of the previous implementation.
    """
    if not (config.llm_model.startswith("openrouter/") or "/" in config.llm_model):
        return config.llm_model

    settings = Settings()
    chain = resolve_model_chain(config.llm_model)
    primary = chain[0]
    if primary.startswith("openrouter/") and primary != "openrouter/free":
        primary = primary.replace("openrouter/", "", 1)
    api_key = (
        SecretStr(settings.openrouter_api_key) if settings.openrouter_api_key is not None else None
    )
    model_kwargs: dict[str, Any] = {"models": chain} if len(chain) > 1 else {}
    options: dict[str, Any] = {}
    if config.reasoning_effort != "none":
        options["reasoning"] = {"effort": config.reasoning_effort}
    options["model_kwargs"] = model_kwargs
    ignored = ignored_providers(config.llm_model)
    if ignored:
        options["openrouter_provider"] = {"ignore": ignored}
    return ChatOpenRouter(model=primary, api_key=api_key, timeout=REQUEST_TIMEOUT_MS, **options)


def build_langchain_agent(
    config: AgentRuntimeConfig,
    *,
    tools: list[BaseTool] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> LangChainAgentLike:
    model = build_chat_model(config)

    # "error", not "end": on "end" the runtime would find no structured response
    # and send LangChain's limit notice to the chat as the reply.
    middleware: list[Any] = [
        ModelCallLimitMiddleware(run_limit=MODEL_CALLS_PER_TURN, exit_behavior="error")
    ]
    if config.enabled_tools is not None:
        # Внешний слой к ActivityMiddleware: заблокированный вызов не должен
        # попадать в ленту активности.
        middleware.append(ToolAccessMiddleware(config.enabled_tools))
    if session_factory is not None:
        recorder = ActivityRecorder(session_factory)
        middleware.append(ActivityMiddleware(agent_id=config.agent_id, recorder=recorder))
        middleware.append(
            TokenUsageMiddleware(
                agent_id=config.agent_id,
                recorder=TokenUsageRecorder(session_factory),
            )
        )

    return LangChainGraphAgent(
        create_agent(
            model=model,
            tools=tools or [],
            system_prompt=config.combined_prompt,
            response_format=AgentResponse,
            context_schema=TurnContext,
            middleware=middleware,
        ),
        model=model,
    )
