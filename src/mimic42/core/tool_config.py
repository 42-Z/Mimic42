"""Настройка доступных агенту инструментов (settings.enabled_tools).

Ключа нет — включены все инструменты. Пустой список — честный пустой
allowlist. Нечитаемое значение не должно ни ронять агента, ни случайно
выключать всё: в этом случае ведём себя как при отсутствии ключа.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger("mimic42.tool_config")

DEFAULT_CONVERSATIONAL_TOOLS = (
    "get_dialogs",
    "get_chat_info",
    "get_profile",
    "get_messages",
    "search_messages",
    "get_discussion_messages",
    "send_text_message",
    "edit_text_message",
    "delete_messages",
    "forward_messages",
    "send_reaction",
    "get_message_reactions",
    "mark_chat_as_read",
    "send_chat_action",
    "join_channel",
    "join_channel_discussion",
    "check_admin_permissions",
    "get_message_buttons",
    "click_inline_button",
    "click_reply_keyboard_button",
    "start_bot",
    "view_image",
    "send_file",
    "transcribe_voice_note",
    "read_document_file",
    "get_sticker_sets",
    "get_stickers_in_set",
    "search_sticker_sets",
    "query_inline_bot",
    "send_inline_bot_result",
    "set_wakeup_timer",
)


def with_default_tools(settings: Mapping[str, Any] | None) -> dict[str, Any]:
    """Materialize the default only when creating an agent without a selection."""
    result = dict(settings or {})
    if "enabled_tools" not in result:
        result["enabled_tools"] = list(DEFAULT_CONVERSATIONAL_TOOLS)
    return result


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
