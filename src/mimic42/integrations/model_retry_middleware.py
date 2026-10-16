"""Повтор вызова модели при отказах провайдера.

Параметр ``models`` (build_chat_model) уже перенаправляет запрос на платную
модель, когда бесплатная недоступна, но насыщены бывают оба звена: документация
OpenRouter описывает такие отказы как изменчивые и рекомендует повторять их с
выдержкой. Собственный повтор SDK покрывает только 5xx и разрывы соединения,
а на 429 отвечает мгновенно — без него прерываются ходы от случайных всплесков,
как на живом прогоне (см. issue #108, серия обращений с «Provider returned error»).

Временные отказы не должны попадать в ленту: ActivityMiddleware и
TokenUsageMiddleware при сборке агента стоят раньше в списке, ждут окончания
повторов и пишут привычный итог. Неисправимые ошибки (404, лимит ходов) идут
дальше без выдержек.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware

logger = logging.getLogger("mimic42.model_retry")

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

DEFAULT_MAX_RETRIES = 2
DEFAULT_BASE_WAIT = 1.5
DEFAULT_MAX_WAIT = 10.0
# Подсказка Retry-After уважается целиком, но доводить ход до её края умеет
# не всегда: длиннее этого потолка — значит, стоит не минутная вспышка, а
# прочный лимит. Такой отказ честнее завершить ход, чем хранить замок хода
# минуты и всё равно упасть.
DEFAULT_MAX_HINT_WAIT = 30.0


class ModelRetryMiddleware(AgentMiddleware):
    def __init__(
        self,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_wait: float = DEFAULT_BASE_WAIT,
        max_wait: float = DEFAULT_MAX_WAIT,
        max_hint_wait: float = DEFAULT_MAX_HINT_WAIT,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._max_retries = max_retries
        self._base_wait = base_wait
        self._max_wait = max_wait
        self._max_hint_wait = max_hint_wait
        self._sleep = sleep if sleep is not None else asyncio.sleep

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        attempt = 0
        while True:
            try:
                return await handler(request)
            except Exception as exc:
                attempt += 1
                retryable = getattr(exc, "status_code", None) in RETRYABLE_STATUSES
                if attempt > self._max_retries or not retryable:
                    raise
                wait = self._wait_for(exc, attempt)
                if wait is None:
                    raise
                logger.warning(
                    "Вызов модели отклонён (%s): повтор %d/%d через %.1f с",
                    type(exc).__name__,
                    attempt,
                    self._max_retries,
                    wait,
                )
                await self._sleep(wait)

    def _wait_for(self, exc: Exception, attempt: int) -> float | None:
        """Пауза перед повтором; None — повторять нет смысла.

        Retry-After — минимум, а не потолок: раннее повторение выжигает ту же
        квоту, что вызвала отказ. Без подсказки работает собственный backoff.
        """
        hinted = _hinted_wait(exc)
        if hinted is not None:
            return None if hinted > self._max_hint_wait else max(hinted, self._base_wait)
        return min(self._base_wait * 2 ** (attempt - 1), self._max_wait)


def _hinted_wait(exc: Exception) -> float | None:
    """Retry-After из тела отказа: API отдаёт его, когда пул отвечает подсказкой."""
    headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    value = headers.get("retry-after")
    if not isinstance(value, str) or not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
