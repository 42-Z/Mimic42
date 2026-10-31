from __future__ import annotations

import logging
import time

from python_socks import ProxyType
from python_socks.async_.asyncio import Proxy

from mimic42.core.agent_runtime import TelegramProxyConfig
from mimic42.core.telegram_proxy import TelegramProxyCheckResult

logger = logging.getLogger("mimic42.telegram_proxy_check")

TELEGRAM_DC_HOST = "149.154.167.51"
TELEGRAM_DC_PORT = 443
PROXY_CHECK_TIMEOUT_SECONDS = 10.0


async def check_telegram_proxy(
    config: TelegramProxyConfig,
    *,
    timeout: float = PROXY_CHECK_TIMEOUT_SECONDS,
) -> TelegramProxyCheckResult:
    """Проверить прокси подключением к DC Telegram.

    Проверяются доступность прокси и авторизация, но не конкретная сессия
    мимика: старт агента всё равно идёт своим путём.
    """
    proxy_type = ProxyType.SOCKS5 if config.protocol == "socks5" else ProxyType.HTTP
    proxy = Proxy(
        proxy_type=proxy_type,
        host=config.host,
        port=config.port,
        username=config.username,
        password=config.password.get_secret_value() if config.password is not None else None,
    )
    started = time.perf_counter()
    try:
        sock = await proxy.connect(
            dest_host=TELEGRAM_DC_HOST,
            dest_port=TELEGRAM_DC_PORT,
            timeout=timeout,
        )
    except Exception as exc:
        logger.info("Проверка прокси %s:%s не удалась", config.host, config.port)
        message = str(exc).strip() or type(exc).__name__
        return TelegramProxyCheckResult(ok=False, error=message)
    else:
        sock.close()
        latency_ms = max(0, round((time.perf_counter() - started) * 1000))
        return TelegramProxyCheckResult(ok=True, latency_ms=latency_ms)
