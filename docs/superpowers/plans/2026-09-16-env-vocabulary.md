# Единый словарь переменных окружения — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Свести три словаря env-переменных к одному, убрать дублирующие `.env`-файлы и сделать так, чтобы тесты грузили свои настройки сами, без `source`.

**Architecture:** Приложение по-прежнему читает `.env` через pydantic. Тестовый слой получает единый загрузчик `mimic42/testing/env.py` (`.env`, затем перекрывающий `.env.test`) и вызывающие его точки входа: `conftest.py`, тестовый сервер, `slot_cli`, bootstrap-скрипт; Playwright грузит те же файлы через `dotenv`. `TEST_`-дубли имён удаляются, `assert_test_project` остаётся единственным заслоном от прод-проекта.

**Tech Stack:** Python 3.13, pytest 9, pydantic-settings, python-dotenv, Playwright, Bun, GitHub Actions.

**Спека:** `docs/superpowers/specs/2026-09-16-env-vocabulary-design.md`

---

## Структура файлов

- `src/mimic42/testing/env.py` — **новый**. Единственное место, где описан порядок загрузки локальных env-файлов для тестового слоя.
- `conftest.py` — вызывает загрузчик, проверяет настройки, падает вместо тихого скипа.
- `tests/testing/test_env_loader.py` — **новый**. Юнит-тесты загрузчика (без базы).
- `src/mimic42/testing/server.py`, `src/mimic42/testing/slot_cli.py`, `scripts/test_env_bootstrap.py` — новые имена переменных, само-загрузка через `env.py`.
- `pyproject.toml` — `python-dotenv` как явная dev-зависимость, `addopts`, маркер `db`.
- `frontend/playwright.config.ts`, `frontend/package.json` — загрузка `.env`/`.env.test` через `dotenv`.
- `.env.example`, `.env`, `.env.test`, `.gitignore`, `frontend/.env.test`, `.env.test.example` — словарь и состав файлов.
- `.github/workflows/ci.yml` — имена секретов.
- `README.md`, `deploy/deploy.sh` — документация.

---

## Task 1: Завести секреты под новыми именами (до первого push)

Порядок обязателен: CI на PR читает секреты по именам, поэтому новые имена должны существовать раньше, чем изменения уедут в ветку. Старые имена при этом остаются живы и удаляются только после мерджа.

**Files:**
- Modify (внешнее состояние): секреты репозитория `42-Z/Mimic42`

- [ ] **Step 1: Убедиться, что значение можно достать локально**

Run:
```bash
grep -c '^DATABASE_CONNECTION_STRING=' .env
grep -c '^SECRET_KEY=' .env
grep -c '^SUPABASE_URL=' .env
grep -c '^NEXT_PUBLIC_SUPABASE_ANON_KEY=' frontend/.env.local
```
Expected: везде `1`.

- [ ] **Step 2: Завести пять секретов под новыми именами (значения не печатаются в терминал)**

Run:
```bash
grep -m1 '^SUPABASE_URL=' .env | cut -d= -f2- | tr -d '"' | gh secret set SUPABASE_URL --repo 42-Z/Mimic42
grep -m1 '^DATABASE_CONNECTION_STRING=' .env | cut -d= -f2- | tr -d '"' | gh secret set DATABASE_CONNECTION_STRING --repo 42-Z/Mimic42
grep -m1 '^SECRET_KEY=' .env | cut -d= -f2- | tr -d '"' | gh secret set SECRET_KEY --repo 42-Z/Mimic42
grep -m1 '^NEXT_PUBLIC_SUPABASE_ANON_KEY=' frontend/.env.local | cut -d= -f2- | tr -d '"' | gh secret set SUPABASE_ANON_KEY --repo 42-Z/Mimic42
grep -m1 '^DATABASE_CONNECTION_STRING=' .env | cut -d= -f2- | sed -E 's|.*://[^:]+:([^@]+)@.*|\1|' | gh secret set SUPABASE_DB_PASSWORD --repo 42-Z/Mimic42
```
Expected: пять строк `✓ Set Actions secret NAME for 42-Z/Mimic42`.

- [ ] **Step 3: Проверить, что имена появились**

Run: `gh secret list --repo 42-Z/Mimic42`
Expected: в списке есть `SUPABASE_URL`, `DATABASE_CONNECTION_STRING`, `SECRET_KEY`, `SUPABASE_ANON_KEY`, `SUPABASE_DB_PASSWORD` — рядом со старыми `TEST_*`.

