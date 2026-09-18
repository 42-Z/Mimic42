# Real Telegram Tests & Python E2E — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Тесты Mimic в настоящем Telegram (проверяющий-аккаунт, два мимика, локально + CI по ручному запуску), полный перевод e2e с Playwright/TS на pytest-playwright/Python и устранение файлового fallback'а сессий Telethon.

**Architecture:** Python-модуль `src/mimic42/testing/real_tg/` (проверяющий на Telethon StringSession + скрипт входа) переиспользуется бэкенд-слоем (`tests/real_tg/backend/`, настоящий app in-process) и фронт-слоем (`tests/real_tg/frontend/`, pytest-playwright против настоящего uvicorn). Существующий TS-e2e переписывается на pytest-playwright (`tests/e2e/`, маркер `e2e`) с тем же слотом учёток и `/__test__`-заглушками. Файловая ветка Telethon-сессий удаляется: конфиг без session string падает с `TelegramAuthorizationRequired`.

**Tech Stack:** Python 3.13, pytest (+ pytest-asyncio, pytest-playwright), Telethon 1.43.2 (StringSession, events.NewMessage), httpx, asyncpg, uv; фронт остаётся на Bun.

**Спека:** `docs/superpowers/specs/2026-09-17-real-telegram-tests-design.md`

**Документация (читать перед задачами):** Telethon — https://docs.telethon.dev/en/stable/: «Session Files» (StringSession), «Entities» (телефон только из контактов), client reference (`send_message`, `get_messages`, `is_user_authorized`), «Update Events» (`NewMessage(chats, incoming, outgoing, from_users, pattern, func)`), modules/custom (`Conversation`), FAQ (луп не меняется после connect; сессия не делится между процессами; `event.get_chat()` вместо свойств); tl.telethon.dev → contacts.import_contacts (`InputPhoneContact`). Правила проекта: `AGENTS.md` в корне и `~/.config/opencode/AGENTS.md`.

---

## Карта файлов

| Ответственность | Файлы |
|---|---|
| Строгий клиент без файловых сессий | `src/mimic42/integrations/telethon_client.py`, `src/mimic42/core/agent_runtime.py` |
| Контракт API | `src/mimic42/api/app.py`, `tests/api/test_agents_api.py`, `tests/api/test_auth_api.py` |
| Конструкторы конфига без session_name | `src/mimic42/core/onboarding.py`, `src/mimic42/core/agent_store.py`, `src/mimic42/integrations/database_agent_store.py` + 10 тестовых файлов |
| e2e (Python) | `tests/e2e/conftest.py`, `tests/e2e/helpers.py`, `tests/e2e/test_*.py` |
| Проверяющий | `src/mimic42/testing/real_tg/checker.py`, `login.py`, `__init__.py` |
| Реальные тесты | `tests/real_tg/backend/*`, `tests/real_tg/frontend/*` |
| Скрипт настройки | `scripts/test_env_bootstrap.py` (сайт-аккаунт — `ensure_real_tg_account`) |
| CI | `.github/workflows/ci.yml`, `.github/workflows/real-tg.yml` |
| Конфиги | `pyproject.toml`, `.env.example`, `.gitignore`, `frontend/package.json` |
| Удаление | `frontend/e2e/`, `frontend/playwright.config.ts`, `PLAN.md`, корневые `*.session`, `sessions/` |

---

## Часть A — файловые сессии

### Task A1: build_telegram_client без fallback

**Files:**
- Test: `tests/integrations/test_telethon_client.py` (новый)
- Modify: `src/mimic42/integrations/telethon_client.py`

- [ ] **Step 1: напиши падающий тест**

Создай `tests/integrations/test_telethon_client.py`:

```python
from __future__ import annotations

from uuid import uuid4

import pytest
from telethon.sessions import StringSession

from mimic42.core.agent_runtime import AgentRuntimeConfig, TelegramAuthorizationRequired
from mimic42.integrations.telethon_client import build_telegram_client


def _config(session_string: str | None) -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_api_id=12345,
        telegram_api_hash="hash",
        telegram_session_string=session_string,
        system_prompt="system",
        soul_prompt="soul",
    )


def test_missing_session_string_raises_before_creating_client() -> None:
    with pytest.raises(TelegramAuthorizationRequired):
        build_telegram_client(_config(None))


def test_empty_session_string_raises_before_creating_client() -> None:
    with pytest.raises(TelegramAuthorizationRequired):
        build_telegram_client(_config(""))


def test_string_session_used_when_present() -> None:
    client = build_telegram_client(_config("test-session-payload"))
    assert isinstance(client.session, StringSession)
```

- [ ] **Step 2: убедись, что тест падает**

Run: `uv run pytest tests/integrations/test_telethon_client.py -q`
Expected: FAIL — сейчас fallback строит файловый клиент без ошибки.

- [ ] **Step 3: перепиши telethon_client.py**

Замени содержимое `src/mimic42/integrations/telethon_client.py`:

```python
from __future__ import annotations

from typing import Any, cast

from telethon import TelegramClient
from telethon.sessions import StringSession

from mimic42.core.agent_runtime import AgentRuntimeConfig, TelegramAuthorizationRequired


def build_telegram_client(config: AgentRuntimeConfig) -> TelegramClient:
    if not config.telegram_session_string:
        raise TelegramAuthorizationRequired(
            f"Agent {config.agent_id} has no stored Telegram session string — "
            "complete onboarding first"
        )
    client = TelegramClient(
        StringSession(config.telegram_session_string),
        config.telegram_api_id,
        config.telegram_api_hash,
    )

    from mimic42.integrations.telegram_tools import CustomMarkdown

    client.parse_mode = cast(Any, CustomMarkdown())
    return client
```

Из доков Telethon: строка в `TelegramClient(StringSession(...))` — единственный путь без файлов; передача строки-пути создаёт `*.session` в CWD — она больше не допускается.

- [ ] **Step 4: прогони**

Run: `uv run pytest tests/integrations/test_telethon_client.py -q`
Expected: 3 passed. Затем `ls *.session` — счётчик файлов не изменился (клиент больше не создаёт файлов).

- [ ] **Step 5: commit**

```bash
git add src/mimic42/integrations/telethon_client.py tests/integrations/test_telethon_client.py
git commit -m "feat: telegram client requires a stored session string"
```

### Task A2: убрать поле telegram_session_name из AgentRuntimeConfig

**Files:**
- Modify: `src/mimic42/core/agent_runtime.py` (строка 41), `src/mimic42/core/onboarding.py:301`, `src/mimic42/core/agent_store.py:170`, `src/mimic42/integrations/database_agent_store.py:116`
- Modify: `tests/integrations/test_langchain_agent.py:17`, `tests/integrations/test_telegram_tools.py:802`, `tests/core/test_agent_manager_restore.py:19`, `tests/core/test_agent_manager_concurrency.py:19`, `tests/core/test_agent_manager_remove.py:19`, `tests/core/test_agent_manager_reload.py:22`, `tests/core/test_agent_manager_reload_error.py:22`, `tests/core/test_agent_runtime.py:110,932`, `tests/integration/test_activity.py:27`, `tests/testing/test_scripted_llm.py:23`

- [ ] **Step 1: удали поле из конфига**

В `src/mimic42/core/agent_runtime.py` удали строку:

```python
    telegram_session_name: str = Field(min_length=1)
```

- [ ] **Step 2: убери передачу поля из всех конструкторов**

Удали строки вида (в `src/mimic42/core/onboarding.py:301` это `telegram_session_name=session.onboarding_id.hex,`; в тестах — литералы):

```python
            telegram_session_name=session.onboarding_id.hex,
```
```python
            telegram_session_name=agent_id.hex,
```
```python
            telegram_session_name="sess",
```
```python
        telegram_session_name="test_session",
```
```python
        telegram_session_name="test-session",
```
```python
        telegram_session_name="test",
```

- [ ] **Step 3: проверь полноту и прогони затронутые наборы**

Run: `grep -rn "telegram_session_name" src tests` (инструментом Grep, не bash) — остаются только `src/mimic42/api/app.py` и `tests/api/*` (Task A3).
Run: `uv run pytest tests/core tests/integrations tests/testing -m "not db" -q`
Expected: зелёные.

- [ ] **Step 4: commit**

```bash
git add -u
git commit -m "refactor: drop telegram_session_name from runtime config"
```

### Task A3: контракт POST /api/v1/agents — session string вместо имени файла

**Files:**
- Modify: `src/mimic42/api/app.py:97-122`
- Modify: `tests/api/test_agents_api.py:47,93`, `tests/api/test_auth_api.py:101`

- [ ] **Step 1: замени поле в CreateAgentRequest**

В `src/mimic42/api/app.py`:

