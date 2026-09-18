"""e2e-фикстуры: слот учёток, тестовый сервер, фронт, браузерные состояния.

Порт связки frontend/e2e/global-setup.ts + global-teardown.ts + auth.setup.ts
на pytest. Слот один на весь прогон; состояние авторизации каждой персоны
сохраняется в tests/e2e/.auth/<key>.json и переиспользуется тестами.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from mimic42.testing.env import load_test_env
from mimic42.testing.slots import assert_test_project

ROOT = Path(__file__).resolve().parents[2]
load_test_env()

from tests.e2e.helpers import (  # noqa: E402
    API_URL,
    APP_URL,
    AUTH_DIR,
    E2EUser,
    create_test_agent,
    login_via_form,
    reset_backend,
    users_from_slot_description,
)
from tests.servers import assert_port_free, spawn, terminate  # noqa: E402

# Как в playwright.config.ts: dev-сервер компилирует маршруты по требованию,
# поэтому веб-first проверки ждут 15 секунд, а не дефолтные 5.
expect.set_options(timeout=15_000)

API_PORT = int(os.environ.get("E2E_API_PORT", "8000"))
ACTION_TIMEOUT_MS = 15_000
# Dev-сервер компилирует маршруты по требованию: первая навигация бывает
# заметно дольше 15 секунд.
NAVIGATION_TIMEOUT_MS = 60_000
# Как у Playwright APIRequestContext: первый старт агента может тянуть
# холодные импорты LangChain, поэтому дефолтных 5 секунд httpx мало.
HTTP_TIMEOUT_SECONDS = 30.0


def _new_context(browser: Browser, *, storage_state: str | None = None) -> BrowserContext:
    context = browser.new_context(base_url=APP_URL, storage_state=storage_state)
    context.set_default_timeout(ACTION_TIMEOUT_MS)
    context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
    return context


def _slot_cli(args: list[str]) -> dict[str, object]:
    result = subprocess.run(
        ["uv", "run", "python", "-m", "mimic42.testing.slot_cli", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    # release не печатает ничего — это не повод падать.
    if not result.stdout.strip():
        return {}
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, dict)
    return parsed


def _wait_for(url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    raise RuntimeError(f"{url} не поднялся за {timeout}с")


@pytest.fixture(scope="session")
def slot_info() -> Iterator[tuple[str, str, dict[str, E2EUser]]]:
    """Арендует слот на весь прогон; персоны — фиксированные учётки Dev."""
    acquired = _slot_cli(["acquire"])
    slot, holder = str(acquired["slot"]), str(acquired["holder"])
    try:
        description = _slot_cli(["describe", slot])
        users = users_from_slot_description(description)
    except Exception:
        _slot_cli(["release", slot, holder])
        raise
    yield slot, holder, users
    _slot_cli(["release", slot, holder])


@pytest.fixture(scope="session")
def users(slot_info: tuple[str, str, dict[str, E2EUser]]) -> dict[str, E2EUser]:
    return slot_info[2]


def _anon_key(env: dict[str, str]) -> str:
    value = env.get("SUPABASE_ANON_KEY") or env.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    if value:
        return value
    env_local = ROOT / "frontend" / ".env.local"
    if env_local.exists():
        for line in env_local.read_text().splitlines():
            if line.startswith("NEXT_PUBLIC_SUPABASE_ANON_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("NEXT_PUBLIC_SUPABASE_ANON_KEY не найден")


@pytest.fixture(scope="session")
def servers() -> Iterator[None]:
    """Поднимает тестовый сервер и фронт; в CI фронт — прод-сборка."""
    assert_port_free(API_PORT)
    assert_port_free(int(os.environ.get("E2E_APP_PORT", "3000")))
    env = os.environ.copy()
    # CORS тестового сервера должен знать фактический порт фронта (его можно
    # переопределить через E2E_APP_PORT, если 3000 занят).
    app_port = int(os.environ.get("E2E_APP_PORT", "3000"))
    env["CORS_ALLOW_ORIGINS"] = f"http://127.0.0.1:{app_port},http://localhost:{app_port}"
    assert_test_project(env["SUPABASE_URL"], env["DATABASE_CONNECTION_STRING"])

    api_proc = spawn(
        ["uv", "run", "uvicorn", "mimic42.testing.server:app", "--port", str(API_PORT)],
        cwd=ROOT,
        env=env,
    )
    try:
        _wait_for(f"{API_URL}/health", timeout=60)

        front_env = {
            **env,
            "NEXT_PUBLIC_SUPABASE_URL": env["SUPABASE_URL"],
            "NEXT_PUBLIC_SUPABASE_ANON_KEY": _anon_key(env),
            "NEXT_PUBLIC_API_BASE_URL": API_URL,
            "PORT": str(int(os.environ.get("E2E_APP_PORT", "3000"))),
        }
        if os.environ.get("CI"):
            build = subprocess.run(["bun", "run", "build"], cwd=ROOT / "frontend", env=front_env)
            if build.returncode != 0:
                raise RuntimeError("bun run build упал")
            app_command = ["bun", "run", "start"]
        else:
            app_command = ["bun", "run", "dev"]
        web_proc = spawn(app_command, cwd=ROOT / "frontend", env=front_env)
        try:
            _wait_for(APP_URL, timeout=180)
            yield
        finally:
            terminate(web_proc)
    finally:
        terminate(api_proc)


@pytest.fixture(scope="session")
def auth_states(
    browser: Browser,
    servers: None,
    slot_info: tuple[str, str, dict[str, E2EUser]],
) -> dict[str, str]:
    """Reset бэкенда, базовый агент для full, логин каждой персоны через UI."""
    slot, _, users_map = slot_info
    with httpx.Client(base_url=API_URL, timeout=HTTP_TIMEOUT_SECONDS) as api:
        reset_backend(api, slot)
        full = users_map["full"]
        create_test_agent(api, full.id, "Бегущий", "running")
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    states: dict[str, str] = {}
    for key, user in users_map.items():
        context = _new_context(browser)
        page = context.new_page()
        try:
            login_via_form(page, user)
            page.wait_for_url("**/dashboard" if key == "full" else "**/onboarding", timeout=30_000)
            context.storage_state(path=str(user.state_file))
            states[key] = str(user.state_file)
        finally:
            context.close()
    return states


@pytest.fixture
def page(browser: Browser, servers: None) -> Iterator[Page]:
    """Чистая страница без storage state (unauth-сценарии)."""
    context = _new_context(browser)
    try:
        yield context.new_page()
    finally:
        context.close()


@pytest.fixture
def persona_page(browser: Browser, auth_states: dict[str, str]) -> Iterator[Callable[..., Page]]:
    """Фабрика: persona_page('full', fresh=True) — контекст без storage state."""
    contexts: list[BrowserContext] = []

    def _page(key: str, *, fresh: bool = False) -> Page:
        state = None if fresh else auth_states.get(key)
        context = _new_context(browser, storage_state=state)
        contexts.append(context)
        return context.new_page()

    yield _page
    for context in contexts:
        context.close()


@pytest.fixture
def api() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=API_URL, timeout=HTTP_TIMEOUT_SECONDS) as client:
        yield client


@pytest.fixture
def page_twofa(persona_page: Callable[..., Page]) -> Page:
    return persona_page("twofa")


@pytest.fixture
def page_code(persona_page: Callable[..., Page]) -> Page:
    return persona_page("code")
