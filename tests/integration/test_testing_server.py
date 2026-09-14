from __future__ import annotations

from uuid import UUID

from httpx import ASGITransport, AsyncClient

from mimic42.testing import registry
from mimic42.testing.server import build_test_app
from mimic42.testing.slots import Slot


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


async def test_reset_endpoint_clears_slot_data(clean_slot: Slot) -> None:
    app = build_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/__test__/reset", json={"slot": clean_slot.name})
    assert response.status_code == 200


async def test_health_endpoint_still_works() -> None:
    app = build_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")
    assert response.json()["status"] == "ok"


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
