"""Вспомогательные операции синхронных живых браузерных тестов."""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import cast

from tests.real_tg.backend.helpers import jwt


def fetch_token() -> str:
    """pytest держит event loop и во время синхронного Playwright-теста."""

    async def fetch() -> str:
        return await asyncio.wait_for(jwt(), timeout=60)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return cast(str, pool.submit(asyncio.run, fetch()).result())