```python
class CreateAgentRequest(BaseModel):
    agent_id: UUID = Field(default_factory=uuid4)
    telegram_session_string: str | None = Field(default=None, min_length=1)
    telegram_api_id: int | None = Field(default=None, gt=0)
    telegram_api_hash: str | None = Field(default=None, min_length=1)
    soul_prompt: str = Field(default="", max_length=20_000)
    auto_start: bool = False

    def to_runtime_config(
        self,
        *,
        owner_id: UUID,
        api_id: int,
        api_hash: str,
    ) -> AgentRuntimeConfig:
        from mimic42.core.onboarding import load_default_system_prompt

        return AgentRuntimeConfig(
            agent_id=self.agent_id,
            owner_id=owner_id,
            telegram_api_id=api_id,
            telegram_api_hash=api_hash,
            telegram_session_string=self.telegram_session_string,
            system_prompt=load_default_system_prompt(),
            soul_prompt=self.soul_prompt,
        )
```

- [ ] **Step 2: обнови тесты API**

В `tests/api/test_agents_api.py` (строки 47 и 93) и `tests/api/test_auth_api.py:101` замени:

```python
                "telegram_session_name": "sessions/api-agent",
```

на:

```python
                "telegram_session_string": "1BQANOTEuMTA4LjUuMLB6LjE",
```

- [ ] **Step 3: проверь полноту и прогони**

Run: Grep `telegram_session_name` по `src tests` → 0 совпадений.
Run: `uv run pytest tests/api -m "not db" -q` → passed.

- [ ] **Step 4: commit**

```bash
git add -u
git commit -m "feat: agents API accepts telegram_session_string"
```

### Task A4: удалить мусорные файлы и PLAN.md

- [ ] **Step 1: удали**

Run: `rm -f ./*.session && rm -rf ./sessions && rm -f PLAN.md`

- [ ] **Step 2: проверь**

Run: `git status --short`
Expected: пусто (файлы были вне гита). Если не пусто — остановись и разберись.

### Task A5: регресс

- [ ] Run: `uv run pytest -m "not db" -q` → passed
- [ ] Run: `uv run pytest -m db -q` (env из .env/.env.test) → passed
- [ ] Run: `ls *.session` → пусто после прогонов

---

## Часть B — e2e на Python

### Task B1: зависимости и маркеры

- [ ] **Step 1:** Run: `uv add --group dev playwright pytest-playwright`
- [ ] **Step 2:** Run: `uv run playwright install --with-deps chromium`
- [ ] **Step 3: маркеры.** В `pyproject.toml` замени блок pytest-конфига:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
testpaths = ["tests"]
# Тесты против настоящей базы по умолчанию исключены. e2e поднимает серверы
# и браузер, real_tg требует настоящих Telegram-аккаунтов — оба слоя
# запускаются явно.
addopts = ["-m", "not db and not e2e and not real_tg"]
markers = [
    "db: требует подключения к тестовой базе Mimic42 Dev",
    "e2e: поднимает тестовый сервер и фронт, гоняет браузерные сценарии",
    "real_tg: требует настоящих Telegram-аккаунтов, сети и секретов",
]
```

- [ ] **Step 4: commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add pytest-playwright and e2e/real_tg markers"
```

### Task B2: tests/e2e/helpers.py — порт helpers.ts

**Files:**
- Create: `tests/e2e/helpers.py`
- Modify: `.gitignore`

- [ ] **Step 1: создай helpers.py**

```python
"""HTTP-помощники e2e: порт frontend/e2e/helpers.ts на httpx."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from playwright.sync_api import Page

from mimic42.testing.env import load_test_env

ROOT = Path(__file__).resolve().parents[2]
load_test_env()

API_PORT = int(os.environ.get("E2E_API_PORT", "8000"))
APP_PORT = int(os.environ.get("E2E_APP_PORT", "3000"))
API_URL = f"http://127.0.0.1:{API_PORT}"
APP_URL = f"http://127.0.0.1:{APP_PORT}"
AUTH_DIR = Path(__file__).parent / ".auth"


def _post(api: httpx.Client, path: str, payload: dict[str, object]) -> dict[str, object]:
    response = api.post(path, json=payload)
    response.raise_for_status()
    return response.json() if response.content else {}


class E2EUser:
    def __init__(self, key: str, user_id: str, email: str, password: str) -> None:
        self.key = key
        self.id = user_id
        self.email = email
        self.password = password
        self.state_file = AUTH_DIR / f"{key}.json"


def users_from_slot_description(description: dict[str, object]) -> dict[str, E2EUser]:
    password = os.environ["TEST_USER_PASSWORD"]
    personas = description["personas"]
    assert isinstance(personas, list)
    return {
        persona["key"]: E2EUser(persona["key"], persona["id"], persona["email"], password)
        for persona in personas
    }


def reset_backend(api: httpx.Client, slot: str) -> None:
    _post(api, "/__test__/reset", {"slot": slot})


def create_test_agent(
    api: httpx.Client,
    owner_id: str,
    name: str,
    state: str = "stopped",
    phone_number: str | None = None,
    with_telegram_session: bool = True,
) -> str:
    result = _post(
        api,
        "/__test__/agents",
        {
            "owner_id": owner_id,
            "name": name,
            "state": state,
            "phone_number": phone_number,
            "with_telegram_session": with_telegram_session,
        },
    )
    return str(result["agent_id"])


def deliver_message(api: httpx.Client, agent_id: str, chat_id: int, text: str) -> None:
    _post(api, f"/__test__/telegram/{agent_id}/deliver", {"chat_id": chat_id, "text": text})


def script_agent_reply(api: httpx.Client, agent_id: str, text: str) -> None:
    _post(api, f"/__test__/agents/{agent_id}/script", {"text": text})


def record_agent_event(api: httpx.Client, agent_id: str, event: dict[str, object]) -> None:
    _post(api, f"/__test__/agents/{agent_id}/events", event)


def script_onboarding_login(
    api: httpx.Client, code: str | None, password: str | None = None
) -> None:
    _post(api, "/__test__/telegram/onboarding/script", {"code": code, "password": password})


def reset_onboarding_login(api: httpx.Client) -> None:
    _post(api, "/__test__/telegram/onboarding/reset", {})


def hide_onboarding_drafts(api: httpx.Client, owner_id: str) -> None:
    _post(api, "/__test__/onboarding/drafts/hide", {"owner_id": owner_id})


def current_draft_id(api: httpx.Client, owner_id: str) -> str:
    response = api.get("/__test__/onboarding/drafts/current", params={"owner_id": owner_id})
    response.raise_for_status()
    draft_id = response.json()["id"]
    assert draft_id, f"Нет черновика онбординга для owner_id={owner_id}"
    return str(draft_id)


def login_via_form(page: Page, user: E2EUser) -> None:
    page.goto("/login")
    page.get_by_label("Email").fill(user.email)
    page.get_by_label("Пароль", exact=True).fill(user.password)
    page.get_by_role("button", name="Войти").click()
```

- [ ] **Step 2: в `.gitignore` рядом с `frontend/e2e/.auth/` добавь:**

```
tests/e2e/.auth/
```

- [ ] **Step 3: commit**

```bash
git add tests/e2e/helpers.py .gitignore
git commit -m "feat: python e2e helpers"
```

### Task B3: tests/e2e/conftest.py — слот, серверы, авторизация

**Files:**
- Create: `tests/e2e/conftest.py` (единый файл, целиком как ниже)

- [ ] **Step 1: создай conftest.py**

