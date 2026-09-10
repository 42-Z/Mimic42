from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from telethon import TelegramClient
from telethon.sessions import StringSession

from mimic42.core.agent_runtime import AgentRuntimeConfig


def build_telegram_client(config: AgentRuntimeConfig) -> TelegramClient:
    if config.telegram_session_string:
        client = TelegramClient(
            StringSession(config.telegram_session_string),
            config.telegram_api_id,
            config.telegram_api_hash,
        )
    else:
        session_path = Path(config.telegram_session_name)
        session_path.parent.mkdir(parents=True, exist_ok=True)
        client = TelegramClient(
            str(session_path),
            config.telegram_api_id,
            config.telegram_api_hash,
        )

    from mimic42.integrations.telegram_tools import CustomMarkdown

    client.parse_mode = cast(Any, CustomMarkdown())
    return client
