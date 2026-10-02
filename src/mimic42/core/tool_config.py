"""Настройка доступных агенту инструментов (settings.enabled_tools).

Ключа нет — включены все инструменты. Пустой список — честный пустой
allowlist. Нечитаемое значение не должно ни ронять агента, ни случайно
выключать всё: в этом случае ведём себя как при отсутствии ключа.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("mimic42.tool_config")


def parse_enabled_tools(raw: Any) -> frozenset[str] | None:
    """Разобрать ``settings.enabled_tools`` в allowlist имён инструментов."""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        logger.warning(
            "enabled_tools has unexpected type %s; enabling all tools",
            type(raw).__name__,
        )
        return None

    names = frozenset(item.strip() for item in raw if isinstance(item, str) and item.strip())
    if not names and raw:
        logger.warning("enabled_tools has no valid tool names; enabling all tools")
        return None
    return names