```python
"""e2e-фикстуры: слот учёток, тестовый сервер, фронт, браузерные состояния."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from playwright.sync_api import Browser, BrowserContext, Page

from mimic42.testing.env import load_test_env
from mimic42.testing.slots import assert_test_project

ROOT = Path(__file__).resolve().parents[2]
load_test_env()

from tests.e2e.helpers import (  # noqa: E402
    APP_PORT,
    APP_URL,
    API_URL,
    AUTH_DIR,
    E2EUser,
    create_test_agent,
    login_via_form,
    reset_backend,
    users_from_slot_description,
)

API_PORT = int(os.environ.get("E2E_API_PORT", "8000"))


def _slot_cli(args: list[str]) -> dict[str, str]:
    result = subprocess.run(
        ["uv", "run", "python", "-m", "mimic42.testing.slot_cli", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


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
    """Арендует слот на весь прогон; персоналы — фиксированные учётки Dev."""
    acquired = _slot_cli(["acquire"])
    slot, holder = acquired["slot"], acquired["holder"]
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
    env = os.environ.copy()
    assert_test_project(env["SUPABASE_URL"], env["DATABASE_CONNECTION_STRING"])

    api_proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "mimic42.testing.server:app", "--port", str(API_PORT)],
        cwd=ROOT,
    )
    _wait_for(f"{API_URL}/health", timeout=60)

    front_env = {
        **env,
        "NEXT_PUBLIC_SUPABASE_URL": env["SUPABASE_URL"],
        "NEXT_PUBLIC_SUPABASE_ANON_KEY": _anon_key(env),
        "NEXT_PUBLIC_API_BASE_URL": API_URL,
        "PORT": str(APP_PORT),
    }
    if os.environ.get("CI"):
        build = subprocess.run(["bun", "run", "build"], cwd=ROOT / "frontend", env=front_env)
        if build.returncode != 0:
            api_proc.terminate()
            raise RuntimeError("bun run build упал")
        app_command = ["bun", "run", "start"]
    else:
        app_command = ["bun", "run", "dev"]
    web_proc = subprocess.Popen(app_command, cwd=ROOT / "frontend", env=front_env)
    try:
        _wait_for(APP_URL, timeout=180)
        yield
    finally:
        web_proc.terminate()
        api_proc.terminate()
        web_proc.wait(timeout=30)
        api_proc.wait(timeout=30)


@pytest.fixture(scope="session")
def auth_states(
    browser: Browser,
    servers: None,
    slot_info: tuple[str, str, dict[str, E2EUser]],
) -> dict[str, str]:
    """Reset бэкенда, базовый агент для full, логин каждой персоны через UI."""
    slot, _, users_map = slot_info
    with httpx.Client(base_url=API_URL) as api:
        reset_backend(api, slot)
        full = users_map["full"]
        create_test_agent(api, full.id, "Бегущий", "running")
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    states: dict[str, str] = {}
    for key, user in users_map.items():
        context = browser.new_context(base_url=APP_URL)
        page = context.new_page()
        login_via_form(page, user)
        page.wait_for_url("**/dashboard" if key == "full" else "**/onboarding", timeout=30_000)
        context.storage_state(path=str(user.state_file))
        context.close()
        states[key] = str(user.state_file)
    return states


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    """Чистая страница без storage state (unauth-сценарии)."""
    context = browser.new_context(base_url=APP_URL)
    yield context.new_page()
    context.close()


@pytest.fixture
def persona_page(
    browser: Browser, auth_states: dict[str, str]
) -> Iterator[Callable[[str, bool], Page]]:
    """Фабрика: persona_page('full', fresh=True) — контекст без storage state."""
    contexts: list[BrowserContext] = []

    def _page(key: str, *, fresh: bool = False) -> Page:
        state = None if fresh else auth_states.get(key)
        context = browser.new_context(base_url=APP_URL, storage_state=state)
        contexts.append(context)
        return context.new_page()

    yield _page
    for context in contexts:
        context.close()


@pytest.fixture
def api() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=API_URL) as client:
        yield client


@pytest.fixture
def page_twofa(persona_page: Callable[[str, bool], Page]) -> Page:
    return persona_page("twofa")


@pytest.fixture
def page_code(persona_page: Callable[[str, bool], Page]) -> Page:
    return persona_page("code")
```

- [ ] **Step 2: проверка сборки**

Run: `uv run pytest tests/e2e -m e2e --collect-only -q`
Expected: `0 tests collected`, без ошибок.

- [ ] **Step 3: commit**

```bash
git add tests/e2e/conftest.py
git commit -m "feat: python e2e fixtures for slot, servers and auth"
```

### Task B4: порт test_unauth.py

**Files:**
- Create: `tests/e2e/test_unauth.py`

- [ ] **Step 1: создай тест**

```python
"""Порт frontend/e2e/unauth.spec.ts."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def _url_is(page: Page, pattern: str) -> None:
    assert re.search(pattern, page.url), page.url


class TestRedirects:
    def test_dashboard_redirects_to_login(self, page: Page) -> None:
        page.goto("/dashboard")
        _url_is(page, r"/login\?redirect=%2Fdashboard")

    def test_root_redirects_to_login(self, page: Page) -> None:
        page.goto("/")
        _url_is(page, r"/login")

    def test_onboarding_redirects_to_login(self, page: Page) -> None:
        page.goto("/onboarding")
        _url_is(page, r"/login\?redirect=%2Fonboarding")

    def test_agent_page_redirects_to_login(self, page: Page) -> None:
        page.goto("/agent/some-agent")
        _url_is(page, r"/login\?redirect=")


class TestPublicPages:
    def test_login_renders(self, page: Page) -> None:
        page.goto("/login")
        expect(page.get_by_role("heading", name="Вход в систему")).to_be_visible()

    def test_register_renders(self, page: Page) -> None:
        page.goto("/register")
        expect(page.get_by_role("heading", name="Создать аккаунт")).to_be_visible()

    def test_reset_password_renders(self, page: Page) -> None:
        page.goto("/reset-password")
        expect(page.get_by_role("heading", name="Восстановление пароля")).to_be_visible()

    def test_login_to_register_and_back(self, page: Page) -> None:
        page.goto("/login")
        page.get_by_role("link", name="Зарегистрироваться").click()
        _url_is(page, r"/register")
        page.get_by_role("link", name="Войти").click()
        _url_is(page, r"/login")

    def test_login_to_reset_password_and_back(self, page: Page) -> None:
        page.goto("/login")
        page.get_by_role("link", name="Забыли пароль?").click()
        _url_is(page, r"/reset-password")
        page.get_by_role("link", name="Вернуться ко входу").click()
        _url_is(page, r"/login")

    def test_password_visibility_toggle(self, page: Page) -> None:
        page.goto("/login")
        password = page.get_by_label("Пароль", exact=True)
        expect(password).to_have_attribute("type", "password")
        page.get_by_role("button", name="Показать пароль").click()
        expect(password).to_have_attribute("type", "text")
        page.get_by_role("button", name="Скрыть пароль").click()
        expect(password).to_have_attribute("type", "password")

    def test_login_validation_errors(self, page: Page) -> None:
        page.goto("/login")
        page.get_by_role("button", name="Войти").click()
        expect(page.get_by_text("Введите корректный email")).to_be_visible()
        expect(page.get_by_text("Пароль обязателен")).to_be_visible()

    def test_register_mismatch_error(self, page: Page) -> None:
        page.goto("/register")
        page.get_by_label("Email").fill("user@example.com")
        page.get_by_label("Пароль", exact=True).fill("password123")
        page.get_by_label("Повторите пароль").fill("different123")
        page.get_by_role("button", name="Создать аккаунт").click()
        expect(page.get_by_text("Пароли не совпадают")).to_be_visible()

    def test_reset_password_email_validation(self, page: Page) -> None:
        page.goto("/reset-password")
        page.get_by_placeholder("Email").fill("not-an-email")
        page.get_by_role("button", name="Отправить ссылку").click()
        expect(page.get_by_text("Введите корректный email")).to_be_visible()

    def test_update_password_session_check(self, page: Page) -> None:
        page.goto("/update-password")
        expect(page.get_by_text("Проверка сессии...")).to_be_visible()
        expect(page.get_by_placeholder("Новый пароль")).to_have_count(0)

    def test_auth_callback_without_code(self, page: Page) -> None:
        page.goto("/api/auth/callback")
        _url_is(page, r"/login\?error=auth_callback_failed")


class TestSecurityHeaders:
    def test_login_headers_and_csp(self, page: Page) -> None:
        response = page.goto("/login")
        assert response.ok
        headers = response.headers
        assert headers["x-frame-options"] == "DENY"
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "default-src 'self'" in headers["content-security-policy"]
        assert "frame-ancestors" in headers["content-security-policy"]
```

- [ ] **Step 2: прогони**

Run: `uv run pytest tests/e2e/test_unauth.py -m e2e -q`
Expected: passed (серверы поднимутся).

- [ ] **Step 3: commit**

```bash
git add tests/e2e/test_unauth.py
git commit -m "feat: port unauth e2e spec to python"
```

### Task B5: порт test_auth.py

**Files:**
- Create: `tests/e2e/test_auth.py`

- [ ] **Step 1: создай тест**

