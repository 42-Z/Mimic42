"""Трейсинг ходов агента в Braintrust (issue #92).

Включается наличием BRAINTRUST_API_KEY: без ключа модуль — no-op, Braintrust
не вызывается ни разу. Сбои трейсинга никогда не роняют ход агента.
"""

from __future__ import annotations

import asyncio
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
_environment: str | None = None


def tracing_enabled() -> bool:
    """Трейсинг включён: Braintrust инициализирован и готов принимать спаны."""
    return _enabled


def setup_tracing(settings: Settings) -> None:
    """Инициализирует Braintrust и глобальный LangChain-хендлер. Идемпотентно."""
    global _enabled, _environment
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
    # Окружение кэшируем здесь: в ходе Settings() больше не конструируется.
    _environment = settings.environment
    _enabled = True
    try:
        # Глушитель ниже — false positive: braintrust.integrations.langchain переопределяет
        # BraintrustCallbackHandler в except ImportError (fallback без langchain-core), из-за чего
        # ty считает результат конструктора union'ом двух классов.
        set_global_handler(BraintrustCallbackHandler())  # ty: ignore[invalid-argument-type]
    except Exception:
        logger.warning("Braintrust global handler not installed", exc_info=True)
    logger.info("Braintrust tracing enabled (project=%s)", settings.braintrust_project)


async def flush_tracing(timeout: float = 5.0) -> None:
    """Допрашивает очередь логов при остановке приложения (best-effort).

    Зовётся одной строкой ``await`` первой строкой ``finally`` lifespan, до
    остановки агентов. СDK-flush синхронный и таймаута не принимает, поэтому
    идёт в ``asyncio.to_thread`` под ``wait_for``: зависший ``braintrust.flush``
    отпускает shutdown по ``timeout``, а не вешает его.

    Спаны, завершающиеся позже (например во время ``manager.shutdown()``),
    добирает atexit-flush SDK при выходе процесса: это осознанная семантика
    одного flush в lifespan, а не утечка.
    """
    if not _enabled:
        return
    try:
        await asyncio.wait_for(asyncio.to_thread(braintrust.flush), timeout)
    except TimeoutError:
        logger.warning("Braintrust flush timed out after %.1fs", timeout)
    except Exception:
        logger.warning("Braintrust flush failed", exc_info=True)


def reset_tracing() -> None:
    """Сбрасывает состояние модуля — только для тестов.

    Глобальный LangChain-хендлер не снимает: тесты мокают ``set_global_handler``,
    поэтому снимать его нечего и не нужно.
    """
    global _enabled, _environment
    _enabled = False
    _environment = None


class TurnTrace:
    """Хэндл корневого спана хода; безопасен при выключенном трейсинге.

    ``log`` зовётся внутри блока ``turn_span``: после выхода из блока спан
    закрыт, и из хэндла доступен только ``permalink``.
    """

    def __init__(self, span: Any | None) -> None:
        self._span = span

    def log(self, **event: Any) -> None:
        """Пишет событие в спан; зовётся внутри блока ``turn_span``.

        После выхода из блока спан закрыт — из хэндла доступен только ``permalink``.
        """
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

    ``start_span(..., set_current=True)`` лишь запоминает флаг: контекст ставит
    только ``with``-блок (``Span.__enter__`` → ``Span.set_current``), поэтому
    current-пара ``set_current``/``unset_current`` управляется здесь явно.
    """
    if not tracing_enabled():
        yield TurnTrace(None)
        return
    try:
        span = braintrust.start_span(name=f"turn {peer}", type=SpanTypeAttribute.TASK)
    except Exception:
        logger.warning("Braintrust start_span failed", exc_info=True)
        yield TurnTrace(None)
        return
    trace = TurnTrace(span)
    try:
        try:
            span.set_current()
        except Exception:
            logger.warning("Braintrust span set_current failed", exc_info=True)
        try:
            span.log(
                input=input,
                metadata={
                    "agent_id": str(agent_id),
                    "turn_id": turn_id,
                    "peer": peer,
                    "model": model,
                    "environment": _environment,
                },
            )
        except Exception:
            logger.warning("Braintrust initial span log failed", exc_info=True)
        yield trace
    except BaseException as exc:
        trace.log(error=str(exc) or type(exc).__name__)
        raise
    finally:
        # Закрытие спана безусловное: BaseException из unset_current (например,
        # отмена) не должен оставлять спан открытым — как и BaseException из
        # set_current выше. У каждого шага свой guard, end() гарантированно
        # выполняется во вложенном finally.
        try:
            try:
                span.unset_current()
            except Exception:
                logger.warning("Braintrust span unset_current failed", exc_info=True)
        finally:
            try:
                span.end()
            except Exception:
                logger.warning("Braintrust span end failed", exc_info=True)
