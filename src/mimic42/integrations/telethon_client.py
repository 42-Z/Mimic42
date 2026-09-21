from __future__ import annotations

from typing import Any, cast

from telethon import TelegramClient
from telethon.sessions import StringSession

from mimic42.core.agent_runtime import AgentRuntimeConfig, TelegramAuthorizationRequired


def build_telegram_client(config: AgentRuntimeConfig) -> TelegramClient:
    if not config.telegram_session_string:
        raise TelegramAuthorizationRequired(
            "Сессия Telegram не привязана. Требуется привязка Telegram-аккаунта."
        )
    client = TelegramClient(
        StringSession(config.telegram_session_string),
        config.telegram_api_id,
        config.telegram_api_hash,
        # По умолчанию порог 60: Telethon сам засыпает на флуд-ошибках короче
        # порога, а SlowModeWaitError — флуд-ошибка. Такой сон прошёл бы внутри
        # send_message под trigger_lock и вернул бы отставание, ради устранения
        # которого сделано окно отправки.
        flood_sleep_threshold=0,
    )

    from mimic42.integrations.telegram_tools import CustomMarkdown

    client.parse_mode = cast(Any, CustomMarkdown())
    return client
