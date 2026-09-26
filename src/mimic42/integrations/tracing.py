"""Трейсинг ходов агента в Braintrust (issue #92).

Включается наличием BRAINTRUST_API_KEY: без ключа модуль — no-op, Braintrust
не вызывается ни разу. Сбои трейсинга никогда не роняют ход агента.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import braintrust
from braintrust.integrations.langchain import BraintrustCallbackHandler, set_global_handler
from braintrust.span_types import SpanTypeAttribute

from mimic42.config import Settings

logger = logging.getLogger("mimic42.tracing")

_enabled = False


def tracing_enabled() -> bool:
    """Трейсинг включён: Braintrust инициализирован и готов принимать спаны."""
    return _enabled


def setup_tracing(settings: Settings) -> None:
    """Инициализирует Braintrust и глобальный LangChain-хендлер. Идемпотентно."""
    global _enabled
    if _enabled or not settings.braintrust_api_key:
        return
    try:
        braintrust.init_logger(
            project=settings.braintrust_project,
            api_key=settings.braintrust_api_key,
        )
    except Exception:
        logger.warning("Braintrust tracing disabled: init failed", exc_info=True)
        return
    # Состояние фиксируем сразу после init_logger: SDK уже запущен, спаны работают,
    # даже если установка глобального хендлера ниже не удалась.
    _enabled = True
    try:
        # Глушитель ниже — false positive: braintrust.integrations.langchain переопределяет
        # BraintrustCallbackHandler в except ImportError (fallback без langchain-core), из-за чего
        # ty считает результат конструктора union'ом двух классов.
        set_global_handler(BraintrustCallbackHandler())  # ty: ignore[invalid-argument-type]
    except Exception:
        logger.warning("Braintrust global handler not installed", exc_info=True)
    logger.info("Braintrust tracing enabled (project=%s)", settings.braintrust_project)


def flush_tracing() -> None:
    """Допрашивает очередь логов при остановке приложения (best-effort)."""
    if not _enabled:
        return
    try:
        braintrust.flush()
    except Exception:
        logger.warning("Braintrust flush failed", exc_info=True)


def reset_tracing() -> None:
    """Сбрасывает состояние модуля — только для тестов.

    Глобальный LangChain-хендлер не снимает: тесты монают ``set_global_handler``,
    поэтому снимать его нечего и не нужно.
    """
    global _enabled
    _enabled = False


class TurnTrace:
    """Хэндл корневого спана хода; безопасен при выключенном трейсинге."""

    def __init__(self, span: Any | None) -> None:
        self._span = span

    def log(self, **event: Any) -> None:
        if self._span is None:
            return
        try:
            self._span.log(**event)
        except Exception:
            logger.warning("Braintrust span log failed", exc_info=True)

    def permalink(self) -> str | None:
        if self._span is None:
            return None
        try:
            return self._span.permalink()
        except Exception:
            logger.warning("Braintrust permalink failed", exc_info=True)
            return None


@contextmanager
def turn_span(
    *,
    agent_id: UUID | str,
    turn_id: str,
    peer: str,
    model: str,
    input: Any,
) -> Iterator[TurnTrace]:
    """Корневой спан хода агента.

    Спан делается current на время хода, поэтому вложенные спаны LangChain
    (модель, инструменты, шаги графа) из BraintrustCallbackHandler
    прикрепляются к нему автоматически.
    """
    if not tracing_enabled():
        yield TurnTrace(None)
        return
    try:
        span = braintrust.start_span(
            name=f"turn {peer}", type=SpanTypeAttribute.TASK, set_current=True
        )
        span.log(
            input=input,
            metadata={
                "agent_id": str(agent_id),
                "turn_id": turn_id,
                "peer": peer,
                "model": model,
                "environment": Settings().environment,
            },
        )
    except Exception:
        logger.warning("Braintrust start_span failed", exc_info=True)
        yield TurnTrace(None)
        return
    trace = TurnTrace(span)
    try:
        yield trace
    except Exception as exc:
        trace.log(error=str(exc))
        raise
    finally:
        try:
            span.end()
        except Exception:
            logger.warning("Braintrust span end failed", exc_info=True)
