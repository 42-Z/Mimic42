"""Трейсинг ходов агента в Braintrust (issue #92).

Включается наличием BRAINTRUST_API_KEY: без ключа модуль — no-op, Braintrust
не вызывается ни разу. Сбои трейсинга никогда не роняют ход агента.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import braintrust
from braintrust.integrations.langchain import BraintrustCallbackHandler, set_global_handler

from mimic42.config import Settings

logger = logging.getLogger("mimic42.tracing")


@dataclass
class _TraceState:
    logger: Any


_state: _TraceState | None = None


def tracing_enabled() -> bool:
    """Трейсинг включён: Braintrust инициализирован и готов принимать спаны."""
    return _state is not None


def setup_tracing(settings: Settings) -> None:
    """Инициализирует Braintrust и глобальный LangChain-хендлер. Идемпотентно."""
    global _state
    if _state is not None or not settings.braintrust_api_key:
        return
    try:
        bt_logger = braintrust.init_logger(
            project=settings.braintrust_project,
            api_key=settings.braintrust_api_key,
        )
        # Глушитель ниже — false positive: braintrust.integrations.langchain переопределяет
        # BraintrustCallbackHandler в except ImportError (fallback без langchain-core), из-за чего
        # ty считает результат конструктора union'ом двух классов.
        set_global_handler(BraintrustCallbackHandler())  # ty: ignore[invalid-argument-type]
    except Exception:
        logger.warning("Braintrust tracing disabled: init failed", exc_info=True)
        return
    _state = _TraceState(logger=bt_logger)
    logger.info("Braintrust tracing enabled (project=%s)", settings.braintrust_project)


def flush_tracing() -> None:
    """Допрашивает очередь логов при остановке приложения (best-effort)."""
    if _state is None:
        return
    try:
        braintrust.flush()
    except Exception:
        logger.warning("Braintrust flush failed", exc_info=True)


def reset_tracing() -> None:
    """Сбрасывает состояние модуля — только для тестов."""
    global _state
    _state = None