```python
"""Порт frontend/e2e/auth.spec.ts."""

from __future__ import annotations

import httpx
import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import APP_URL, create_test_agent, login_via_form


@pytest.fixture
def full_page(persona_page: object, users: dict) -> object:
    return persona_page("full")


def seed_agents(api: httpx.Client, owner_id: str) -> tuple[str, str]:
    running = create_test_agent(api, owner_id, "Бегущий", "running")
    stopped = create_test_agent(api, owner_id, "Остановленный", "stopped")
    return running, stopped


class TestAuthenticatedNavigation:
    def test_login_redirects_authenticated_to_dashboard(
        self, full_page: object, api: httpx.Client, users: dict
    ) -> None:
        seed_agents(api, users["full"].id)
        full_page.goto("/login")
        full_page.wait_for_url("**/dashboard", timeout=15_000)
        expect(full_page.get_by_role("heading", name="Ваши агенты")).to_be_visible()

    def test_dashboard_lists_agents_with_kpis(
        self, full_page: object, api: httpx.Client, users: dict
    ) -> None:
        running, stopped = seed_agents(api, users["full"].id)
        full_page.goto("/dashboard")
        expect(full_page.get_by_role("heading", name="Ваши агенты")).to_be_visible()
        expect(full_page.get_by_test_id(f"agent-card-{running}")).to_be_visible()
        expect(full_page.get_by_test_id(f"agent-card-{stopped}")).to_be_visible()
        expect(full_page.get_by_test_id("kpi-card")).to_have_count(4)

    def test_start_stop_buttons_reflect_state(
        self, full_page: object, api: httpx.Client, users: dict
    ) -> None:
        running, stopped = seed_agents(api, users["full"].id)
        full_page.goto("/dashboard")
        running_card = full_page.get_by_test_id(f"agent-card-{running}")
        expect(running_card.get_by_role("button", name="Запустить")).to_be_disabled()
        expect(running_card.get_by_role("button", name="Стоп")).to_be_enabled()
        stopped_card = full_page.get_by_test_id(f"agent-card-{stopped}")
        expect(stopped_card.get_by_role("button", name="Запустить")).to_be_enabled()
        expect(stopped_card.get_by_role("button", name="Стоп")).to_be_disabled()


class TestSignOut:
    def test_logout_from_sidebar(self, browser: object, api: httpx.Client, users: dict) -> None:
        seed_agents(api, users["full"].id)
        context = browser.new_context(base_url=APP_URL)
        page = context.new_page()
        try:
            login_via_form(page, users["full"])
            page.wait_for_url("**/dashboard", timeout=15_000)
            page.get_by_role("button", name="Выйти").click()
            page.wait_for_url("**/login", timeout=15_000)
        finally:
            context.close()


class TestDashboardWithoutAgents:
    def test_forces_onboarding(self, browser: object, auth_states: dict[str, str]) -> None:
        context = browser.new_context(base_url=APP_URL, storage_state=auth_states["empty"])
        page = context.new_page()
        try:
            page.goto("/dashboard")
            page.wait_for_url("**/onboarding", timeout=15_000)
            expect(page.get_by_test_id("step-indicator")).to_be_visible()
        finally:
            context.close()


class TestFreshLoginWithRedirect:
    def test_login_lands_on_redirect_target(
        self, browser: object, api: httpx.Client, users: dict
    ) -> None:
        running = create_test_agent(api, users["full"].id, "Бегущий", "running")
        context = browser.new_context(base_url=APP_URL)
        page = context.new_page()
        try:
            page.goto("/dashboard")
            page.wait_for_url("**/login?redirect=%2Fdashboard", timeout=15_000)
            login_via_form(page, users["full"])
            page.wait_for_url("**/dashboard", timeout=15_000)
            expect(
                page.get_by_test_id(f"agent-card-{running}").get_by_text("Бегущий")
            ).to_be_visible()
        finally:
            context.close()
```

- [ ] **Step 2: прогони** `uv run pytest tests/e2e/test_auth.py -m e2e -q` → passed
- [ ] **Step 3: commit**

```bash
git add tests/e2e/test_auth.py
git commit -m "feat: port auth e2e spec to python"
```

### Task B6: порт test_onboarding.py

**Files:**
- Create: `tests/e2e/test_onboarding.py`

- [ ] **Step 1: создай тест**

```python
"""Порт frontend/e2e/onboarding.spec.ts: файл серийный, общий фейк входа.

По умолчанию pytest гоняет один процесс — серийность внутри файла
сохраняется (см. пояснение в TS-версии: общий onboarding-аккаунт).
"""

from __future__ import annotations

import time

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import (
    current_draft_id,
    hide_onboarding_drafts,
    reset_onboarding_login,
    script_onboarding_login,
)

pytestmark = pytest.mark.e2e

SOUL_TEXT = "0123456789性格テスト: спокойный помощник, отвечает коротко и по делу каждый день"


def _wait_code_cleared(page: object, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.evaluate("() => sessionStorage.getItem('_m42_tc_state')") is None:
            return
        time.sleep(0.5)
    raise AssertionError("Код остался в sessionStorage после авторизации")


def _walk_to_credentials(page: object, name: str, soul: str) -> None:
    page.goto("/onboarding")
    page.get_by_label("Имя агента").fill(name)
    page.get_by_role("button", name="Продолжить →").click()
    page.get_by_label("SOUL.md").fill(soul)
    page.get_by_role("button", name="Продолжить →").click()


class TestWholeFlow:
    def test_walks_the_whole_flow(self, page: object, api: object, users: dict) -> None:
        flow = users["flow"]
        reset_onboarding_login(api)
        script_onboarding_login(api, "12345")
        hide_onboarding_drafts(api, flow.id)

        page.goto("/onboarding")
        expect(page.get_by_role("heading", name="Как зовут вашего агента?")).to_be_visible()

        page.get_by_role("button", name="Продолжить →").click()
        expect(page.get_by_text("Имя агента обязательно")).to_be_visible()
        page.get_by_label("Имя агента").fill("Тест")
        page.get_by_role("button", name="Продолжить →").click()
        expect(page.get_by_role("heading", name="Характер агента")).to_be_visible()

        page.get_by_label("SOUL.md").fill("коротко")
        page.get_by_role("button", name="Продолжить →").click()
        expect(page.get_by_text("Характер должен содержать хотя бы 10 символов")).to_be_visible()
        page.get_by_label("SOUL.md").fill(SOUL_TEXT)
        page.get_by_role("button", name="Продолжить →").click()
        expect(page.get_by_role("heading", name="Подключение Telegram")).to_be_visible()

        draft_id = current_draft_id(api, flow.id)

        page.get_by_label("Номер телефона").fill("123")
        page.get_by_role("button", name="Получить код →").click()
        expect(page.get_by_text("Номер телефона должен быть в формате E.164")).to_be_visible()
        page.get_by_label("Номер телефона").fill("+79990000000")
        page.get_by_role("button", name="Получить код →").click()
        expect(page.get_by_role("heading", name="Код из Telegram")).to_be_visible()

        page.get_by_label("Код подтверждения").fill("12")
        page.get_by_role("button", name="Подтвердить →").click()
        expect(page.get_by_text("Код должен содержать минимум 5 цифр")).to_be_visible()
        page.get_by_label("Код подтверждения").fill("12345")
        page.get_by_role("button", name="Подтвердить →").click()
        expect(page.get_by_role("heading", name="Всё готово!")).to_be_visible()
        _wait_code_cleared(page)

        page.get_by_role("button", name="Создать агента").click()
        page.wait_for_url("**/dashboard", timeout=15_000)
        expect(page.get_by_test_id(f"agent-card-{draft_id}").get_by_text("Тест")).to_be_visible()


class TestTwoFA:
    def test_submits_password_and_clears_code(
        self, page_twofa: object, api: object, users: dict
    ) -> None:
        twofa = users["twofa"]
        reset_onboarding_login(api)
        hide_onboarding_drafts(api, twofa.id)
        script_onboarding_login(api, "12345", "secret2fa")

        _walk_to_credentials(page_twofa, "Тест 2FA", SOUL_TEXT)
        page_twofa.get_by_label("Номер телефона").fill("+79990000000")
        page_twofa.get_by_role("button", name="Получить код →").click()
        expect(page_twofa.get_by_role("heading", name="Код из Telegram")).to_be_visible()

        page_twofa.get_by_label("Код подтверждения").fill("12345")
        page_twofa.get_by_role("button", name="Подтвердить →").click()
        expect(
            page_twofa.get_by_role("heading", name="Двухфакторная аутентификация")
        ).to_be_visible()

        page_twofa.get_by_role("button", name="Подтвердить →").click()
        expect(page_twofa.get_by_text("2FA пароль обязателен")).to_be_visible()

        page_twofa.get_by_label("Пароль 2FA").fill("secret2fa")
        page_twofa.get_by_role("button", name="Подтвердить →").click()
        expect(page_twofa.get_by_role("heading", name="Всё готово!")).to_be_visible()
        _wait_code_cleared(page_twofa)


class TestStoredStep:
    def test_code_requested_draft_opens_code_step(
        self, page_code: object, api: object, users: dict
    ) -> None:
        code_user = users["code"]
        reset_onboarding_login(api)
        script_onboarding_login(api, "12345")
        hide_onboarding_drafts(api, code_user.id)

        _walk_to_credentials(page_code, "Тест возврата", SOUL_TEXT)
        page_code.get_by_label("Номер телефона").fill("+79990000000")
        page_code.get_by_role("button", name="Получить код →").click()
        expect(page_code.get_by_role("heading", name="Код из Telegram")).to_be_visible()

        page_code.reload()
        expect(page_code.get_by_role("heading", name="Код из Telegram")).to_be_visible()
        expect(page_code.get_by_test_id("onboarding-step-telegram_credentials")).to_be_visible()

        page_code.get_by_role("button", name="← Назад").click()
        expect(page_code.get_by_role("heading", name="Подключение Telegram")).to_be_visible()
```

