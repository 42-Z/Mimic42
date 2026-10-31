from __future__ import annotations

import pytest
from telethon import TelegramClient

from mimic42.core.agent_runtime import TelegramProxyConfig
from mimic42.core.telegram_proxy import TelegramProxyUnavailableError
from mimic42.integrations.telegram_auth import TelethonAuthClient


@pytest.mark.asyncio
async def test_connect_failure_through_proxy_is_reported_as_proxy_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(_self: object) -> None:
        raise OSError("no route to host")

    monkeypatch.setattr(TelegramClient, "connect", fail)
    client = TelethonAuthClient(
        api_id=12345,
        api_hash="hash",
        proxy=TelegramProxyConfig(protocol="socks5", host="proxy.example.test", port=1080),
    )

    with pytest.raises(TelegramProxyUnavailableError, match="прокси"):
        await client.connect()


@pytest.mark.asyncio
async def test_connect_failure_without_proxy_is_not_misclassified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(_self: object) -> None:
        raise OSError("network is down")

    monkeypatch.setattr(TelegramClient, "connect", fail)
    client = TelethonAuthClient(api_id=12345, api_hash="hash")

    with pytest.raises(OSError, match="network is down"):
        await client.connect()
