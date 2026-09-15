from __future__ import annotations

from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.integrations.database_models import AgentModel, AgentOnboardingSessionModel
from mimic42.testing import registry
from mimic42.testing.server import build_test_app
from mimic42.testing.slots import Slot


async def _count_for_owner(
    factory: async_sessionmaker[AsyncSession],
    model: type[AgentModel | AgentOnboardingSessionModel],
    owner_id: UUID,
) -> int:
    async with factory() as session:
        query = select(func.count()).select_from(model).where(model.owner_id == owner_id)
        return int(await session.scalar(query) or 0)


async def test_create_test_agent_endpoint_creates_a_real_agent(clean_slot: Slot) -> None:
    owner_id = clean_slot.persona("full").user_id
    app = build_test_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/__test__/agents",
                json={"owner_id": str(owner_id), "name": "Бегущий", "state": "running"},
            )
            assert response.status_code == 200
            agent_id = UUID(response.json()["agent_id"])

            status = await app.state.agent_manager.get_agent_status(agent_id)
    assert status.owner_id == owner_id
    assert status.state.value == "running"


async def test_reset_endpoint_clears_slot_data(
    clean_slot: Slot,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = clean_slot.persona("full").user_id
    app = build_test_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            created = await client.post(
                "/__test__/agents",
                json={"owner_id": str(owner_id), "name": "К удалению", "state": "stopped"},
            )
            assert created.status_code == 200
            async with db_session_factory() as session:
                session.add(
                    AgentOnboardingSessionModel(
                        owner_id=owner_id, authorization_status="not_started"
                    )
                )
                await session.commit()

            assert await _count_for_owner(db_session_factory, AgentModel, owner_id) == 1
            assert (
                await _count_for_owner(db_session_factory, AgentOnboardingSessionModel, owner_id)
                == 1
            )

            response = await client.post("/__test__/reset", json={"slot": clean_slot.name})
            assert response.status_code == 200

    # No-op хендлер тут не пройдёт: до сброса строки существовали.
    assert await _count_for_owner(db_session_factory, AgentModel, owner_id) == 0
    assert await _count_for_owner(db_session_factory, AgentOnboardingSessionModel, owner_id) == 0


async def test_draft_endpoints_hide_and_locate_incomplete_drafts(
    clean_slot: Slot,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = clean_slot.persona("flow").user_id
    app = build_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        missing = await client.get(
            "/__test__/onboarding/drafts/current", params={"owner_id": str(owner_id)}
        )
        assert missing.status_code == 404

        async with db_session_factory() as session:
            draft_id = uuid4()
            session.add(
                AgentOnboardingSessionModel(
                    id=draft_id, owner_id=owner_id, authorization_status="code_requested"
                )
            )
            await session.commit()

        current = await client.get(
            "/__test__/onboarding/drafts/current", params={"owner_id": str(owner_id)}
        )
        assert current.status_code == 200
        assert current.json()["id"] == str(draft_id)

        hidden = await client.post(
            "/__test__/onboarding/drafts/hide", json={"owner_id": str(owner_id)}
        )
        assert hidden.status_code == 200
        assert hidden.json()["removed"] == 1

        again = await client.get(
            "/__test__/onboarding/drafts/current", params={"owner_id": str(owner_id)}
        )
        assert again.status_code == 404


async def test_onboarding_script_endpoint_sets_code_and_password() -> None:
    app = build_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/__test__/telegram/onboarding/script",
            json={"code": "12345", "password": "secret2fa"},
        )
    assert response.status_code == 200
    account = registry.onboarding_account()
    assert account.expected_code == "12345"
    assert account.password == "secret2fa"
    assert account.password_satisfied is False


async def test_onboarding_reset_endpoint_clears_the_script() -> None:
    registry.onboarding_account().script_code("12345")
    registry.onboarding_account().require_password("secret2fa")
    app = build_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/__test__/telegram/onboarding/reset")
    assert response.status_code == 200
    account = registry.onboarding_account()
    assert account.expected_code is None
    assert account.password is None
    assert account.password_satisfied is True