- [ ] **Step 2: прогони** `uv run pytest tests/e2e/test_onboarding.py -m e2e -q` → passed
- [ ] **Step 3: commit**

```bash
git add tests/e2e/test_onboarding.py
git commit -m "feat: port onboarding e2e spec to python"
```

### Task B7: порт test_agent.py

**Files:**
- Create: `tests/e2e/test_agent.py`

- [ ] **Step 1: создай тест**

```python
"""Порт frontend/e2e/agent.spec.ts."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import (
    create_test_agent,
    deliver_message,
    record_agent_event,
    script_agent_reply,
)

PEER_CHAT_ID = 123


@pytest.fixture
def agent_page(persona_page: object) -> object:
    return persona_page("full")


def _new_agent(api: object, users: dict, name: str, state: str = "stopped", **kwargs: object) -> str:
    return create_test_agent(api, users["full"].id, name, state, **kwargs)


class TestAgentPage:
    def test_rejects_invalid_id(self, agent_page: object) -> None:
        agent_page.goto("/agent/!!!")
        expect(agent_page.get_by_text("Недопустимый ID агента")).to_be_visible()

    def test_tabs_switch_via_query(self, agent_page: object, api: object, users: dict) -> None:
        agent_id = _new_agent(api, users, "Вкладки", phone_number="+79990000001")
        agent_page.goto(f"/agent/{agent_id}")
        expect(agent_page.get_by_test_id("agent-tabs")).to_be_visible()

        agent_page.get_by_test_id("agent-tab-logs").click()
        expect(agent_page).to_have_url(re.compile(r"[?&]tab=logs"), timeout=15_000)
        expect(agent_page.get_by_test_id("log-filter-full")).to_be_visible()

        agent_page.get_by_test_id("agent-tab-memory").click()
        expect(agent_page).to_have_url(re.compile(r"[?&]tab=memory"), timeout=15_000)
        expect(agent_page.get_by_text("Память пуста")).to_be_visible()

        agent_page.get_by_test_id("agent-tab-telegram").click()
        expect(agent_page.get_by_text("+799******01")).to_be_visible()

    def test_log_filters_narrow_feed(self, agent_page: object, api: object, users: dict) -> None:
        agent_id = _new_agent(api, users, "Логи", "running")
        script_agent_reply(api, agent_id, "Здравствуйте!")
        deliver_message(api, agent_id, PEER_CHAT_ID, "Привет")
        record_agent_event(
            api,
            agent_id,
            {
                "event_type": "tool.send_text_message",
                "status": "succeeded",
                "payload": {"turn_id": "turn-ok", "peer": str(PEER_CHAT_ID)},
                "result": {"success": True},
            },
        )
        record_agent_event(
            api,
            agent_id,
            {
                "event_type": "tool.get_dialogs",
                "status": "failed",
                "payload": {"turn_id": "turn-fail", "peer": str(PEER_CHAT_ID)},
                "error": "FloodWait",
            },
        )
        agent_page.goto(f"/agent/{agent_id}?tab=logs")
        expect(agent_page.get_by_text("Здравствуйте!")).to_be_visible()
        expect(agent_page.get_by_text("Просмотрел список диалогов")).to_be_visible()

        agent_page.get_by_test_id("log-filter-chat").click()
        expect(agent_page.get_by_text("Просмотрел список диалогов")).to_have_count(0)

        agent_page.get_by_test_id("log-filter-full").click()
        expect(agent_page.get_by_text("Просмотрел список диалогов")).to_be_visible()

    def test_stop_confirm_dialog(self, agent_page: object, api: object, users: dict) -> None:
        agent_id = _new_agent(api, users, "Стоп", "running")
        agent_page.goto(f"/agent/{agent_id}?tab=actions")
        agent_page.get_by_role("button", name="Остановить", exact=True).first.click()
        dialog = agent_page.get_by_role("dialog")
        expect(dialog.get_by_text("Остановить агента?")).to_be_visible()
        dialog.get_by_role("button", name="Остановить", exact=True).click()
        expect(agent_page.get_by_test_id("toast-container")).to_contain_text("Агент остановлен")
        expect(agent_page.get_by_label("Статус агента: ОСТАНОВЛЕН")).to_be_visible()

    def test_send_message_modal_posts_trigger(
        self, agent_page: object, api: object, users: dict
    ) -> None:
        agent_id = _new_agent(api, users, "Триггер")
        agent_page.goto(f"/agent/{agent_id}?tab=actions")
        agent_page.get_by_role("button", name="Отправить", exact=True).click()
        dialog = agent_page.get_by_role("dialog")
        expect(dialog.get_by_text("Отправить сообщение")).to_be_visible()
        dialog.get_by_label("Получатель (peer)").fill("@someone")
        dialog.get_by_label("Текст сообщения").fill("Тестовый триггер")
        dialog.get_by_role("button", name="Отправить", exact=True).click()
        expect(agent_page.get_by_test_id("toast-container")).to_contain_text("Сообщение отправлено")


class TestEmptyStates:
    def test_memory_empty(self, agent_page: object, api: object, users: dict) -> None:
        agent_id = _new_agent(api, users, "Без памяти")
        agent_page.goto(f"/agent/{agent_id}?tab=memory")
        expect(agent_page.get_by_text("Память пуста")).to_be_visible()

    def test_logs_empty(self, agent_page: object, api: object, users: dict) -> None:
        agent_id = _new_agent(api, users, "Без логов")
        agent_page.goto(f"/agent/{agent_id}?tab=logs")
        expect(agent_page.get_by_text("Нет записей")).to_be_visible()

    def test_telegram_missing_session(self, agent_page: object, api: object, users: dict) -> None:
        agent_id = _new_agent(api, users, "Без сессии", with_telegram_session=False)
        agent_page.goto(f"/agent/{agent_id}?tab=telegram")
        expect(agent_page.get_by_text("Telegram сессия не найдена")).to_be_visible()
```

- [ ] **Step 2: прогони** `uv run pytest tests/e2e -m e2e -q` → все e2e зелёные
- [ ] **Step 3: commit**

```bash
git add tests/e2e/test_agent.py
git commit -m "feat: port agent page e2e spec to python"
```

### Task B8: убрать TS e2e и перенастроить CI

**Files:**
- Delete: `frontend/e2e/`, `frontend/playwright.config.ts`
- Modify: `frontend/package.json`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: удали файлы**

Run: `rm -rf frontend/e2e frontend/playwright.config.ts`

- [ ] **Step 2: почисти package.json**

В `frontend/package.json` удали из `scripts` строку `"test:e2e": "playwright test",` и из `devDependencies` строку `"@playwright/test": "^1.48.0",`. Затем:

Run: `bun install`

- [ ] **Step 3: CI — unit job.** В `.github/workflows/ci.yml` строку:

```yaml
        run: uv run pytest -m "not db" -W error -q
```

замени на:

```yaml
        run: uv run pytest -m "not db and not e2e and not real_tg" -W error -q
```

- [ ] **Step 4: CI — e2e job на Python.** В джобе `e2e` замени шаги `Cache Playwright browsers`, `Install Playwright browsers`, `Run Playwright tests` и `Upload Playwright report`:

```yaml
      - name: Cache Playwright browsers
        uses: actions/cache@v4
        with:
          path: ~/.cache/ms-playwright
          key: playwright-${{ runner.os }}-${{ hashFiles('uv.lock') }}
          restore-keys: |
            playwright-${{ runner.os }}-

      - name: Install Playwright browsers
        run: uv run playwright install --with-deps chromium

      - name: Run e2e tests
        run: uv run pytest tests/e2e -m e2e -W error -q
        env:
          CI: true
          DATABASE_CONNECTION_STRING: ${{ secrets.DATABASE_CONNECTION_STRING }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_ANON_KEY: ${{ secrets.SUPABASE_ANON_KEY }}
          SECRET_KEY: ${{ secrets.SECRET_KEY }}
          TEST_USER_PASSWORD: ${{ secrets.TEST_USER_PASSWORD }}
          TELEGRAM_API_ID: '1'
          TELEGRAM_API_HASH: test-api-hash

      - name: Upload Playwright artifacts
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: playwright-artifacts
          path: test-results/
          retention-days: 7
```

(шаги `Set up uv`, `Install Python`, `Install backend dependencies`, `Set up Bun`, `Install frontend dependencies` остаются как есть)

