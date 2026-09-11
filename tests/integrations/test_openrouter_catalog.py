from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from mimic42.integrations import openrouter_catalog


@pytest.fixture(autouse=True)
def _reset_cache() -> Iterator[None]:
    openrouter_catalog._cache = None
    openrouter_catalog._cache_time = 0.0
    yield
    openrouter_catalog._cache = None
    openrouter_catalog._cache_time = 0.0


@pytest.mark.asyncio
async def test_reasoning_map_extracts_catalog_models_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def fake_fetch() -> dict[str, Any]:
        calls.append(1)
        return {
            "data": [
                {"id": "z-ai/glm-5.3-flash", "reasoning": {"supported_efforts": ["max"]}},
                {"id": "deepseek/deepseek-v4-flash-0731", "reasoning": {"mandatory": False}},
                {"id": "poolside/laguna-s-2.1", "reasoning": {"mandatory": False}},
                {"id": "some/other-gateway-model", "reasoning": {"supported_efforts": ["high"]}},
                {"id": "another/one"},
            ]
        }

    monkeypatch.setattr(openrouter_catalog, "_fetch_models", fake_fetch)

    result = await openrouter_catalog.fetch_reasoning_by_model()

    # Только модели из каталога меню: остальной гейтвей не нужен дашборду.
    assert set(result) == {
        "z-ai/glm-5.3-flash",
        "deepseek/deepseek-v4-flash-0731",
        "inclusionai/ling-3.0-flash-vl",
        "meituan/longcat-2.0",
        "poolside/laguna-s-2.1",
    }
    assert result["z-ai/glm-5.3-flash"] == {"supported_efforts": ["max"]}
    assert result["meituan/longcat-2.0"] is None


@pytest.mark.asyncio
async def test_reasoning_map_is_cached_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def fake_fetch() -> dict[str, Any]:
        calls.append(1)
        return {"data": [{"id": "m", "reasoning": None}]}

    monkeypatch.setattr(openrouter_catalog, "_fetch_models", fake_fetch)

    first = await openrouter_catalog.fetch_reasoning_by_model()
    second = await openrouter_catalog.fetch_reasoning_by_model()

    assert calls == [1]
    assert first is second


@pytest.mark.asyncio
async def test_reasoning_map_refetches_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def fake_fetch() -> dict[str, Any]:
        calls.append(1)
        return {"data": []}

    monkeypatch.setattr(openrouter_catalog, "_fetch_models", fake_fetch)

    await openrouter_catalog.fetch_reasoning_by_model()
    openrouter_catalog._cache_time -= openrouter_catalog._CACHE_TTL + 1
    await openrouter_catalog.fetch_reasoning_by_model()

    assert len(calls) == 2


def test_cache_ttl_is_at_least_five_minutes() -> None:
    assert openrouter_catalog._CACHE_TTL >= 300
