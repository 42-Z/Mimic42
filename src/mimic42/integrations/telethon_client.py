from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from telethon import TelegramClient, errors
from telethon.sessions import StringSession

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    TelegramAuthorizationRequired,
    TelegramProxyConfig,
)

logger = logging.getLogger("mimic42.telethon_client")


class MimicTelegramClient(TelegramClient):
    """Клиент, который сообщает об ограничении аккаунта (PeerFloodError) с любой отправки.

    Все сообщения агента — ответы, инструменты, комментарии, зачины прогрева — идут через
    ``__call__``, так что одна точка ловит ограничение везде и не требует правок каждого пути.
    """

    peer_flood_handler: Callable[[], Awaitable[None]] | None = None
    # Id @SpamBot, который рантайм узнаёт при старте: инструменты по нему отказывают
    # в любом обращении к боту, как бы ни была записана ссылка.
    spambot_user_id: int | None = None
    # USER_BANNED_IN_CHANNEL и USER_RESTRICTED: Telegram описывает их как «ограничен,
    # проверь @SpamBot». Причина может быть и в одном чате, поэтому это лишь подозрение,
    # которое проверяет сам @SpamBot, а не метка ограничения.
    spam_limit_suspect_handler: Callable[[], Awaitable[None]] | None = None

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
        except (errors.UserBannedInChannelError, errors.UserRestrictedError):
            suspect_handler = self.spam_limit_suspect_handler
            if suspect_handler is not None:
                await suspect_handler()
            raise


def build_proxy_argument(proxy: TelegramProxyConfig | None) -> dict[str, Any] | None:
    """Аргумент ``proxy=`` для Telethon; без прокси — None, ключ не передаётся.

    Формат описан в документации Telethon и требует ``python-socks[asyncio]``.
    """
    if proxy is None:
        return None
    argument: dict[str, Any] = {
        "proxy_type": proxy.protocol,
        "addr": proxy.host,
        "port": proxy.port,
        "rdns": True,
    }
    if proxy.username:
        argument["username"] = proxy.username
    if proxy.password is not None:
        argument["password"] = proxy.password.get_secret_value()
    return argument


def build_telegram_client(config: AgentRuntimeConfig) -> TelegramClient:
    if not config.telegram_session_string:
        logger.warning("Agent %s has no stored telegram session string", config.agent_id)
        raise TelegramAuthorizationRequired(
            "Сессия Telegram не привязана. Требуется привязка Telegram-аккаунта."
        )
    proxy_argument = build_proxy_argument(config.telegram_proxy)
    session = StringSession(config.telegram_session_string)
    # По умолчанию порог 60: Telethon сам засыпает на флуд-ошибках короче
    # порога, а SlowModeWaitError — флуд-ошибка. Такой сон прошёл бы внутри
    # send_message под trigger_lock и вернул бы отставание, ради устранения
    # которого сделано окно отправки.
    if proxy_argument is None:
        client = MimicTelegramClient(
            session,
            config.telegram_api_id,
            config.telegram_api_hash,
            flood_sleep_threshold=0,
        )
    else:
        client = MimicTelegramClient(
            session,
            config.telegram_api_id,
            config.telegram_api_hash,
            flood_sleep_threshold=0,
            proxy=proxy_argument,
        )

    from mimic42.integrations.telegram_tools import CustomMarkdown

    client.parse_mode = cast(Any, CustomMarkdown())
    return client
