"""Онборд нового мимика с настоящим входом. Только вручную, локально:

    TG_ONBOARD_PHONE=+7... uv run pytest tests/real_tg/frontend/test_real_onboarding.py -m real_tg

Код из SMS положи в REAL_TG_CODE_FILE, пароль 2FA (если есть) — в
REAL_TG_PASSWORD_FILE. Без TG_ONBOARD_PHONE тест скипается.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import asyncpg
import pytest
from playwright.sync_api import Browser, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from mimic42.testing.real_tg import REAL_TG_USER_ID
from mimic42.testing.slots import plain_dsn
from tests.real_tg.frontend.conftest import ACTION_TIMEOUT_MS, APP_URL

pytestmark = pytest.mark.real_tg


def _read_when_ready(path_value: str, timeout: float = 600.0) -> str:
    path = Path(path_value)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            content = path.read_text().strip()
            if content:
                return content
        except FileNotFoundError:
            pass
        time.sleep(2)
    raise TimeoutError(f"Код не появился в {path} за {timeout}с")


async def _load_agents() -> set[tuple[str, str]]:
    conn = await asyncpg.connect(plain_dsn(os.environ["DATABASE_CONNECTION_STRING"]))
    try:
        rows = await conn.fetch(
            """
            select a.id::text as agent_id, ts.authorization_status
            from agents a join telegram_sessions ts on ts.agent_id = a.id
            where a.owner_id = $1
            """,
            REAL_TG_USER_ID,
        )
    finally:
        await conn.close()
    return {(row["agent_id"], row["authorization_status"]) for row in rows}


@pytest.mark.skipif(os.environ.get("TG_ONBOARD_PHONE") is None, reason="TG_ONBOARD_PHONE не задан")
def test_real_onboarding_new_mimic(
    browser: Browser,
    real_servers: None,
    real_auth: str,
) -> None:
    phone = os.environ["TG_ONBOARD_PHONE"]
    # Первый прогон заводит самого первого мимика: снимок из базы, а не
    # фикстура mimic_agents (та требует уже заведённых мимиков).
    agents_before = {agent_id for agent_id, _ in asyncio.run(_load_agents())}

    context = browser.new_context(base_url=APP_URL, storage_state=real_auth)
    context.set_default_timeout(ACTION_TIMEOUT_MS)
    page = context.new_page()
    try:
        page.goto("/onboarding")
        page.get_by_label("Имя агента").fill("Мимик реальный")
        page.get_by_role("button", name="Продолжить →").click()
        page.get_by_label("SOUL.md").fill("спокойный помощник, отвечает коротко")
        page.get_by_role("button", name="Продолжить →").click()
        page.get_by_label("Номер телефона").fill(phone)
        page.get_by_role("button", name="Получить код →").click()
        expect(page.get_by_role("heading", name="Код из Telegram")).to_be_visible(timeout=60_000)

        code = _read_when_ready(os.environ["REAL_TG_CODE_FILE"])
        page.get_by_label("Код подтверждения").fill(code)
        page.get_by_role("button", name="Подтвердить →").click()

        twofa_heading = page.get_by_role("heading", name="Двухфакторная аутентификация")
        try:
            twofa_heading.wait_for(timeout=15_000)
        except PlaywrightTimeoutError:
            twofa_heading = None
        if twofa_heading is not None:
            password = _read_when_ready(os.environ.get("REAL_TG_PASSWORD_FILE", ""), timeout=120)
            page.get_by_label("Пароль 2FA").fill(password)
            page.get_by_role("button", name="Подтвердить →").click()

        expect(page.get_by_role("heading", name="Всё готово!")).to_be_visible(timeout=30_000)
        page.get_by_role("button", name="Создать агента").click()
        page.wait_for_url("**/dashboard", timeout=30_000)

        # Новый агент появился, его сессия авторизована: проверка по базе.
        rows = asyncio.run(_load_agents())
        new_agents = {agent_id for agent_id, _ in rows} - agents_before
        assert new_agents, "Новый агент не появился"
        statuses = {status for agent_id, status in rows if agent_id in new_agents}
        assert statuses == {"authorized"}
    finally:
        context.close()
