"""Чтение полей из ответов Telegram API.

Telethon возвращает объекты `types.*`, а заглушки в тестах — словари. Оба
варианта здесь приводятся к одному виду, чтобы вызывающий код не разбирался
с формой ответа. Модуль вынесен отдельно: он нужен и онбордингу, и рантайму,
а импорт в любом направлении давал бы цикл.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast


def read_attr(value: object, name: str) -> str:
    """Обязательное строковое поле; пустое или отсутствующее — ошибка."""
    if isinstance(value, Mapping):
        value_map = cast("Mapping[str, Any]", value)
        result = value_map.get(name)
    else:
        result = getattr(value, name, None)
    if not isinstance(result, str) or not result:
        raise ValueError("Telegram не вернул нужные данные. Попробуйте ещё раз.")
    return result


def read_optional_attr(value: object, name: str) -> str | None:
    """Как read_attr, но отсутствие значения — норма, а не ошибка."""
    if isinstance(value, Mapping):
        value_map = cast("Mapping[str, Any]", value)
        result = value_map.get(name)
    else:
        result = getattr(value, name, None)
    if not isinstance(result, str) or not result:
        return None
    return result
