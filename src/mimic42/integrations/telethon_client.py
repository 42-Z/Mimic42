from __future__ import annotations

import asyncio
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
SHORT_WAIT_SECONDS = 4
SHORT_WAIT_RETRIED_NOTE = "Mimic42 already retried this short Telegram wait."
WAIT_ERRORS = (
    errors.FloodWaitError,
    errors.FloodPremiumWaitError,
    errors.SlowModeWaitError,
    errors.FloodTestPhoneWaitError,
)


def _can_retry_short_wait(error: BaseException | None) -> bool:
    return (
        isinstance(error, WAIT_ERRORS)
        and 0 <= error.seconds <= SHORT_WAIT_SECONDS
        and SHORT_WAIT_RETRIED_NOTE not in getattr(error, "__notes__", ())
    )


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

    async def _call(
        self,
        sender: Any,
        request: Any,
        ordered: bool = False,
        flood_sleep_threshold: Any = None,
    ) -> Any:
        """Retry rejected RPCs once after a four-second wait, retaining batch successes."""
        try:
            return await super()._call(
                sender, request, ordered=ordered, flood_sleep_threshold=flood_sleep_threshold
            )
        except WAIT_ERRORS as error:
            if not _can_retry_short_wait(error):
                raise
            await asyncio.sleep(SHORT_WAIT_SECONDS)
            return await self._retry_rpc_once(
                sender, request, ordered=ordered, flood_sleep_threshold=flood_sleep_threshold
            )
        except errors.MultiError as error:
            batch = cast(Any, error)
            retry_indices = [
                index
                for index, failure in enumerate(batch.exceptions)
                if _can_retry_short_wait(failure)
            ]
            if not retry_indices:
                raise
            await asyncio.sleep(SHORT_WAIT_SECONDS)
            results = list(batch.results)
            failures = list(batch.exceptions)
            for index in retry_indices:
                try:
                    results[index] = await self._retry_rpc_once(
                        sender,
                        batch.requests[index],
                        ordered=ordered,
                        flood_sleep_threshold=flood_sleep_threshold,
                    )
                except Exception as failure:
                    failures[index] = failure
                else:
                    failures[index] = None
            if any(failure is not None for failure in failures):
                raise errors.MultiError(failures, results, batch.requests)
            return results

    async def _retry_rpc_once(
        self,
        sender: Any,
        request: Any,
        ordered: bool,
        flood_sleep_threshold: Any,
    ) -> Any:
        try:
            return await super()._call(
                sender, request, ordered=ordered, flood_sleep_threshold=flood_sleep_threshold
            )
        except (*WAIT_ERRORS, errors.MultiError) as error:
            failures = (
                cast(Any, error).exceptions if isinstance(error, errors.MultiError) else [error]
            )
            for failure in failures:
                if _can_retry_short_wait(failure):
                    failure.add_note(SHORT_WAIT_RETRIED_NOTE)
            raise

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
