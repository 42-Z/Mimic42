from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from telethon import TelegramClient, errors
from telethon.sessions import StringSession

from mimic42.core.agent_runtime import AgentRuntimeConfig, TelegramAuthorizationRequired

logger = logging.getLogger("mimic42.telethon_client")


class MimicTelegramClient(TelegramClient):
    """Клиент, который сообщает об ограничении аккаунта (PeerFloodError) с любой отправки.

    Все сообщения агента — ответы, инструменты, комментарии, зачины прогрева — идут через
    ``__call__``, так что одна точка ловит ограничение везде и не требует правок каждого пути.
    """

    peer_flood_handler: Callable[[], Awaitable[None]] | None = None

    async def __call__(
        self, request: Any, ordered: bool = False, flood_sleep_threshold: Any = None
    ) -> Any:
        try:
            return await super().__call__(
                request, ordered=ordered, flood_sleep_threshold=flood_sleep_threshold
            )
        except errors.PeerFloodError:
            handler = self.peer_flood_handler
            if handler is not None:
                await handler()
            raise


def build_telegram_client(config: AgentRuntimeConfig) -> TelegramClient:
    if not config.telegram_session_string:
        logger.warning("Agent %s has no stored telegram session string", config.agent_id)
        raise TelegramAuthorizationRequired(
            "Сессия Telegram не привязана. Требуется привязка Telegram-аккаунта."
        )
    client = MimicTelegramClient(
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