- [ ] **Step 5: локальные прогоны**

Run: `uv run pytest -m "not db and not e2e and not real_tg" -q` → passed
Run: `uv run pytest -m e2e -q` → passed

- [ ] **Step 6: commit**

```bash
git add -A
git commit -m "feat: remove ts e2e stack, python e2e runs in ci"
```

---

## Часть C — реальные Telegram-тесты

### Task C1: модуль проверяющего

**Files:**
- Create: `src/mimic42/testing/real_tg/__init__.py`, `src/mimic42/testing/real_tg/checker.py`

- [ ] **Step 1: создай checker.py**

```python
"""Проверяющий Telegram-аккаунт: пишет мимику и читает ответ.

По документации Telethon: StringSession (Sessions), телефон работает только
если контакт импортирован (Entities), NewMessage-хендлер регистрируется ДО
отправки, луп клиента не меняется после connect (FAQ), сессия не делится
между процессами (FAQ: «database is locked»).
"""

from __future__ import annotations

import asyncio
import random
import threading
from uuid import UUID

import asyncpg
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact

REPLY_TIMEOUT_SECONDS = 300.0


class Checker:
    """Асинхронное ядро проверяющего."""

    def __init__(self, api_id: int, api_hash: str, session_string: str) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._session_string = session_string
        self._client: TelegramClient | None = None

    async def start(self) -> None:
        self._client = TelegramClient(
            StringSession(self._session_string), self._api_id, self._api_hash
        )
        await self._client.connect()
        if not await self._client.is_user_authorized():
            raise RuntimeError("Session string проверяющего не авторизована — прогони login")

    async def stop(self) -> None:
        if self._client is None:
            return
        await self._client.disconnect()
        self._client = None

    @property
    def client(self) -> TelegramClient:
        assert self._client is not None
        return self._client

    async def mimic_phones(self, dsn: str, owner_id: UUID) -> list[str]:
        conn = await asyncpg.connect(dsn)
        try:
            rows = await conn.fetch(
                """
                select ts.phone_number
                from agents a
                join telegram_sessions ts on ts.agent_id = a.id
                where a.owner_id = $1 and ts.phone_number is not null
                order by a.created_at
                """,
                owner_id,
            )
        finally:
            await conn.close()
        phones = [row["phone_number"] for row in rows if row["phone_number"]]
        if not phones:
            raise RuntimeError("Мимики не заведены — прогони реальный онборд")
        return phones

    async def import_contact(self, phone: str) -> None:
        try:
            await self.client.get_input_entity(phone)
            return
        except ValueError:
            await self.client(
                ImportContactsRequest(
                    contacts=[
                        InputPhoneContact(
                            client_id=random.randrange(-2**63, 2**63),
                            phone=phone,
                            first_name="Mimic",
                            last_name="Test",
                        )
                    ]
                )
            )
            await self.client.get_input_entity(phone)

    async def send(self, phone: str, text: str) -> int:
        message = await self.client.send_message(phone, text)
        return message.id

    async def wait_incoming(self, phone: str, *, timeout: float = REPLY_TIMEOUT_SECONDS) -> str:
        """Ждёт первое входящее сообщение от `phone` с момента вызова."""
        got: asyncio.Future[object] = asyncio.get_running_loop().create_future()

        async def handler(event: object) -> None:
            if not got.done():
                got.set_result(event)

        self.client.add_event_handler(
            handler, events.NewMessage(chats=[phone], incoming=True)
        )
        try:
            message = await asyncio.wait_for(got, timeout)
            return message.text or ""
        finally:
            self.client.remove_event_handler(handler)

    async def send_and_wait_reply(
        self, phone: str, text: str, *, timeout: float = REPLY_TIMEOUT_SECONDS
    ) -> str:
        """Регистрирует хендлер, отправляет, ждёт ответ. Порядок обязателен."""
        waiter = asyncio.ensure_future(self.wait_incoming(phone, timeout=timeout))
        await self.send(phone, text)
        try:
            return await waiter
        except BaseException:
            waiter.cancel()
            raise


class SyncChecker:
    """Синхронная обёртка для pytest-playwright: приватный луп в потоке.

    Луп один на весь срок жизни клиента (FAQ: «event loop must not change
    after connection»); все вызовы сериализуются на его лупе.
    """

    def __init__(self, api_id: int, api_hash: str, session_string: str) -> None:
        self._checker = Checker(api_id, api_hash, session_string)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def _run(self, coro: object) -> object:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=600)

    def start(self) -> None:
        self._run(self._checker.start())

    def stop(self) -> None:
        try:
            self._run(self._checker.stop())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=30)

    def mimic_phones(self, dsn: str, owner_id: UUID) -> list[str]:
        return self._run(self._checker.mimic_phones(dsn, owner_id))

    def ensure_contact(self, phone: str) -> None:
        self._run(self._checker.import_contact(phone))

    def send(self, phone: str, text: str) -> None:
        self._run(self._checker.send(phone, text))

    def wait_incoming(self, phone: str, *, timeout: float = REPLY_TIMEOUT_SECONDS) -> str:
        return self._run(self._checker.wait_incoming(phone, timeout=timeout))

    def send_and_wait_reply(
        self, phone: str, text: str, *, timeout: float = REPLY_TIMEOUT_SECONDS
    ) -> str:
        return self._run(self._checker.send_and_wait_reply(phone, text, timeout=timeout))
```

и `__init__.py`:

```python
from mimic42.testing.real_tg.checker import Checker, SyncChecker

__all__ = ["Checker", "SyncChecker"]
```

- [ ] **Step 2: линт**

Run: `uv run ruff check src/mimic42/testing/real_tg && uv run ty check` → чисто

- [ ] **Step 3: commit**

```bash
git add src/mimic42/testing/real_tg
git commit -m "feat: real telegram checker module"
```

### Task C2: скрипт входа

- [ ] **Step 1: создай `src/mimic42/testing/real_tg/login.py`**

