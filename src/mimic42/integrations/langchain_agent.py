from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import BaseTool
from langchain_openrouter import ChatOpenRouter
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.config import Settings
from mimic42.core.activity import ActivityRecorder
from mimic42.core.agent_runtime import AgentRuntimeConfig, LangChainAgentLike, TurnContext
from mimic42.core.model_catalog import resolve_model_chain
from mimic42.integrations.activity_middleware import ActivityMiddleware
from mimic42.integrations.agent_response_schema import AgentResponse


class LangChainGraphAgent:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    async def ainvoke(
        self,
        input_data: dict[str, object],
        context: object | None = None,
    ) -> object:
        if context is not None:
            return await self._graph.ainvoke(input_data, context=context)
        return await self._graph.ainvoke(input_data)


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
    if config.reasoning_effort != "none":
        return ChatOpenRouter(
            model=primary,
            api_key=api_key,
            reasoning={"effort": config.reasoning_effort},
            model_kwargs=model_kwargs,
        )
    return ChatOpenRouter(model=primary, api_key=api_key, model_kwargs=model_kwargs)


def build_langchain_agent(
    config: AgentRuntimeConfig,
    *,
    tools: list[BaseTool] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> LangChainAgentLike:
    model = build_chat_model(config)

    middleware: list[Any] = []
    if session_factory is not None:
        recorder = ActivityRecorder(session_factory)
        middleware.append(ActivityMiddleware(agent_id=config.agent_id, recorder=recorder))

    return LangChainGraphAgent(
        create_agent(
            model=model,
            tools=tools or [],
            system_prompt=config.combined_prompt,
            response_format=AgentResponse,
            context_schema=TurnContext,
            middleware=middleware,
        )
    )
