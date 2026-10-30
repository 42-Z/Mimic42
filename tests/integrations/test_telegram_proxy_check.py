from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr
from python_socks import ProxyType

from mimic42.core.agent_runtime import TelegramProxyConfig
from mimic42.integrations import telegram_proxy_check


class FakeSocket:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeProxy:
    calls: list[dict[str, Any]] = []
    error: Exception | None = None
    socket = FakeSocket()

    def __init__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)

    async def connect(self, **kwargs: Any) -> FakeSocket:
        self.calls[-1]["connect"] = kwargs
        if self.error is not None:
            raise self.error
        return self.socket


@pytest.fixture
def fake_proxy(monkeypatch: pytest.MonkeyPatch) -> type[FakeProxy]:
    FakeProxy.calls = []
    FakeProxy.error = None
    FakeProxy.socket = FakeSocket()
    monkeypatch.setattr(telegram_proxy_check, "Proxy", FakeProxy)
    return FakeProxy


@pytest.mark.asyncio
async def test_check_connects_through_socks5_with_credentials(fake_proxy: type[FakeProxy]) -> None:
    result = await telegram_proxy_check.check_telegram_proxy(
        TelegramProxyConfig(
            protocol="socks5",
            host="proxy.example.test",
            port=1080,
            username="mimic",
            password=SecretStr("secret"),
        )
    )

    assert result.ok is True
    assert result.error is None
    assert result.latency_ms is not None
    assert fake_proxy.calls[0] == {
        "proxy_type": ProxyType.SOCKS5,
        "host": "proxy.example.test",
        "port": 1080,
        "username": "mimic",
        "password": "secret",
        "connect": {
            "dest_host": telegram_proxy_check.TELEGRAM_DC_HOST,
            "dest_port": telegram_proxy_check.TELEGRAM_DC_PORT,
            "timeout": telegram_proxy_check.PROXY_CHECK_TIMEOUT_SECONDS,
        },
    }
    assert fake_proxy.socket.closed is True


@pytest.mark.asyncio
async def test_check_uses_http_protocol(fake_proxy: type[FakeProxy]) -> None:
    await telegram_proxy_check.check_telegram_proxy(
        TelegramProxyConfig(protocol="http", host="proxy.example.test", port=3128)
    )

    assert fake_proxy.calls[0]["proxy_type"] is ProxyType.HTTP


@pytest.mark.asyncio
async def test_check_reports_the_connection_error(fake_proxy: type[FakeProxy]) -> None:
    fake_proxy.error = OSError("connection refused")

    result = await telegram_proxy_check.check_telegram_proxy(
        TelegramProxyConfig(protocol="socks5", host="proxy.example.test", port=1080)
    )

    assert result.ok is False
    assert result.latency_ms is None
    assert result.error == "connection refused"
