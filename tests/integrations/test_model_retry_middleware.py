from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from mimic42.integrations.model_retry_middleware import ModelRetryMiddleware


class ProviderFailure(Exception):
    """Отказ в терминах SDK: статус меняет поведение повтора, Retry-After — выдержку."""

    def __init__(self, status_code: int, retry_after: str | None = None) -> None:
        self.status_code = status_code
        self.headers = {} if retry_after is None else {"retry-after": retry_after}


def clock_waited() -> tuple[Callable[[float], Awaitable[None]], list[float]]:
    waited: list[float] = []

    async def fake_sleep(delay: float) -> None:
        waited.append(delay)

    return fake_sleep, waited


def build_handler(plan: list[Any], calls: list[Any]) -> Callable[[Any], Awaitable[Any]]:
    sequence = iter(plan)

    async def handler(request: Any) -> Any:
        calls.append(request)
        step = next(sequence)
        if isinstance(step, Exception):
            raise step
        return step

    return handler


async def test_rate_limit_is_waited_out_and_the_call_succeeds() -> None:
    sleep, waited = clock_waited()
    middleware = ModelRetryMiddleware(sleep=sleep)
    calls: list[Any] = []

    result = await middleware.awrap_model_call(
        "запрос", build_handler([ProviderFailure(429), "ответ"], calls)
    )

    assert result == "ответ"
    assert len(calls) == 2
    assert waited == [1.5]


async def test_retry_after_header_wins_over_the_backoff() -> None:
    sleep, waited = clock_waited()
    middleware = ModelRetryMiddleware(sleep=sleep)
    calls: list[Any] = []

    result = await middleware.awrap_model_call(
        "запрос", build_handler([ProviderFailure(429, "3"), "ответ"], calls)
    )

    assert result == "ответ"
    assert waited == [3.0]


async def test_exhausted_retries_raise_the_last_failure() -> None:
    sleep, waited = clock_waited()
    middleware = ModelRetryMiddleware(sleep=sleep, max_retries=2)
    failure = ProviderFailure(429)

    with pytest.raises(ProviderFailure):
        await middleware.awrap_model_call("запрос", build_handler([failure] * 8, []))

    assert waited == [1.5, 3.0]


@pytest.mark.parametrize("status_code", [404, 400])
async def test_client_errors_are_raised_without_waits(status_code: int) -> None:
    sleep, waited = clock_waited()
    middleware = ModelRetryMiddleware(sleep=sleep)
    calls: list[Any] = []

    with pytest.raises(ProviderFailure):
        await middleware.awrap_model_call(
            "запрос", build_handler([ProviderFailure(status_code)], calls)
        )

    assert calls == ["запрос"]
    assert waited == []


@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
async def test_server_failures_are_retried_too(status_code: int) -> None:
    sleep, _ = clock_waited()
    middleware = ModelRetryMiddleware(sleep=sleep)
    calls: list[Any] = []

    result = await middleware.awrap_model_call(
        "запрос", build_handler([ProviderFailure(status_code), "ответ"], calls)
    )

    assert result == "ответ"
    assert len(calls) == 2
