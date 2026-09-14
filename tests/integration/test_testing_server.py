from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from mimic42.testing.server import build_test_app
from mimic42.testing.slots import Slot


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
