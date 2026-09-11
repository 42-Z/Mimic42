"""Slim snapshot of per-model reasoning metadata from the OpenRouter API.

The dashboard fetches reasoning effort options through the backend instead
of calling OpenRouter directly: openrouter.ai is unreachable from some
countries the users may be in, while the backend server can reach it.
"""

from __future__ import annotations

import time
from typing import Any

import aiohttp

_MODELS_URL = "https://openrouter.ai/api/v1/models"
_CACHE_TTL: float = 600.0

_cache: dict[str, dict[str, Any] | None] | None = None
_cache_time: float = 0.0


async def _fetch_models() -> dict[str, Any]:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            _MODELS_URL,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            response.raise_for_status()
            return await response.json()  # type: ignore[no-any-return]


def _reasoning_meta(model: dict[str, Any]) -> dict[str, Any] | None:
    reasoning = model.get("reasoning")
    return reasoning if isinstance(reasoning, dict) else None


async def fetch_reasoning_by_model() -> dict[str, dict[str, Any] | None]:
    """Return ``{slug: reasoning_meta}`` for all OpenRouter models, cached."""
    global _cache, _cache_time
    now = time.monotonic()
    if _cache is not None and now - _cache_time < _CACHE_TTL:
        return _cache
    payload = await _fetch_models()
    _cache = {
        model["id"]: _reasoning_meta(model)
        for model in payload.get("data", [])
        if isinstance(model, dict) and "id" in model
    }
    _cache_time = now
    return _cache
