from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier


@pytest.mark.asyncio
async def test_reasoning_endpoint_returns_slim_model_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mimic42.integrations import openrouter_catalog

    fake_map: dict[str, dict[str, Any] | None] = {
        "z-ai/glm-5.3-flash": {
            "supported_efforts": ["max", "high", "low"],
            "default_effort": "max",
            "mandatory": True,
        },
        "poolside/laguna-s-2.1": {"mandatory": False, "default_enabled": True},
    }
    monkeypatch.setattr(openrouter_catalog, "fetch_reasoning_by_model", lambda: _async(fake_map))

    app = create_app(auth_verifier=FakeAuthVerifier(uuid4()))

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/openrouter/reasoning", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"models": fake_map}


@pytest.mark.asyncio
async def test_reasoning_endpoint_returns_503_when_openrouter_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mimic42.integrations import openrouter_catalog

    async def _fail() -> dict[str, Any]:
        raise OSError("connection refused")

    monkeypatch.setattr(openrouter_catalog, "fetch_reasoning_by_model", _fail)

    app = create_app(auth_verifier=FakeAuthVerifier(uuid4()))

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/openrouter/reasoning", headers=AUTH_HEADERS)

    assert response.status_code == 503


async def _async(value: Any) -> Any:
    return value