```python
"""Одноразовый вход для session string проверяющего.

    TG_CHECKER_API_ID=... TG_CHECKER_API_HASH=... uv run python -m mimic42.testing.real_tg.login

Интерактивно спросит телефон, код (из SMS) и 2FA-пароль, затем напечатает
session string — вставь её в TG_CHECKER_SESSION (.env.test). Использует
`with client` → start(): интерактивный поток по документации Telethon.
"""

from __future__ import annotations

import os
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession


def main() -> None:
    api_id = os.environ.get("TG_CHECKER_API_ID")
    api_hash = os.environ.get("TG_CHECKER_API_HASH")
    if not api_id or not api_hash:
        sys.exit("TG_CHECKER_API_ID / TG_CHECKER_API_HASH не заданы (см. .env.example)")
    client = TelegramClient(StringSession(), int(api_id), api_hash)
    with client:
        print("\nTG_CHECKER_SESSION=")
        print(client.session.save())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: прогони вручную**

Run: `TG_CHECKER_API_ID=... TG_CHECKER_API_HASH=... uv run python -m mimic42.testing.real_tg.login`
Expected: интерактивный вход, на выходе `TG_CHECKER_SESSION=...`. Вставь в `.env.test`.

- [ ] **Step 3: commit**

```bash
git add src/mimic42/testing/real_tg/login.py
git commit -m "feat: checker session login script"
```

### Task C3: настройка сайт-аккаунта и переменные

**Files:**
- Modify: `scripts/test_env_bootstrap.py` (регистрация сайт-аккаунта влита
  в существующий bootstrap как `ensure_real_tg_account`)
- Modify: `.env.example`

- [ ] **Step 1: регистрация аккаунта**

Отдельный скрипт не создаётся: `scripts/test_env_bootstrap.py` уже заводит
тестовые учётки через Admin API, поэтому аккаунт реальных TG-тестов заводится
там же — опционально, если заданы `TEST_ACCOUNT_EMAIL/PASSWORD`, и без
фиксированного id (тесты берут owner_id из `sub` JWT). Сервисный ключ —
`SUPABASE_SERVICE_ROLE_KEY` из `.env` (тот же, что у медиа-стораджа).

- [ ] **Step 2: допиши `.env.example`**

```
# --- Реальные Telegram-тесты (pytest -m real_tg) ---
# Выделенный аккаунт сайта Mimic (владелец агентов-мимиков), создаётся
# scripts/test_env_bootstrap.py один раз.
TEST_ACCOUNT_EMAIL=test@mail.zomb.top
TEST_ACCOUNT_PASSWORD=
# Проверяющий Telegram-аккаунт (реальный): session string — секрет.
TG_CHECKER_API_ID=
TG_CHECKER_API_HASH=
TG_CHECKER_SESSION=
```

- [ ] **Step 3: commit**

```bash
git add scripts/test_env_bootstrap.py .env.example
git commit -m "feat: real-tg site account setup script and env contract"
```

### Task C4: ручная настройка (выполняет человек)

- [ ] 1. `uv run python scripts/test_env_bootstrap.py` (при заданных `TEST_ACCOUNT_EMAIL/PASSWORD` заводит сайт-аккаунт) → `TEST_ACCOUNT_*` в `.env.test`
- [ ] 2. Онборд двух мимиков через дашборд вручную (онбординг тестами не покрывается)
- [ ] 3. `uv run python -m mimic42.testing.real_tg.login` → session string → `.env.test`
- [ ] 4. Секреты CI: TG_CHECKER_API_ID/HASH/SESSION, TEST_ACCOUNT_EMAIL/PASSWORD, TELEGRAM_API_ID/HASH, OPENROUTER_API_KEY, SUPABASE_ANON_KEY

### Task C5: бэкенд-слой real_tg

**Files:**
- Create: `tests/real_tg/backend/helpers.py`, `tests/real_tg/backend/conftest.py`, `tests/real_tg/backend/test_real_dialog.py`

- [ ] **Step 1: helpers.py**

```python
"""Помощники реальных TG-тестов бэкенда: логин, owner id и поиск агентов."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import asyncpg
import httpx
import jwt as pyjwt

from mimic42.testing.slots import plain_dsn

ROOT = Path(__file__).resolve().parents[3]


def anon_key() -> str:
    """Публичный anon-ключ: из окружения (CI) или frontend/.env.local (локально)."""
    value = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    if value:
        return value
    env_local = ROOT / "frontend" / ".env.local"
    if env_local.exists():
        for line in env_local.read_text().splitlines():
            if line.startswith("NEXT_PUBLIC_SUPABASE_ANON_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("SUPABASE_ANON_KEY / NEXT_PUBLIC_SUPABASE_ANON_KEY не найден")


async def jwt() -> str:
    """Supabase JWT для API-вызовов от имени реального сайт-аккаунта."""
    async with httpx.AsyncClient(base_url=os.environ["SUPABASE_URL"].rstrip("/")) as client:
        response = await client.post(
            "/auth/v1/token?grant_type=password",
            headers={"apikey": anon_key()},
            json={
                "email": os.environ["TEST_ACCOUNT_EMAIL"],
                "password": os.environ["TEST_ACCOUNT_PASSWORD"],
            },
        )
        response.raise_for_status()
        return str(response.json()["access_token"])


def user_id_from_token(token: str) -> UUID:
    """owner_id — тот же claim `sub`, что читает прод (`api/auth.py`).

    Подпись не проверяется: токен только что получен от Supabase по TLS,
    из него берётся собственная личность, а не принимается чужое решение.
    """
    payload = pyjwt.decode(token, options={"verify_signature": False})
    return UUID(str(payload["sub"]))


async def agent_id_for_phone(dsn: str, phone: str, owner_id: UUID) -> str:
    conn = await asyncpg.connect(plain_dsn(dsn))
    try:
        row = await conn.fetchrow(
            """
            select a.id::text as agent_id
            from agents a join telegram_sessions ts on ts.agent_id = a.id
            where ts.phone_number = $1 and a.owner_id = $2
            """,
            phone,
            owner_id,
        )
    finally:
        await conn.close()
    assert row, f"Нет агента с телефоном {phone}"
    return str(row["agent_id"])
```

- [ ] **Step 2: conftest.py**

```python
"""Общая обвязка реальных TG-тестов бэкенда: настоящий app и проверяющий."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from dotenv import load_dotenv
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from mimic42.config import Settings

ROOT = Path(__file__).resolve().parents[3]
# real_tg работает с боевой конфигурацией: .env грузится ПОВЕРХ тестовых
# переопределений (.env.test выставляет заглушки телеги и правит базу).
load_dotenv(ROOT / ".env", override=True)

from mimic42.api.app import create_app  # noqa: E402