**Если `migrations-drift` на PR упадёт с ошибкой аутентификации Supabase** — значит пароль Dev-БД, лежавший в `TEST_DB_PASSWORD`, отличается от того, что в строке подключения. Тогда значение надо взять из первоисточника и повторить `gh secret set SUPABASE_DB_PASSWORD`.

---

## Task 2: Загрузчик env-файлов для тестового слоя

**Files:**
- Create: `src/mimic42/testing/env.py`
- Test: `tests/testing/test_env_loader.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/testing/test_env_loader.py`:

```python
from __future__ import annotations

import os
from pathlib import Path

from mimic42.testing.env import load_test_env


def test_test_file_overrides_base(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("MIMIC42_PROBE=base\nMIMIC42_ONLY_BASE=base\n")
    (tmp_path / ".env.test").write_text("MIMIC42_PROBE=test\n")
    monkeypatch.delenv("MIMIC42_PROBE", raising=False)
    monkeypatch.delenv("MIMIC42_ONLY_BASE", raising=False)

    loaded = load_test_env(tmp_path)

    assert loaded == [tmp_path / ".env", tmp_path / ".env.test"]
    assert os.environ["MIMIC42_PROBE"] == "test"
    assert os.environ["MIMIC42_ONLY_BASE"] == "base"


def test_missing_files_are_not_an_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MIMIC42_PROBE", raising=False)
    assert load_test_env(tmp_path) == []
    assert "MIMIC42_PROBE" not in os.environ


def test_real_environment_wins_over_base_file(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("MIMIC42_PROBE=base\n")
    monkeypatch.setenv("MIMIC42_PROBE", "shell")

    load_test_env(tmp_path)

    assert os.environ["MIMIC42_PROBE"] == "shell"
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `uv run pytest -q tests/testing/test_env_loader.py`
Expected: FAIL с `ModuleNotFoundError: No module named 'mimic42.testing.env'`.

- [ ] **Step 3: Написать загрузчик**

Создать `src/mimic42/testing/env.py`:

```python
"""Загрузка локальных env-файлов для тестового слоя.

Приложение читает `.env` само (pydantic), а тестовый слой раньше рассчитывал на
ручной ``source .env.test``. Здесь этот порядок собран в одном месте: сначала
`.env` как база, поверх него `.env.test`. Реальное окружение сильнее базового
файла, поэтому явно выставленная переменная не перетирается (так же ведёт себя
Next: `process.env` в приоритете).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_ENV_FILE = ".env"
TEST_ENV_FILE = ".env.test"

# src/mimic42/testing/env.py -> корень репозитория
REPO_ROOT = Path(__file__).resolve().parents[3]


def load_test_env(root: Path | None = None) -> list[Path]:
    """Загрузить `.env`, затем перекрывающий его `.env.test`.

    Возвращает список реально прочитанных файлов: в CI файлов нет и это не
    ошибка — значения приходят из секретов.
    """
    base = root if root is not None else REPO_ROOT
    loaded: list[Path] = []
    for name, override in ((BASE_ENV_FILE, False), (TEST_ENV_FILE, True)):
        path = base / name
        if path.is_file():
            load_dotenv(path, override=override)
            loaded.append(path)
    return loaded
```

- [ ] **Step 4: Объявить зависимость явно**

`python-dotenv` приезжает транзитивно с `pydantic-settings`, но раз мы импортируем его напрямую, он должен быть объявлен. В `pyproject.toml` в группу `[dependency-groups] dev` добавить строку:

```toml
dev = [
    "httpx>=0.28.1",
    "pytest>=9.0.3",
    "pytest-asyncio>=1.3.0",
    "python-dotenv>=1.2.2",
    "ruff>=0.15.13",
    "ty>=0.0.37",
]
```

Затем:
Run: `uv sync --all-groups`
Expected: `python-dotenv` остаётся в локе, новых пакетов не докачивается.

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `uv run pytest -q tests/testing/test_env_loader.py`
Expected: `3 passed`.

- [ ] **Step 6: Коммит**

```bash
git add pyproject.toml uv.lock src/mimic42/testing/env.py tests/testing/test_env_loader.py
git commit -m "feat(test): единый загрузчик .env и .env.test для тестового слоя"
```

---

## Task 3: conftest — автозагрузка и падение вместо скипа

**Files:**
- Modify: `conftest.py`

- [ ] **Step 1: Переписать загрузку и фикстуру**

Привести `conftest.py` к виду (изменяются импорты, добавляется вызов загрузчика, переписывается `test_dsn`):

```python
"""Общие фикстуры. Тесты с маркером db работают против настоящей
базы проекта Mimic42 Dev и занимают слот тестовых аккаунтов."""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from mimic42.integrations.database_session import create_engine, create_session_factory
from mimic42.testing import registry
from mimic42.testing.cleanup import purge_slot_data
from mimic42.testing.env import load_test_env
from mimic42.testing.slots import Slot, acquire_slot, assert_test_project, release_slot

# До сбора тестов: значения из .env/.env.test нужны и фикстурам, и тестовому
# серверу, и они же закрывают заслон от прод-проекта реальными значениями.
load_test_env()


@pytest.fixture(scope="session")
def test_dsn() -> str:
    dsn = os.environ.get("DATABASE_CONNECTION_STRING")
    url = os.environ.get("SUPABASE_URL")
    if not dsn or not url:
        pytest.fail(
            "DATABASE_CONNECTION_STRING/SUPABASE_URL не заданы: "
            "скопируйте .env.example в .env. db-тесты запускаются явно: "
            "`uv run pytest -m db`"
        )
    try:
        # Проверяем и DSN, и адрес проекта: фикстуры пишут и через SQLAlchemy,
        # и через Supabase-подобные вызовы, а заслон должен стоять на входе.
        assert_test_project(dsn, url)
    except RuntimeError as exc:
        pytest.fail(str(exc))
    return dsn
```

Остальные фикстуры (`test_slot`, `db_engine`, `db_session_factory`, `clean_slot`) и хук `pytest_collection_modifyitems` не меняются.

- [ ] **Step 2: Проверить, что db-тесты больше не скипаются молча**

Run: `uv run pytest -q -m db --collect-only | tail -2`
Expected: `38 tests collected` (без упоминания skip).

- [ ] **Step 3: Проверить громкое падение без настроек**

Run:
```bash
mv .env .env.backup && uv run pytest -q -m db 2>&1 | tail -5; mv .env.backup .env
```
Expected: тесты падают с текстом `DATABASE_CONNECTION_STRING/SUPABASE_URL не заданы`, а не отчитываются зелёными. Файл `.env` возвращён на место.

- [ ] **Step 4: Коммит**

```bash
git add conftest.py
git commit -m "test: conftest грузит .env и .env.test сам, вместо тихого скипа — падение"
```

---

## Task 4: pyproject — db-тесты только по явному запросу

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Добавить addopts и маркер**

В `pyproject.toml` раздел `[tool.pytest.ini_options]` привести к виду:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
# Тесты против настоящей базы по умолчанию исключены: они занимают слот
# тестовых аккаунтов и чистят данные в общей Dev-базе. Явный `-m db` с
# командной строки перекрывает этот addopts и включает их.
addopts = ["-m", "not db"]
markers = ["db: тесты против настоящей базы Mimic42 Dev"]
```

- [ ] **Step 2: Проверить оба режима**

Run: `uv run pytest -q 2>&1 | tail -2`
Expected: `141 passed, 38 deselected`.

Run: `uv run pytest -q -m db 2>&1 | tail -2`
Expected: `38 passed, 141 deselected` (около 6 минут, нужен `.env`).

- [ ] **Step 3: Убедиться, что `-k` db-тесты не разлочивает**

Run: `uv run pytest -q -k slots --collect-only 2>&1 | tail -2`
Expected: ни одного `passed` — db-тесты из `tests/integration/test_slots.py` отсечены маркером (`deselected`), даже когда имя подходит под `-k`.

- [ ] **Step 4: Коммит**

```bash
git add pyproject.toml
git commit -m "test: db-тесты включаются только явным -m db, без флага в окружении"
```

---

## Task 5: Тестовый сервер, slot_cli и бутстрап — новые имена и само-загрузка

**Files:**
- Modify: `src/mimic42/testing/server.py:74-88`, `src/mimic42/testing/server.py:236`
- Modify: `src/mimic42/testing/slot_cli.py:24-27`
- Modify: `scripts/test_env_bootstrap.py:1-6`, `scripts/test_env_bootstrap.py:75-88`

- [ ] **Step 1: Переписать `_test_settings()` и модульный гард**

В `src/mimic42/testing/server.py` в импорты добавить:

```python
from mimic42.testing.env import load_test_env
```

`_test_settings()` привести к виду:

```python
def _test_settings() -> Settings:
    database_connection_string = os.environ["DATABASE_CONNECTION_STRING"]
    supabase_url = os.environ["SUPABASE_URL"]
    return Settings(
        database_connection_string=database_connection_string,
        supabase_url=supabase_url,
        secret_key=os.environ["SECRET_KEY"],
        telegram_api_id=int(os.environ.get("TELEGRAM_API_ID", "1")),
        telegram_api_hash=os.environ.get("TELEGRAM_API_HASH", "test-api-hash"),
        cors_allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        # Явно отключает Mem0: без этого Settings() подхватил бы боевой
        # MEM0_API_KEY из .env разработчика, и тесты били бы по настоящему
        # внешнему сервису. Память подменяется FakeLongTermMemory ниже.
        mem0_api_key=None,
    )
```

Модульный гард в конце файла заменить на явный:

```python
if os.environ.get("DATABASE_CONNECTION_STRING"):
    # Строится только когда переменные окружения реально заданы: иначе
    # простой импорт этого модуля (например, во время сбора тестов без
    # базы) падал бы независимо от маркера db.
    app = build_test_app()
```

- [ ] **Step 2: Само-загрузка в точке входа сервера**

Сразу после блока импортов `src/mimic42/testing/server.py` (перед определением моделей) добавить:

```python
# Точка входа для `uvicorn mimic42.testing.server:app`: файлы грузятся здесь,
# чтобы сервер поднимался без предварительного `source .env.test`.
load_test_env()
```

Проверить, что запуск без сорса работает:

Run:
```bash
uv run uvicorn mimic42.testing.server:app --port 8099 & sleep 5; curl -s http://127.0.0.1:8099/health; kill %1
```
Expected: `{"status":"ok","service":"mimic42-api"}`.

- [ ] **Step 3: slot_cli — новое имя DSN и само-загрузка**

В `src/mimic42/testing/slot_cli.py` импорт дополнить:

```python
from mimic42.testing.env import load_test_env
```

Функцию `_dsn()` привести к виду:

```python
def _dsn() -> str:
    load_test_env()
    value = os.environ["DATABASE_CONNECTION_STRING"]
    assert_test_project(value)
    return value
```

- [ ] **Step 4: Bootstrap-скрипт — новые имена, само-загрузка, сервисный ключ только из окружения**

В `scripts/test_env_bootstrap.py` в импорты добавить `from mimic42.testing.env import load_test_env`, а функцию `main()` привести к виду:

```python
async def main() -> int:
    load_test_env()
    dsn = os.environ["DATABASE_CONNECTION_STRING"]
    supabase_url = os.environ["SUPABASE_URL"]
    password = os.environ["TEST_USER_PASSWORD"]
    # Сервисный ключ намеренно не лежит в env-файлах: он нужен ровно этому
    # скрипту, поэтому передаётся явно и не попадает в окружение тестов.
    service_key = os.environ.get("TEST_SUPABASE_SERVICE_ROLE_KEY", "")
    if not service_key:
        raise SystemExit(
            "TEST_SUPABASE_SERVICE_ROLE_KEY не задан. Запуск:\n"
            "  TEST_SUPABASE_SERVICE_ROLE_KEY=... uv run python scripts/test_env_bootstrap.py"
        )
    try:
        # service_key сразу пойдёт в Admin API: проверяем и его, а не только
        # DSN с адресом, — иначе чужим ключом можно завести юзеров не туда.
        assert_test_project(dsn, supabase_url, service_key)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    await ensure_schema(_plain_dsn(dsn))
    await ensure_users(supabase_url, service_key, password)
    return 0
```

Докстринг модуля дополнить строкой про способ запуска:

```
Запускается руками, требует TEST_SUPABASE_SERVICE_ROLE_KEY в окружении
(в файлах он не хранится — см. .env.example). Повторный запуск ничего не ломает.
```

- [ ] **Step 5: Убедиться, что тестовый сервер и db-тесты живы**

Run: `uv run pytest -q -m db -k testing_server 2>&1 | tail -3`
Expected: `5 passed` (в том числе те два, что падали раньше).

- [ ] **Step 6: Коммит**

```bash
git add src/mimic42/testing/server.py src/mimic42/testing/slot_cli.py scripts/test_env_bootstrap.py
git commit -m "test: тестовый слой читает общие имена и грузит env сам"
```

---

## Task 6: Интеграционные тесты — единый `SECRET_KEY`

**Files:**
- Modify: `tests/integration/test_app_lifespan.py:22-25`
- Modify: `tests/integration/test_conversation.py:41-44`

- [ ] **Step 1: Поправить первый тест**

В `tests/integration/test_app_lifespan.py` заменить чтение ключа:

```python
    """Тот же ключ, что build_test_app() берёт из SECRET_KEY — без
    совпадения строки телеграм-сессии нечем расшифровать."""
    return FernetSecretCipher(os.environ["SECRET_KEY"])
```

- [ ] **Step 2: Поправить второй тест**

В `tests/integration/test_conversation.py` заменить чтение ключа:

```python
    # Тот же ключ, что build_test_app() берёт из SECRET_KEY: конфиг
    # рантайма расшифровывается только им.
    cipher = FernetSecretCipher(os.environ["SECRET_KEY"])
```

- [ ] **Step 3: Проверить, что дублей имён в питоне не осталось**

Run: `grep -rn "TEST_SECRET_KEY\|TEST_DATABASE_CONNECTION_STRING\|TEST_SUPABASE_URL\|TEST_TELEGRAM" --include=*.py . | grep -v '/.venv/'`
Expected: пусто.

- [ ] **Step 4: Прогнать оба набора**

Run: `uv run pytest -q -m db 2>&1 | tail -2`
Expected: `38 passed`.

- [ ] **Step 5: Коммит**

```bash
git add tests/integration/test_app_lifespan.py tests/integration/test_conversation.py
git commit -m "test: интеграционные тесты берут единый SECRET_KEY"
```

---

## Task 7: Локальные файлы, шаблон и мусор

**Files:**
- Modify: `.env`, `.env.test`, `.env.example`, `.gitignore`
- Delete: `.env.test.example`, `frontend/.env.test`

- [ ] **Step 1: Убрать сервисный ключ из `.env.test` и оставить только переопределения**

`.env.test` (файл в гитигноре; значения `TEST_USER_PASSWORD` переносятся из текущего файла без изменений) привести к виду:

```
# Переопределения поверх .env для тестов. Файл в .gitignore.
# Живой Telegram в тестах не используется — апп подменяется заглушкой.
TELEGRAM_API_ID=1
TELEGRAM_API_HASH=test-api-hash
# Общий пароль тестовых учёток: логин в e2e (frontend/e2e/helpers.ts)
TEST_USER_PASSWORD=<текущее значение из этого файла>
```

Сервисный ключ (`TEST_SUPABASE_SERVICE_ROLE_KEY`) из файла убирается: он нужен только `scripts/test_env_bootstrap.py` и передаётся тому явно. Значение сохранить у себя (менеджер паролей) — в репозиторий и в `.env.example` оно не попадает.

- [ ] **Step 2: Убедиться, что `.env` менять не нужно**

Run: `cut -d= -f1 .env | grep -v '^#' | grep -v '^$' | sort`
Expected: `CORS_ALLOW_ORIGINS`, `DATABASE_CONNECTION_STRING`, `MEM0_API_KEY`, `OPENROUTER_API_KEY`, `SECRET_KEY`, `SUPABASE_URL`, `TELEGRAM_API_HASH`, `TELEGRAM_API_ID` — имена уже нужные, значения не трогаются.

- [ ] **Step 3: Переписать шаблон**

`.env.example` привести к виду:

```
# Шаблон backend-конфигурации (в гите только имена, без значений).
# Скопировать в .env (файл в .gitignore) и заполнить.
# Локальный .env смотрит в проект Mimic42 Dev; прод-значения живут только
# в /etc/mimic42.env на сервере и в репозиторий не попадают.

# --- база: её читают и приложение, и тесты --------------------------------

# Адрес проекта Supabase, например https://xyzcompany.supabase.co
SUPABASE_URL=
# Строка подключения SQLAlchemy, например
# postgresql+asyncpg://postgres:PASSWORD@db.xyz.supabase.co:5432/postgres
DATABASE_CONNECTION_STRING=
# Долгосрочная память
MEM0_API_KEY=
# Провайдер модели
OPENROUTER_API_KEY=
# Ключ Fernet для шифрования телеграм-сессий в базе. ОБЯЗАН совпадать с тем,
# которым уже зашифрованы сохранённые сессии, иначе агенты не восстановятся
# после перезапуска.
SECRET_KEY=
# Общепроектное телеграм-приложение (onboarding берёт его по умолчанию)
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
# Разрешённые браузерные источники. Локально нужны оба, в проде один:
# https://mimic42.zomb.top
CORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# --- .env.test: только переопределения для тестов (файл в .gitignore) ------
# Его грузят pytest, тестовый сервер и Playwright — сами, без `source`.
#
# TELEGRAM_API_ID=1
# TELEGRAM_API_HASH=test-api-hash
# TEST_USER_PASSWORD=
#
# Публичный anon-ключ в корневых файлах не нужен: локально он берётся из
# frontend/.env.local, а в CI приходит секретом SUPABASE_ANON_KEY.
#
# Сервисный ключ Dev-проекта в файлах не хранится: он нужен ровно одному
# скрипту и передаётся ему явно:
#   TEST_SUPABASE_SERVICE_ROLE_KEY=... uv run python scripts/test_env_bootstrap.py
```

- [ ] **Step 4: Удалить мёртвое**

```bash
git rm .env.test.example frontend/.env.test
```

- [ ] **Step 5: Почистить `.gitignore`**

Убрать строку `!.env.template` (файла нет и не было) и `!.env.test.example` (шаблон удалён), оставив:

```
.env
.env.*
!.env.example
```

- [ ] **Step 6: Проверить, что игнор работает и дублей имён в файлах нет**

Run:
```bash
git check-ignore -v .env .env.test
grep -rn "TEST_SUPABASE\|TEST_SECRET\|TEST_DATABASE\|TEST_TELEGRAM" .env .env.test .env.example || echo "дублей нет"
```
Expected: `.env` и `.env.test` игнорируются; `дублей нет`.

- [ ] **Step 7: Коммит**

```bash
git add -A .env.example .gitignore
git commit -m "chore: один шаблон env, .env.test только с переопределениями, удалён мёртвый frontend/.env.test"
```

---

## Task 8: Playwright — те же файлы через dotenv

**Files:**
- Modify: `frontend/package.json`, `frontend/bun.lock`
- Modify: `frontend/playwright.config.ts:1-37`

- [ ] **Step 1: Объявить dotenv явно**

Run: `cd frontend && bun add -d dotenv`
Expected: `dotenv` появляется в `devDependencies` (он уже есть в дереве как транзитивный, новых загрузок не будет).

- [ ] **Step 2: Переписать загрузку и имена**

Начало `frontend/playwright.config.ts` (до `export default defineConfig`) привести к виду:

```ts
import { config as loadDotenv } from 'dotenv';
import { defineConfig, devices } from '@playwright/test';

// Console output should not be duplicated by dotenv for every variable.
loadDotenv({ path: '../.env', quiet: true });
// Порядок как у backend-тестов: .env — база, .env.test — переопределения
// (заглушки телеги, пароль тестовых учёток).
loadDotenv({ path: '../.env.test', override: true, quiet: true });
// frontend/.env.local — локальный публичный конфиг фронта: отсюда берётся
// anon-ключ, которого нет в корневых файлах. В CI его нет, значение приходит
// из секрета SUPABASE_ANON_KEY.
loadDotenv({ path: '.env.local', quiet: true });

const APP_PORT = Number(process.env.E2E_APP_PORT ?? 3000);
const APP_URL = `http://127.0.0.1:${APP_PORT}`;
const API_PORT = Number(process.env.E2E_API_PORT ?? 8000);
const API_URL = `http://127.0.0.1:${API_PORT}`;

function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} не задан — источник .env/.env.test перед запуском e2e`);
  }
  return value;
}

// Allowlist: e2e — единственный слой, который логинится в настоящую
// Supabase Auth, поэтому адрес обязан указывать на Dev-проект. Иначе
// уведённая переменная окружения отправила бы реальные сессии в чужой проект.
const DEV_PROJECT_REF = 'ipqylrdmmjitemjrygej';

function requiredDevSupabaseUrl(): string {
  const url = requiredEnv('SUPABASE_URL');
  if (!url.includes(DEV_PROJECT_REF)) {
    throw new Error(`SUPABASE_URL не указывает на Dev-проект (${DEV_PROJECT_REF})`);
  }
  return url;
}

// Настоящий проект Mimic42 Dev: фронт ходит в настоящую Supabase Auth, а
// API — в mimic42.testing.server:app, поднятый ниже поверх настоящей базы.
const testEnv = {
  NEXT_PUBLIC_SUPABASE_URL: requiredDevSupabaseUrl(),
  NEXT_PUBLIC_SUPABASE_ANON_KEY:
    process.env.SUPABASE_ANON_KEY ?? requiredEnv('NEXT_PUBLIC_SUPABASE_ANON_KEY'),
  NEXT_PUBLIC_API_BASE_URL: API_URL,
};
```

Остальное в файле (`export default defineConfig`, `webServer`, проекты) не меняется.

- [ ] **Step 3: Проверить типы и отсутствие старых имён**

Run:
```bash
cd frontend && bunx tsc --noEmit && grep -rn "TEST_SUPABASE\|TEST_USER_PASSWORD" e2e playwright.config.ts
```
Expected: `tsc` чист; из `e2e` находится только `TEST_USER_PASSWORD` (он остаётся тестовым именем).

- [ ] **Step 4: Прогнать e2e без сорса**

Run: `cd frontend && bun run test:e2e 2>&1 | tail -5`
Expected: `39 passed` (число может отличаться на единицу, если тесты менялись) — и главное, запуск прошёл **без** `source .env.test`.

- [ ] **Step 5: Коммит**

```bash
git add frontend/package.json frontend/bun.lock frontend/playwright.config.ts
git commit -m "test(e2e): Playwright грузит .env и .env.test сам, имена общие"
```

---

## Task 9: CI — имена секретов

**Files:**
- Modify: `.github/workflows/ci.yml:70-79`, `.github/workflows/ci.yml:154-165`, `.github/workflows/ci.yml:189-210`

- [ ] **Step 1: Джоба `backend-db`**

Блок `env:` у шага «Tests against Dev database» привести к виду:

```yaml
        env:
          DATABASE_CONNECTION_STRING: ${{ secrets.DATABASE_CONNECTION_STRING }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SECRET_KEY: ${{ secrets.SECRET_KEY }}
          TEST_USER_PASSWORD: ${{ secrets.TEST_USER_PASSWORD }}
          TELEGRAM_API_ID: '1'
          TELEGRAM_API_HASH: test-api-hash
```

- [ ] **Step 2: Джоба `e2e`**

Блок `env:` у шага «Run Playwright tests» привести к виду:

```yaml
        env:
          CI: true
          DATABASE_CONNECTION_STRING: ${{ secrets.DATABASE_CONNECTION_STRING }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_ANON_KEY: ${{ secrets.SUPABASE_ANON_KEY }}
          SECRET_KEY: ${{ secrets.SECRET_KEY }}
          TEST_USER_PASSWORD: ${{ secrets.TEST_USER_PASSWORD }}
          TELEGRAM_API_ID: '1'
          TELEGRAM_API_HASH: test-api-hash
```

- [ ] **Step 3: Джоба `migrations-drift`**

В двух шагах («Link Supabase project» и «Compare local migrations with Dev») заменить ссылку на пароль:

```yaml
          SUPABASE_DB_PASSWORD: ${{ secrets.SUPABASE_DB_PASSWORD }}
```

- [ ] **Step 4: Убедиться, что старых имён в воркфлоу не осталось**

Run: `grep -n "TEST_SUPABASE\|TEST_SECRET\|TEST_DATABASE\|TEST_TELEGRAM\|TEST_DB_PASSWORD" .github/workflows/*.yml`
Expected: пусто.

- [ ] **Step 5: Коммит**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: секреты под общими именами"
```

---

## Task 10: README и комментарий в deploy

**Files:**
- Modify: `README.md:40-70`
- Modify: `deploy/deploy.sh:4-5`

- [ ] **Step 1: Раздел про тесты в README**

После блока с `uv sync --all-groups` и командами разработки добавить секцию:

```markdown
## Тесты

```bash
uv run pytest                  # 141 тест без базы, ~30 секунд
uv run pytest -m db            # 38 тестов против настоящей базы Mimic42 Dev, ~6 минут
cd frontend && bunx tsc --noEmit && bun test
cd frontend && bun run test:e2e
```

`.env` и `.env.test` тесты грузят сами — `source` не нужен. Локальный `.env`
указывает на проект **Mimic42 Dev**; прод-значения живут только в
`/etc/mimic42.env` на сервере и в репозиторий не попадают.

Тесты против базы помечены маркером `db` и по умолчанию исключены: они занимают
слот тестовых учёток и чистят данные своего слота перед прогоном, поэтому
запускаются только явным `-m db`. Если настройки не заданы, такой запуск падает
с объяснением, а не отчитывается зелёным.

Сервисный ключ Dev-проекта в env-файлах не хранится: он нужен только разовой
подготовке учёток:

```bash
TEST_SUPABASE_SERVICE_ROLE_KEY=... uv run python scripts/test_env_bootstrap.py
```
```

Список имён переменных окружения ниже в README оставить как есть — он уже описывает общие имена.

- [ ] **Step 2: Поправить имя файла секретов в deploy**

В `deploy/deploy.sh` заменить комментарий:

```bash
# - Atomically writes IMAGE_TAG into .env (compose-level variables only;
#   secrets live in /etc/mimic42.env and are never touched here).
```

- [ ] **Step 3: Коммит**

```bash
git add README.md deploy/deploy.sh
git commit -m "docs: раздел про тесты и правильное имя файла прод-секретов"
```

---

## Task 11: Полная проверка и PR

**Files:**
- Проверка, без изменений кода

- [ ] **Step 1: Линт, типы, юнит-тесты**

Run:
```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q
```
Expected: чисто; `141 passed, 38 deselected`.

- [ ] **Step 2: Тесты против базы**

Run: `uv run pytest -q -m db`
Expected: `38 passed` (~6 минут).

- [ ] **Step 3: Фронтенд**

Run: `cd frontend && bunx tsc --noEmit && bun test && bun run test:e2e 2>&1 | tail -3`
Expected: типы чисты, `67 passed` в юнит-тестах, e2e зелёные без `source`.

- [ ] **Step 4: Дублей имён не осталось нигде**

Run:
```bash
grep -rn "TEST_SUPABASE\|TEST_SECRET\|TEST_DATABASE\|TEST_TELEGRAM\|TEST_DB_PASSWORD" --include=*.py --include=*.ts --include=*.yml --include=*.toml --include=*.md . | grep -v '/.venv/' | grep -v '/docs/superpowers/' || echo "чисто"
```
Expected: `чисто`.

- [ ] **Step 5: Push и PR**

```bash
git push -u origin chore/env-vocabulary
cat > /tmp/opencode/pr-env-body.md <<'EOF'
## Что сделано

Единый словарь переменных окружения вместо трёх параллельных: `TEST_*`-дубли
убраны, имён стало два типа — общие и `NEXT_PUBLIC_*` (его требует Next).

- Файлов пять вместо семи: `.env` (база и для приложения, и для тестов),
  `.env.test` (только переопределения: заглушки телеги и пароль тестовых учёток),
  `.env.example` (единственный шаблон), `frontend/.env.local` и его шаблон.
  Удалены мёртвый `frontend/.env.test` и `.env.test.example`.
- Тесты грузят `.env`/`.env.test` сами (`mimic42.testing.env`): pytest, тестовый
  сервер, `slot_cli`, bootstrap и Playwright. `source` больше не нужен.
- db-тесты включаются только явным `-m db` (`addopts`), а при отсутствии настроек
  падают с объяснением, вместо тихого скипа.
- Единый `SECRET_KEY`: тесты и приложение шифруют строки в одной базе одним ключом —
  причина `InvalidToken` при старте убрана.
- Секреты GitHub переименованы в общие имена; старые удаляются после мерджа.
- Попутно закрыт красный `uv run pytest` из README: два теста в
  `tests/integration/test_testing_server.py` падали с `KeyError`.

## Проверка

- `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check` — чисто
- `uv run pytest` — 141 passed, 38 deselected
- `uv run pytest -m db` — 38 passed против Dev
- `cd frontend && bunx tsc --noEmit && bun test` — чисто, 67 passed
- `cd frontend && bun run test:e2e` — зелёные без ручного `source`
EOF
gh pr create --repo 42-Z/Mimic42 --base main --title "chore: единый словарь переменных окружения" --body-file /tmp/opencode/pr-env-body.md
```
Expected: ссылка на созданный PR.

- [ ] **Step 6: Дождаться всех пяти джоб**

Run: `gh pr checks --repo 42-Z/Mimic42`
Expected: `backend`, `backend-db`, `frontend`, `e2e`, `migrations-drift` — все `pass`.

- [ ] **Step 7: После мерджа удалить старые имена секретов**

```bash
for name in TEST_DATABASE_CONNECTION_STRING TEST_SUPABASE_URL TEST_SUPABASE_ANON_KEY TEST_SECRET_KEY TEST_DB_PASSWORD; do
  gh secret delete "$name" --repo 42-Z/Mimic42
done
```
Expected: пять строк `✓ Deleted Actions secret NAME`. `TEST_SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ACCESS_TOKEN`, `TEST_USER_PASSWORD` и `DEPLOY_*` остаются на месте — по решению владельца репозитория.
