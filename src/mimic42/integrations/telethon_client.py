from __future__ import annotations

from typing import Any, cast

from telethon import TelegramClient
from telethon.sessions import StringSession

from mimic42.core.agent_runtime import AgentRuntimeConfig, TelegramAuthorizationRequired


def build_telegram_client(config: AgentRuntimeConfig) -> TelegramClient:
    if not config.telegram_session_string:
        raise TelegramAuthorizationRequired(
            f"Agent {config.agent_id} has no stored Telegram session string — "
            "complete onboarding first"
        )
    client = TelegramClient(
        StringSession(config.telegram_session_string),
        config.telegram_api_id,
        config.telegram_api_hash,
    )

    from mimic42.integrations.telegram_tools import CustomMarkdown

    client.parse_mode = cast(Any, CustomMarkdown())
    return client
