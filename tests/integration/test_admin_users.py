from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from mimic42.core.admin import AdminUserNotFoundError
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.model_catalog import DEFAULT_LLM_MODEL
from mimic42.integrations.database_admin import DatabaseAdminRepository
from mimic42.integrations.database_models import AgentModel, ProfileModel
from mimic42.testing.slots import Slot


@pytest.mark.asyncio
async def test_user_queries_escape_search_and_keep_stable_pagination(
    admin_db_factory: async_sessionmaker[Any],
    test_slot: Slot,
) -> None:
    owners = [test_slot.persona(key).user_id for key in ("empty", "full", "flow")]
    marker = f"admin-user-{uuid4().hex}"
    created_at = datetime(2099, 1, 1, tzinfo=UTC)
    owners_by_name = {
        owners[0]: f"{marker.upper()} wildcard%_target",
        owners[1]: f"{marker} wildcardXXtarget",
        owners[2]: f"{marker} third profile",
    }
    agent_ids = [uuid4(), uuid4(), uuid4(), uuid4()]
    async with admin_db_factory() as session, session.begin():
        await session.execute(delete(AgentModel).where(AgentModel.owner_id.in_(owners)))
        for owner_id, display_name in owners_by_name.items():
            await session.execute(
                update(ProfileModel)
                .where(ProfileModel.id == owner_id)
                .values(display_name=display_name, created_at=created_at)
            )
        session.add_all(
            [
                AgentModel(
                    id=agent_ids[0],
                    owner_id=owners[0],
                    name="Saved active without runtime",
                    soul_prompt="private prompt",
                    status="running",
                    settings={},
                    created_at=created_at,
                ),
                AgentModel(
                    id=agent_ids[1],
                    owner_id=owners[0],
                    name="Second agent",
                    soul_prompt="another private prompt",
                    status="stopped",
                    settings={"model": "openrouter/custom-model"},
                    created_at=created_at,
                ),
                AgentModel(
                    id=agent_ids[2],
                    owner_id=owners[1],
                    name="Runtime overrides error",
                    soul_prompt="private prompt",
                    status="error",
                    settings={"model": "openrouter/runtime-model"},
                    created_at=created_at,
                ),
                AgentModel(
                    id=agent_ids[3],
                    owner_id=owners[1],
                    name="Draft without runtime",
                    soul_prompt="private prompt",
                    status="draft",
                    settings={},
                    created_at=created_at,
                ),
            ]
        )

    repository = DatabaseAdminRepository(admin_db_factory)
    runtime_states = {agent_ids[2]: AgentRuntimeState.RUNNING}

    page = await repository.list_users(
        q=marker.lower(),
        page=1,
        page_size=10,
        runtime_states=runtime_states,
    )
    empty_runtime_page = await repository.list_users(
        q=marker,
        page=1,
        page_size=10,
        runtime_states={},
    )
    wildcard_matches = await repository.list_users(
        q="wildcard%_target",
        page=1,
        page_size=10,
        runtime_states=runtime_states,
    )
    first_page = await repository.list_users(
        q=marker,
        page=1,
        page_size=1,
        runtime_states=runtime_states,
    )
    second_page = await repository.list_users(
        q=marker,
        page=2,
        page_size=1,
        runtime_states=runtime_states,
    )
    third_page = await repository.list_users(
        q=marker,
        page=3,
        page_size=1,
        runtime_states=runtime_states,
    )

    by_id = {user.user_id: user for user in page.items}
    assert page.total == 3
    assert by_id[owners[0]].agents_total == 2
    assert by_id[owners[0]].states == {AgentRuntimeState.STOPPED: 2}
    assert by_id[owners[1]].agents_total == 2
    assert by_id[owners[1]].states == {
        AgentRuntimeState.RUNNING: 1,
        AgentRuntimeState.STOPPED: 1,
    }
    assert by_id[owners[2]].agents_total == 0
    assert by_id[owners[2]].states == {}
    empty_runtime_users = {user.user_id: user for user in empty_runtime_page.items}
    assert empty_runtime_users[owners[0]].states == {AgentRuntimeState.STOPPED: 2}
    assert empty_runtime_users[owners[1]].states == {
        AgentRuntimeState.ERROR: 1,
        AgentRuntimeState.STOPPED: 1,
    }
    assert [user.user_id for user in wildcard_matches.items] == [owners[0]]
    assert [
        first_page.items[0].user_id,
        second_page.items[0].user_id,
        third_page.items[0].user_id,
    ] == (sorted(owners, key=lambda user_id: user_id.int, reverse=True))

    detail = await repository.get_user(
        owners[0],
        page=1,
        page_size=1,
        runtime_states=runtime_states,
    )
    next_agent_page = await repository.get_user(
        owners[0],
        page=2,
        page_size=1,
        runtime_states=runtime_states,
    )
    empty_detail = await repository.get_user(
        owners[2],
        page=1,
        page_size=10,
        runtime_states=runtime_states,
    )

    assert detail.profile.agents_total == 2
    assert detail.agents.total == 2
    assert detail.agents.items[0].agent_id == max(agent_ids[:2], key=lambda agent_id: agent_id.int)
    assert next_agent_page.agents.items[0].agent_id == min(
        agent_ids[:2], key=lambda agent_id: agent_id.int
    )
    agent_models = {
        agent.agent_id: agent.llm_model
        for agent in [*detail.agents.items, *next_agent_page.agents.items]
    }
    assert agent_models == {
        agent_ids[0]: DEFAULT_LLM_MODEL,
        agent_ids[1]: "openrouter/custom-model",
    }
    assert empty_detail.profile.agents_total == 0
    assert empty_detail.profile.states == {}
    assert empty_detail.agents.total == 0
    assert empty_detail.agents.items == []

    with pytest.raises(AdminUserNotFoundError):
        await repository.get_user(
            uuid4(),
            page=1,
            page_size=25,
            runtime_states=runtime_states,
        )