@pytest_asyncio.fixture
async def real_app() -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    settings = Settings(
        database_connection_string=os.environ["DATABASE_CONNECTION_STRING"],
        supabase_url=os.environ["SUPABASE_URL"],
        secret_key=os.environ["SECRET_KEY"],
        telegram_api_id=int(os.environ["TELEGRAM_API_ID"]),
        telegram_api_hash=os.environ["TELEGRAM_API_HASH"],
        mem0_api_key=None,  # Mem0 в тестах не дёргаем
    )
    app = create_app(settings=settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield app, client


@pytest_asyncio.fixture
async def checker() -> AsyncIterator[object]:
    from mimic42.testing.real_tg.checker import Checker

    instance = Checker(
        api_id=int(os.environ["TG_CHECKER_API_ID"]),
        api_hash=os.environ["TG_CHECKER_API_HASH"],
        session_string=os.environ["TG_CHECKER_SESSION"],
    )
    await instance.start()
    yield instance
    await instance.stop()


@pytest_asyncio.fixture
async def started_mimics(
    real_app: tuple[FastAPI, AsyncClient], checker: object
) -> list[tuple[str, str]]:
    """Запускает агентов-мимиков через API; возвращает [(agent_id, phone)]."""
    _, client = real_app
    from tests.real_tg.backend.helpers import agent_id_for_phone, jwt, user_id_from_token

    token = await jwt()
    owner_id = user_id_from_token(token)
    dsn = os.environ["DATABASE_CONNECTION_STRING"]
    phones = await checker.mimic_phones(dsn, owner_id)
    agents: list[tuple[str, str]] = []
    for phone in phones:
        agent_id = await agent_id_for_phone(dsn, phone, owner_id)
        response = await client.post(
            f"/api/v1/agents/{agent_id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 204, response.text
        agents.append((agent_id, phone))
    return agents
```

- [ ] **Step 3: test_real_dialog.py**

```python
"""Реальный диалог: проверяющий пишет мимику, мимик отвечает в настоящем TG."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from mimic42.testing.real_tg.checker import Checker
from mimic42.testing.slots import plain_dsn
from tests.real_tg.backend.helpers import jwt

pytestmark = pytest.mark.real_tg


async def test_agent_replies_in_real_telegram(
    checker: Checker, started_mimics: list[tuple[str, str]]
) -> None:
    agent_id, phone = started_mimics[0]
    await checker.import_contact(phone)
    reply = await checker.send_and_wait_reply(phone, "Привет, как дела?", timeout=300)
    assert reply and reply.strip(), "Мимик не ответил в реальном Telegram"

    conn = await asyncpg.connect(plain_dsn(os.environ["DATABASE_CONNECTION_STRING"]))
    try:
        rows = await conn.fetch(
            "select direction from agent_messages where agent_id = $1 "
            "order by created_at desc limit 10",
            UUID(agent_id),
        )
    finally:
        await conn.close()
    directions = {row["direction"] for row in rows}
    assert "incoming" in directions, "Входящее не записано в agent_messages"
    assert "outgoing" in directions, "Ответ не записан в agent_messages"


async def test_trigger_message_arrives_in_telegram(
    real_app: tuple[FastAPI, AsyncClient],
    checker: Checker,
    started_mimics: list[tuple[str, str]],
) -> None:
    agent_id, phone = started_mimics[1]
    _, client = real_app
    token = await jwt()
    await checker.import_contact(phone)
    incoming = asyncio.ensure_future(checker.wait_incoming(phone, timeout=180))
    response = await client.post(
        f"/api/v1/agents/{agent_id}/messages/trigger",
        headers={"Authorization": f"Bearer {token}"},
        json={"peer": phone, "text": "Тестовое сообщение из дашборда"},
    )
    assert response.status_code == 200, response.text
    text = await incoming
    assert text and text.strip()
```

- [ ] **Step 4: линт**

Run: `uv run ruff check tests/real_tg && uv run ty check` → чисто

- [ ] **Step 5: commit**

```bash
git add tests/real_tg/backend
git commit -m "feat: real telegram backend tests"
```

### Task C6: фронт-слой real_tg — реальный диалог

**Files:**
- Create: `tests/real_tg/frontend/conftest.py`, `tests/real_tg/frontend/test_real_dialog.py`

- [ ] **Step 1: conftest**

```python
"""Настоящий бэкенд + фронт для real_tg фронт-слоя. Маркер real_tg."""

from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser
from dotenv import load_dotenv

from mimic42.testing.real_tg.checker import SyncChecker
from tests.real_tg.backend.helpers import (
    agent_id_for_phone,
    anon_key,
    jwt,
    user_id_from_token,
)

ROOT = Path(__file__).resolve().parents[3]
AUTH_DIR = ROOT / "tests" / "e2e" / ".auth"
API_PORT = int(os.environ.get("E2E_API_PORT", "8000"))
APP_PORT = int(os.environ.get("E2E_APP_PORT", "3000"))
API_URL = f"http://127.0.0.1:{API_PORT}"
APP_URL = f"http://127.0.0.1:{APP_PORT}"
# Боевые переменные поверх тестовых переопределений (.env.test).
load_dotenv(ROOT / ".env", override=True)


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
    _wait_for(f"{API_URL}/health", timeout=90)

    anon_key = env.get("SUPABASE_ANON_KEY") or env.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    if not anon_key:
        env_local = ROOT / "frontend" / ".env.local"
        if env_local.exists():
            for line in env_local.read_text().splitlines():
                if line.startswith("NEXT_PUBLIC_SUPABASE_ANON_KEY="):
                    anon_key = line.split("=", 1)[1].strip()
    assert anon_key, "NEXT_PUBLIC_SUPABASE_ANON_KEY не найден"

    front_env = {
        **env,
        "NEXT_PUBLIC_SUPABASE_URL": env["SUPABASE_URL"],
        "NEXT_PUBLIC_SUPABASE_ANON_KEY": anon_key,
        "NEXT_PUBLIC_API_BASE_URL": API_URL,
        "PORT": str(APP_PORT),
    }
    web_proc = subprocess.Popen(["bun", "run", "dev"], cwd=ROOT / "frontend", env=front_env)
    try:
        _wait_for(APP_URL, timeout=180)
        yield
    finally:
        web_proc.terminate()
        api_proc.terminate()
        web_proc.wait(timeout=30)
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

    async def start_all() -> list[tuple[str, str]]:
        token = await jwt()
        owner_id = user_id_from_token(token)
        phones = sync_checker.mimic_phones(dsn, owner_id)
        agents: list[tuple[str, str]] = []
        async with httpx.AsyncClient(base_url=API_URL, timeout=60.0) as client:
            for phone in phones:
                agent_id = await agent_id_for_phone(dsn, phone, owner_id)
                response = await client.post(
                    f"/api/v1/agents/{agent_id}/start",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert response.status_code == 204, response.text
                agents.append((agent_id, phone))
        return agents

    return asyncio.run(start_all())


@pytest.fixture(scope="session")
def real_auth(browser: object, real_servers: None) -> str:
    state_path = AUTH_DIR / "real_tg.json"
    if state_path.exists():
        return str(state_path)
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    context = browser.new_context(base_url=APP_URL)
    page = context.new_page()
    page.goto("/login")
    page.get_by_label("Email").fill(os.environ["TEST_ACCOUNT_EMAIL"])
    page.get_by_label("Пароль", exact=True).fill(os.environ["TEST_ACCOUNT_PASSWORD"])
    page.get_by_role("button", name="Войти").click()
    page.wait_for_url("**/onboarding**", timeout=60_000)
    context.storage_state(path=str(state_path))
    context.close()
    return str(state_path)
```

- [ ] **Step 2: test_real_dialog.py**

```python
"""Реальный диалог через дашборд: проверяющий пишет мимику, ответ виден в UI."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.real_tg


def test_dialog_visible_in_dashboard(
    browser: object,
    real_auth: str,
    sync_checker: object,
    mimic_agents: list[tuple[str, str]],
) -> None:
    agent_id, phone = mimic_agents[0]
    sync_checker.ensure_contact(phone)
    context = browser.new_context(base_url=APP_URL, storage_state=real_auth)
    page = context.new_page()
    try:
        page.goto(f"/agent/{agent_id}?tab=logs")
        reply = sync_checker.send_and_wait_reply(
            phone, "Привет из реального теста", timeout=300
        )
        assert reply.strip()
        expect(page.get_by_text("Привет из реального теста")).to_be_visible(timeout=180_000)
        expect(page.get_by_text(reply[:40])).to_be_visible(timeout=180_000)
    finally:
        context.close()
```

- [ ] **Step 3: локальный прогон** (после Task C5/C4 настройки)

Run: `uv run pytest tests/real_tg/frontend -m real_tg -q`

- [ ] **Step 4: commit**

```bash
git add tests/real_tg/frontend
git commit -m "feat: real telegram dashboard dialog test"
```

### Task C7: real-tg.yml

- [ ] **Step 1: создай `.github/workflows/real-tg.yml`**

```yaml
name: Real Telegram Tests

on:
  workflow_dispatch:

concurrency:
  group: mimic42-dev-testdb
  cancel-in-progress: false

jobs:
  backend-real:
    name: backend-real-tg
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv python install
      - run: uv sync --locked --all-groups
      - name: Backend real-TG tests
        run: uv run pytest tests/real_tg/backend -m real_tg -W error -q
        env:
          DATABASE_CONNECTION_STRING: ${{ secrets.DATABASE_CONNECTION_STRING }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_ANON_KEY: ${{ secrets.SUPABASE_ANON_KEY }}
          SECRET_KEY: ${{ secrets.SECRET_KEY }}
          TELEGRAM_API_ID: ${{ secrets.TELEGRAM_API_ID }}
          TELEGRAM_API_HASH: ${{ secrets.TELEGRAM_API_HASH }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          TG_CHECKER_API_ID: ${{ secrets.TG_CHECKER_API_ID }}
          TG_CHECKER_API_HASH: ${{ secrets.TG_CHECKER_API_HASH }}
          TG_CHECKER_SESSION: ${{ secrets.TG_CHECKER_SESSION }}
          TEST_ACCOUNT_EMAIL: ${{ secrets.TEST_ACCOUNT_EMAIL }}
          TEST_ACCOUNT_PASSWORD: ${{ secrets.TEST_ACCOUNT_PASSWORD }}

  frontend-real:
    name: frontend-real-tg
    runs-on: ubuntu-latest
    timeout-minutes: 40
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv python install
      - run: uv sync --locked --all-groups
      - uses: oven-sh/setup-bun@v2
      - run: bun install --frozen-lockfile
        working-directory: frontend
      - run: uv run playwright install --with-deps chromium
      - name: Run real dashboard dialog
        run: uv run pytest tests/real_tg/frontend -m real_tg -W error -q
        env:
          CI: true
          DATABASE_CONNECTION_STRING: ${{ secrets.DATABASE_CONNECTION_STRING }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_ANON_KEY: ${{ secrets.SUPABASE_ANON_KEY }}
          SECRET_KEY: ${{ secrets.SECRET_KEY }}
          TELEGRAM_API_ID: ${{ secrets.TELEGRAM_API_ID }}
          TELEGRAM_API_HASH: ${{ secrets.TELEGRAM_API_HASH }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          TG_CHECKER_API_ID: ${{ secrets.TG_CHECKER_API_ID }}
          TG_CHECKER_API_HASH: ${{ secrets.TG_CHECKER_API_HASH }}
          TG_CHECKER_SESSION: ${{ secrets.TG_CHECKER_SESSION }}
          TEST_ACCOUNT_EMAIL: ${{ secrets.TEST_ACCOUNT_EMAIL }}
          TEST_ACCOUNT_PASSWORD: ${{ secrets.TEST_ACCOUNT_PASSWORD }}
```

- [ ] **Step 2: commit**

```bash
git add .github/workflows/real-tg.yml
git commit -m "ci: manual real telegram test workflow"
```

### Task C8: финальный прогон

- [ ] `uv run pytest -m "not db and not e2e and not real_tg" -q` → passed
- [ ] `uv run pytest -m db -q` → passed
- [ ] `uv run pytest -m e2e -q` → passed
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run ty check` → чисто
- [ ] `frontend`: `bun run lint && bun run typecheck && bun test` → чисто
- [ ] После ручной настройки (Task C5→C4): `uv run pytest -m real_tg -q` локально
- [ ] После покупки мимиков → онборд → прогон → PR

---

## Самопроверка

1. **Спека → задачи:** строгий клиент (A1), поле конфига (A2), контракт API (A3), мусор (A4), прогоны (A5); маркеры/зависимости (B1); helpers/conftest/порты (B2–B7); удаление TS e2e и CI (B8); проверяющий и вход (C1–C2); сайт-аккаунт и env (C3); ручная настройка (C4); бэкенд-слой (C5); фронт-слой (C6); workflow (C7); регресс (C8). Онбординг мимиков — ручная операция вне тестов (см. спеку). Всё из спеки покрыто.
2. **Плейсхолдеры:** все фрагменты кода полные; вспомогательные функции (`_jwt`, `agent_id_for_phone`, `mimic_agents`) определены в своих файлах.
3. **Типы/имена:** `Checker.mimic_phones(dsn, owner_id)` и `SyncChecker.mimic_phones(dsn, owner_id)` — единые сигнатуры; owner_id везде берётся из `sub` JWT (`user_id_from_token`); `auth_states`/`persona_page`/`mimic_agents` согласованы между conftest и тестами.
