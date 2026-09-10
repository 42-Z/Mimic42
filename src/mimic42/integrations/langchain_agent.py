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


def build_langchain_agent(
    config: AgentRuntimeConfig,
    *,
    tools: list[BaseTool] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> LangChainAgentLike:
    model: str | ChatOpenRouter
    if config.llm_model.startswith("openrouter/") or "/" in config.llm_model:
        settings = Settings()
        model_name = config.llm_model
        if model_name.startswith("openrouter/") and model_name != "openrouter/free":
            model_name = model_name.replace("openrouter/", "", 1)
        api_key = (
            SecretStr(settings.openrouter_api_key)
            if settings.openrouter_api_key is not None
            else None
        )
        if config.reasoning_effort != "none":
            model = ChatOpenRouter(
                model=model_name,
                api_key=api_key,
                reasoning={"effort": config.reasoning_effort},
            )
        else:
            model = ChatOpenRouter(model=model_name, api_key=api_key)
    else:
        model = config.llm_model

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
