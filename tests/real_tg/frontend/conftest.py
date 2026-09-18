"""Настоящий бэкенд + фронт для real_tg фронт-слоя. Маркер real_tg.

Отличия от backend-слоя: приложение поднимается отдельным процессом
(mimic42.main:app), фронт — bun dev, а Telegram-клиент проверяющего живёт
в синхронной обёртке SyncChecker (pytest-playwright не терпит чужой луп).
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv
from playwright.sync_api import Browser

from mimic42.testing.real_tg import TEST_ACCOUNT_USER_ID
from mimic42.testing.real_tg.checker import SyncChecker
from tests.real_tg.backend.helpers import agent_id_for_phone, anon_key, jwt

ROOT = Path(__file__).resolve().parents[3]
AUTH_DIR = ROOT / "tests" / "e2e" / ".auth"
API_PORT = int(os.environ.get("E2E_API_PORT", "8000"))
APP_PORT = int(os.environ.get("E2E_APP_PORT", "3000"))
API_URL = f"http://127.0.0.1:{API_PORT}"
APP_URL = f"http://127.0.0.1:{APP_PORT}"
ACTION_TIMEOUT_MS = 15_000
# Боевые переменные поверх тестовых переопределений (.env.test).
load_dotenv(ROOT / ".env", override=True)

from playwright.sync_api import expect  # noqa: E402

expect.set_options(timeout=15_000)


def _wait_for(url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(2)
    raise RuntimeError(f"{url} не поднялся за {timeout}с")


@pytest.fixture(scope="session")
def real_servers() -> Iterator[None]:
    """Настоящий mimic42.main:app + фронт (dev)."""
    env = os.environ.copy()
    api_proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "mimic42.main:app", "--port", str(API_PORT)],
        cwd=ROOT,
    )
    try:
        _wait_for(f"{API_URL}/health", timeout=90)

        front_env = {
            **env,
            "NEXT_PUBLIC_SUPABASE_URL": env["SUPABASE_URL"],
            "NEXT_PUBLIC_SUPABASE_ANON_KEY": anon_key(),
            "NEXT_PUBLIC_API_BASE_URL": API_URL,
            "PORT": str(APP_PORT),
        }
        web_proc = subprocess.Popen(["bun", "run", "dev"], cwd=ROOT / "frontend", env=front_env)
        try:
            _wait_for(APP_URL, timeout=180)
            yield
        finally:
            web_proc.terminate()
            web_proc.wait(timeout=30)
    finally:
        api_proc.terminate()
        api_proc.wait(timeout=30)


@pytest.fixture(scope="session")
def sync_checker() -> Iterator[SyncChecker]:
    instance = SyncChecker(
        api_id=int(os.environ["TG_CHECKER_API_ID"]),
        api_hash=os.environ["TG_CHECKER_API_HASH"],
        session_string=os.environ["TG_CHECKER_SESSION"],
    )
    instance.start()
    yield instance
    instance.stop()


@pytest.fixture(scope="session")
def mimic_agents(real_servers: None, sync_checker: SyncChecker) -> list[tuple[str, str]]:
    """Запускает мимиков через настоящий API; [(agent_id, phone)] из Dev-базы."""
    dsn = os.environ["DATABASE_CONNECTION_STRING"]
    phones = sync_checker.mimic_phones(dsn, TEST_ACCOUNT_USER_ID)

    async def start_all() -> list[tuple[str, str]]:
        token = await jwt()
        agents: list[tuple[str, str]] = []
        async with httpx.AsyncClient(base_url=API_URL, timeout=60.0) as client:
            for phone in phones:
                agent_id = await agent_id_for_phone(dsn, phone, TEST_ACCOUNT_USER_ID)
                response = await client.post(
                    f"/api/v1/agents/{agent_id}/start",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert response.status_code == 204, response.text
                agents.append((agent_id, phone))
        return agents

    return asyncio.run(start_all())


@pytest.fixture(scope="session")
def real_auth(browser: Browser, real_servers: None) -> str:
    state_path = AUTH_DIR / "real_tg.json"
    if state_path.exists():
        return str(state_path)
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    context = browser.new_context(base_url=APP_URL)
    context.set_default_timeout(ACTION_TIMEOUT_MS)
    page = context.new_page()
    page.goto("/login")
    page.get_by_label("Email").fill(os.environ["TEST_ACCOUNT_EMAIL"])
    page.get_by_label("Пароль", exact=True).fill(os.environ["TEST_ACCOUNT_PASSWORD"])
    page.get_by_role("button", name="Войти").click()
    # У аккаунта есть агенты-мимики, но состояние зависит от прогона: логин
    # может упасть и на дашборд, и на онбординг (если агентов ещё нет).
    page.wait_for_url(re.compile(r"/(dashboard|onboarding)"), timeout=60_000)
    context.storage_state(path=str(state_path))
    context.close()
    return str(state_path)
