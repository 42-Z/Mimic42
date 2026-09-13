# Тестовая база и живой бэкенд — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести тесты хранилища на настоящую Postgres-базу проекта Mimic42 Dev, заставить браузерные тесты работать против настоящего бэкенда и собрать четыре разрозненные подделки Telegram в одну сменную.

**Architecture:** Прод-код получает швы — необязательные параметры-фабрики в `create_app` и `AgentManager`, по умолчанию равные сегодняшним реализациям. Всё тестовое живёт в новом пакете `src/mimic42/testing/`: подделка телеги с общим состоянием, сценарные ответы модели, аренда слота тестовых аккаунтов, тестовая точка входа сервера. Тесты и Playwright подключаются к облачному Dev-проекту; параллельные прогоны разводятся арендой слота.

**Tech Stack:** Python 3.13, uv, pytest + pytest-asyncio, SQLAlchemy async + asyncpg, FastAPI, Telethon, Supabase (облачный Dev-проект), Bun + Next.js 14 + Playwright.

**Spec:** `docs/superpowers/specs/2026-09-13-test-database-design.md`

## Global Constraints

- Проект Dev: ref `ipqylrdmmjitemjrygej`. Прод: ref `ajcznltdbwvhmhgzufzv` — не трогать ничем в этом плане.
- Все команды Python — через `uv run`. Линт `uv run ruff check .`, формат `uv run ruff format .`, типы `uv run ty check`.
- Ruff: line-length 100, target py313, правила `E,F,I,B,UP,ANN`. Аннотации типов обязательны везде, включая тесты.
- Фронтенд — через `bun`, рабочий каталог `frontend/`.
- Ветка: `feat/test-database` (уже создана, в ней лежит спека). Коммит после каждой задачи.
- PR не открывать до живой проверки пользователем.
- Секреты не коммитить. Реальные значения — только в `.env.test` (gitignored) и в секретах GitHub.
- Тексты в коде и тестах — на русском там, где они уже на русском (сообщения онбординга, интерфейс).

## Порядок и зависимости

Задачи 1→2→3→4 идут строго по порядку (инфраструктура, потом аренда, потом фикстуры, потом переезд тестов).
Линия подделки и живого сервера: 5→6→**9**→7→8→10. Задача 9 (сценарные ответы модели) идёт раньше задачи 7, потому что тестовый сервер импортирует из неё фабрику. Внутри задачи 9 сперва делается сам модуль `llm.py`, а её тесты устойчивости дописываются уже после задачи 7 — они поднимают тестовый сервер.

Задача 11 опирается на 7 и 10. Задача 12 — последняя.

---

### Task 1: Инфраструктура Dev-проекта

**Files:**
- Create: `scripts/test_env_bootstrap.py`
- Create: `.env.test.example`
- Modify: `.gitignore`
- Modify: `frontend/package.json` (скрипт `generate:types` — сверить project-id)

**Interfaces:**
- Consumes: ничего.
- Produces: схема `test_support` с таблицей `slot_leases` в Dev; десять пользователей в `auth.users` Dev (два слота × пять персон); файл `.env.test.example` с именами переменных `TEST_DATABASE_CONNECTION_STRING`, `TEST_SUPABASE_URL`, `TEST_SUPABASE_ANON_KEY`, `TEST_SUPABASE_SERVICE_ROLE_KEY`, `TEST_SECRET_KEY`, `TEST_TELEGRAM_API_ID`, `TEST_TELEGRAM_API_HASH`, `TEST_USER_PASSWORD`.

- [ ] **Step 1: Перепривязать CLI с прода на Dev**

Сейчас `supabase/.temp/project-ref` содержит ref прода, то есть `supabase db push` уезжает в прод.

```bash
supabase link --project-ref ipqylrdmmjitemjrygej
cat supabase/.temp/project-ref
```

Ожидается: `ipqylrdmmjitemjrygej`.

- [ ] **Step 2: Накатить отставшую миграцию в Dev**

```bash
supabase migration list --linked
```

Ожидается: `20260909120000_activity_log_indexes` числится локально, но не в Remote.

```bash
supabase db push
supabase migration list --linked
```

Ожидается: все семь миграций и локально, и удалённо.

Прод в этом плане не трогаем. Отметить пользователю отдельно, что прод отстаёт на ту же миграцию.

- [ ] **Step 3: Написать `.env.test.example`**

```bash
cat > .env.test.example <<'EOF'
# Настройки тестового окружения. Скопировать в .env.test и заполнить.
# Всё указывает на проект Mimic42 Dev (ipqylrdmmjitemjrygej), никогда на прод.

# Подключение к Postgres Dev-проекта (драйвер asyncpg подставляется автоматически)
TEST_DATABASE_CONNECTION_STRING=
# Адрес Dev-проекта, например https://ipqylrdmmjitemjrygej.supabase.co
TEST_SUPABASE_URL=
# Публикуемый ключ Dev-проекта — им логинится браузер в тестах
TEST_SUPABASE_ANON_KEY=
# Сервисный ключ Dev-проекта. Нужен ТОЛЬКО скрипту scripts/test_env_bootstrap.py.
# В обычные прогоны и в CI не передаётся.
TEST_SUPABASE_SERVICE_ROLE_KEY=
# Отдельный ключ шифрования сессий телеги для тестов (не прод-ключ).
# Сгенерировать: uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TEST_SECRET_KEY=
# Заглушки телеграм-приложения: живая телега в этом наборе не используется
TEST_TELEGRAM_API_ID=1
TEST_TELEGRAM_API_HASH=test-api-hash
# Общий пароль всех тестовых учёток
TEST_USER_PASSWORD=
EOF
```

- [ ] **Step 4: Добавить `.env.test` в игнорируемые**

В `.gitignore` строка `.env.*` уже есть, но её перекрывают исключения. Проверить, что `.env.test` игнорируется:

```bash
git check-ignore -v .env.test
```

Если не игнорируется — добавить в секцию «Secrets and local configuration» строку `.env.test`.

- [ ] **Step 5: Написать скрипт подготовки окружения**

```python
# scripts/test_env_bootstrap.py
"""Идемпотентно готовит проект Mimic42 Dev к тестам.

Создаёт схему test_support с таблицей аренды слотов и заводит
тестовые учётки через Admin API GoTrue. Запускается руками, требует
TEST_SUPABASE_SERVICE_ROLE_KEY. Повторный запуск ничего не ломает.
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg
import httpx

from mimic42.testing.slots import SLOTS

CREATE_SCHEMA_SQL = """
create schema if not exists test_support;

create table if not exists test_support.slot_leases (
    slot        text primary key,
    holder      text,
    acquired_at timestamptz,
    expires_at  timestamptz
);
"""


async def ensure_schema(dsn: str) -> None:
    connection = await asyncpg.connect(dsn)
    try:
        await connection.execute(CREATE_SCHEMA_SQL)
        for slot in SLOTS:
            await connection.execute(
                "insert into test_support.slot_leases (slot) values ($1) "
                "on conflict (slot) do nothing",
                slot.name,
            )
    finally:
        await connection.close()


async def ensure_users(supabase_url: str, service_key: str, password: str) -> None:
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=supabase_url.rstrip("/"), timeout=30.0) as client:
        for slot in SLOTS:
            for persona in slot.personas:
                response = await client.post(
                    "/auth/v1/admin/users",
                    headers=headers,
                    json={
                        "id": str(persona.user_id),
                        "email": persona.email,
                        "password": password,
                        "email_confirm": True,
                    },
                )
                if response.status_code in (200, 201):
                    print(f"создан {persona.email}")
                elif response.status_code in (409, 422):
                    print(f"уже есть {persona.email}")
                else:
                    raise RuntimeError(
                        f"не удалось создать {persona.email}: "
                        f"{response.status_code} {response.text}"
                    )


async def main() -> int:
    dsn = os.environ["TEST_DATABASE_CONNECTION_STRING"]
    supabase_url = os.environ["TEST_SUPABASE_URL"]
    service_key = os.environ["TEST_SUPABASE_SERVICE_ROLE_KEY"]
    password = os.environ["TEST_USER_PASSWORD"]
    if "ajcznltdbwvhmhgzufzv" in dsn or "ajcznltdbwvhmhgzufzv" in supabase_url:
        raise SystemExit("отказ: настройки указывают на прод")
    await ensure_schema(_plain_dsn(dsn))
    await ensure_users(supabase_url, service_key, password)
    return 0


def _plain_dsn(value: str) -> str:
    """asyncpg не понимает префикс SQLAlchemy."""
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

Скрипт зависит от `mimic42.testing.slots.SLOTS` из задачи 2 — поэтому запускается после неё.

- [ ] **Step 6: Сверить project-id в генерации типов**

```bash
grep -n "generate:types" frontend/package.json
```

Там должен стоять `ipqylrdmmjitemjrygej`. Если стоит другой — исправить.

- [ ] **Step 7: Коммит**

```bash
git add scripts/test_env_bootstrap.py .env.test.example .gitignore frontend/package.json
git commit -m "chore(test): подготовка Dev-проекта под тесты"
```

---

### Task 2: Слоты тестовых аккаунтов и очистка данных

**Files:**
- Create: `src/mimic42/testing/__init__.py`
- Create: `src/mimic42/testing/slots.py`
- Create: `src/mimic42/testing/cleanup.py`
- Test: `tests/integration/__init__.py`, `tests/integration/test_slots.py`, `tests/integration/test_cleanup.py`

**Interfaces:**
- Consumes: схему `test_support.slot_leases` из задачи 1.
- Produces:
  - `Persona(key: str, user_id: UUID, email: str)` — dataclass.
  - `Slot(name: str, personas: tuple[Persona, ...])` — dataclass; `Slot.persona(key: str) -> Persona`.
  - `SLOTS: tuple[Slot, ...]` — два слота по пять персон с ключами `empty`, `full`, `flow`, `twofa`, `code`.
  - `async def acquire_slot(dsn: str, *, holder: str, ttl_seconds: int = 1800, wait_timeout: int = 600) -> Slot`
  - `async def release_slot(dsn: str, slot: Slot) -> None`
  - `async def purge_slot_data(dsn: str, slot: Slot) -> None`

- [ ] **Step 1: Написать падающий тест на аренду**

```python
# tests/integration/test_slots.py
from __future__ import annotations

import os

import pytest

from mimic42.testing.slots import SLOTS, acquire_slot, release_slot

pytestmark = pytest.mark.db

DSN = os.environ.get("TEST_DATABASE_CONNECTION_STRING", "")


async def test_two_holders_get_different_slots() -> None:
    first = await acquire_slot(DSN, holder="first", wait_timeout=5)
    second = await acquire_slot(DSN, holder="second", wait_timeout=5)
    try:
        assert first.name != second.name
    finally:
        await release_slot(DSN, first)
        await release_slot(DSN, second)


async def test_third_holder_waits_and_fails_by_timeout() -> None:
    first = await acquire_slot(DSN, holder="first", wait_timeout=5)
    second = await acquire_slot(DSN, holder="second", wait_timeout=5)
    try:
        with pytest.raises(TimeoutError):
            await acquire_slot(DSN, holder="third", wait_timeout=2)
    finally:
        await release_slot(DSN, first)
        await release_slot(DSN, second)


async def test_expired_lease_is_reclaimed() -> None:
    stale = await acquire_slot(DSN, holder="stale", ttl_seconds=-1, wait_timeout=5)
    try:
        reclaimed = await acquire_slot(DSN, holder="fresh", wait_timeout=5)
        assert reclaimed.name == stale.name
        await release_slot(DSN, reclaimed)
    finally:
        await release_slot(DSN, stale)


async def test_every_slot_has_five_personas() -> None:
    assert len(SLOTS) == 2
    for slot in SLOTS:
        assert {persona.key for persona in slot.personas} == {
            "empty",
            "full",
            "flow",
            "twofa",
            "code",
        }
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `uv run pytest tests/integration/test_slots.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'mimic42.testing'`.

- [ ] **Step 3: Реализовать слоты**

```python
# src/mimic42/testing/slots.py
"""Аренда набора тестовых учёток: база одна на всех, слотов несколько."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg

PERSONA_KEYS = ("empty", "full", "flow", "twofa", "code")


@dataclass(frozen=True)
class Persona:
    key: str
    user_id: UUID
    email: str


@dataclass(frozen=True)
class Slot:
    name: str
    personas: tuple[Persona, ...]

    def persona(self, key: str) -> Persona:
        for persona in self.personas:
            if persona.key == key:
                return persona
        raise KeyError(f"В слоте {self.name} нет персоны {key}")


def _build_slot(name: str, digit: str, suffix: str) -> Slot:
    personas = tuple(
        Persona(
            key=key,
            user_id=UUID(f"{digit * 8}-{digit * 4}-{digit * 4}-{digit * 4}-{index:012d}"),
            email=f"e2e-{key}{suffix}@mimic42.test",
        )
        for index, key in enumerate(PERSONA_KEYS, start=1)
    )
    return Slot(name=name, personas=personas)


SLOTS: tuple[Slot, ...] = (
    _build_slot("a", "1", ""),
    _build_slot("b", "2", "-b"),
)


def plain_dsn(value: str) -> str:
    """asyncpg не понимает префикс драйвера из строки SQLAlchemy."""
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


async def acquire_slot(
    dsn: str,
    *,
    holder: str,
    ttl_seconds: int = 1800,
    wait_timeout: int = 600,
) -> Slot:
    deadline = datetime.now(UTC) + timedelta(seconds=wait_timeout)
    while True:
        taken = await _try_acquire(dsn, holder=holder, ttl_seconds=ttl_seconds)
        if taken is not None:
            return taken
        if datetime.now(UTC) >= deadline:
            raise TimeoutError(
                "Все слоты тестовых аккаунтов заняты: дождитесь окончания другого прогона"
            )
        await asyncio.sleep(2)


async def _try_acquire(dsn: str, *, holder: str, ttl_seconds: int) -> Slot | None:
    connection = await asyncpg.connect(plain_dsn(dsn))
    try:
        row = await connection.fetchrow(
            """
            update test_support.slot_leases
               set holder = $1,
                   acquired_at = now(),
                   expires_at = now() + make_interval(secs => $2)
             where slot = (
                 select slot
                   from test_support.slot_leases
                  where holder is null or expires_at < now()
                  order by slot
                    for update skip locked
                  limit 1
             )
            returning slot
            """,
            holder,
            float(ttl_seconds),
        )
    finally:
        await connection.close()
    if row is None:
        return None
    return next(slot for slot in SLOTS if slot.name == row["slot"])


async def release_slot(dsn: str, slot: Slot) -> None:
    connection = await asyncpg.connect(plain_dsn(dsn))
    try:
        await connection.execute(
            "update test_support.slot_leases "
            "set holder = null, acquired_at = null, expires_at = null where slot = $1",
            slot.name,
        )
    finally:
        await connection.close()
```

- [ ] **Step 4: Прогнать тесты аренды**

```bash
uv run python scripts/test_env_bootstrap.py   # создаст схему и учётки
uv run pytest tests/integration/test_slots.py -v
```

Expected: PASS.

- [ ] **Step 5: Написать падающий тест на очистку**

Главное здесь — что очистка не трогает чужое. Тест создаёт агента у персоны своего слота и агента у персоны чужого слота, чистит свой слот и проверяет, что чужой цел.

```python
# tests/integration/test_cleanup.py
from __future__ import annotations

import os
from uuid import uuid4

import asyncpg
import pytest

from mimic42.testing.cleanup import purge_slot_data
from mimic42.testing.slots import SLOTS, plain_dsn

pytestmark = pytest.mark.db

DSN = os.environ.get("TEST_DATABASE_CONNECTION_STRING", "")


async def _insert_agent(connection: asyncpg.Connection, owner_id: object, name: str) -> object:
    agent_id = uuid4()
    await connection.execute(
        "insert into public.agents (id, owner_id, name, soul_markdown, state) "
        "values ($1, $2, $3, 'тест', 'stopped')",
        agent_id,
        owner_id,
        name,
    )
    return agent_id


async def test_purge_removes_own_slot_and_keeps_the_other() -> None:
    own, other = SLOTS[0], SLOTS[1]
    connection = await asyncpg.connect(plain_dsn(DSN))
    try:
        own_agent = await _insert_agent(connection, own.persona("full").user_id, "свой")
        other_agent = await _insert_agent(connection, other.persona("full").user_id, "чужой")

        await purge_slot_data(DSN, own)

        assert await connection.fetchval(
            "select count(*) from public.agents where id = $1", own_agent
        ) == 0
        assert await connection.fetchval(
            "select count(*) from public.agents where id = $1", other_agent
        ) == 1
    finally:
        await connection.execute(
            "delete from public.agents where owner_id = $1", other.persona("full").user_id
        )
        await connection.close()


async def test_purge_keeps_the_user_accounts_themselves() -> None:
    slot = SLOTS[0]
    await purge_slot_data(DSN, slot)
    connection = await asyncpg.connect(plain_dsn(DSN))
    try:
        for persona in slot.personas:
            assert await connection.fetchval(
                "select count(*) from auth.users where id = $1", persona.user_id
            ) == 1
            assert await connection.fetchval(
                "select count(*) from public.profiles where id = $1", persona.user_id
            ) == 1
    finally:
        await connection.close()
```

- [ ] **Step 6: Запустить и убедиться, что падает**

Run: `uv run pytest tests/integration/test_cleanup.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'mimic42.testing.cleanup'`.

- [ ] **Step 7: Реализовать очистку**

Учётку и профиль не удаляем — иначе пришлось бы каждый раз создавать их заново. Удаляем всё, что к ним прицеплено: агенты (каскадом уносят сессии телеги, ветки, сообщения, события, таймеры) и черновики онбординга.

```python
# src/mimic42/testing/cleanup.py
"""Очистка данных тестового слота. Выполняется ПЕРЕД прогоном,
чтобы после падения состояние можно было посмотреть глазами."""

from __future__ import annotations

import asyncpg

from mimic42.testing.slots import Slot, plain_dsn


async def purge_slot_data(dsn: str, slot: Slot) -> None:
    owner_ids = [persona.user_id for persona in slot.personas]
    connection = await asyncpg.connect(plain_dsn(dsn))
    try:
        async with connection.transaction():
            await connection.execute(
                "delete from public.agent_onboarding_sessions where owner_id = any($1::uuid[])",
                owner_ids,
            )
            await connection.execute(
                "delete from public.agents where owner_id = any($1::uuid[])",
                owner_ids,
            )
    finally:
        await connection.close()
```

- [ ] **Step 8: Прогнать оба набора тестов**

Run: `uv run pytest tests/integration -v`
Expected: PASS.

- [ ] **Step 9: Коммит**

```bash
git add src/mimic42/testing tests/integration
git commit -m "feat(test): аренда слота тестовых аккаунтов и очистка данных"
```

---

### Task 3: Фикстуры pytest и маркер db

**Files:**
- Create: `conftest.py` (в корне репозитория)
- Modify: `pyproject.toml` (секция `[tool.pytest.ini_options]`)

**Interfaces:**
- Consumes: `acquire_slot`, `release_slot`, `purge_slot_data`, `SLOTS` из задачи 2; `create_engine`, `create_session_factory` из `src/mimic42/integrations/database_session.py`.
- Produces: фикстуры `test_dsn` (str), `test_slot` (Slot, scope=session), `db_engine` (AsyncEngine, scope=session), `db_session_factory` (`async_sessionmaker[AsyncSession]`), `clean_slot` (автоочистка перед тестом); маркер `db`.

- [ ] **Step 1: Зарегистрировать маркер и пути в pyproject**

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "db: требует подключения к тестовой базе Mimic42 Dev",
]
```

- [ ] **Step 2: Написать conftest**

```python
# conftest.py
"""Общие фикстуры. Тесты с маркером db работают против настоящей
базы проекта Mimic42 Dev и занимают слот тестовых аккаунтов."""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from mimic42.integrations.database_session import create_engine, create_session_factory
from mimic42.testing.cleanup import purge_slot_data
from mimic42.testing.slots import Slot, acquire_slot, release_slot

PROD_REF = "ajcznltdbwvhmhgzufzv"


@pytest.fixture(scope="session")
def test_dsn() -> str:
    dsn = os.environ.get("TEST_DATABASE_CONNECTION_STRING")
    if not dsn:
        pytest.skip("TEST_DATABASE_CONNECTION_STRING не задан: тесты на базе пропущены")
    if PROD_REF in dsn:
        pytest.fail("TEST_DATABASE_CONNECTION_STRING указывает на прод")
    return dsn


@pytest.fixture(scope="session")
async def test_slot(test_dsn: str) -> AsyncIterator[Slot]:
    holder = f"{socket.gethostname()}:{os.getpid()}"
    slot = await acquire_slot(test_dsn, holder=holder)
    try:
        yield slot
    finally:
        await release_slot(test_dsn, slot)


@pytest.fixture(scope="session")
async def db_engine(test_dsn: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(test_dsn)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def db_session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(db_engine)


@pytest.fixture
async def clean_slot(test_dsn: str, test_slot: Slot) -> AsyncIterator[Slot]:
    """Чистит данные слота ПЕРЕД тестом: после падения остатки видно."""
    await purge_slot_data(test_dsn, test_slot)
    yield test_slot


def pytest_collection_modifyitems(items: Iterator[pytest.Item]) -> None:
    """Тесты в tests/integration автоматически получают маркер db."""
    for item in items:
        if "tests/integration" in str(item.path).replace(os.sep, "/"):
            item.add_marker(pytest.mark.db)
```

- [ ] **Step 3: Убрать ручные маркеры из тестов задачи 2**

В `tests/integration/test_slots.py` и `tests/integration/test_cleanup.py` строка `pytestmark = pytest.mark.db` больше не нужна — маркер проставляется автоматически. Удалить её и неиспользуемый импорт `pytest`, если он остался без применения.

- [ ] **Step 4: Проверить оба режима**

```bash
uv run pytest -m "not db" -q          # быстрые, без сети
uv run pytest -m db -q                # на базе Dev
uv run pytest -q                      # всё вместе
```

Expected: все три зелёные. Без `TEST_DATABASE_CONNECTION_STRING` набор `-m db` должен скипаться, а не падать — проверить:

```bash
env -u TEST_DATABASE_CONNECTION_STRING uv run pytest -m db -q
```

Expected: `skipped`.

- [ ] **Step 5: Коммит**

```bash
git add conftest.py pyproject.toml tests/integration
git commit -m "feat(test): общие фикстуры и маркер db"
```

---

### Task 4: Перевод тестов хранилища с SQLite на Postgres

**Files:**
- Modify: `tests/integrations/test_database_agent_store.py:29` (фикстура engine)
- Modify: `tests/integrations/test_database_onboarding_repository.py:16`
- Modify: `tests/core/test_activity.py:37`
- Modify: `tests/api/test_agents_api.py:200` (фикстура `sqlite_session_factory`)
- Modify: `tests/core/test_agent_runtime.py:573`
- Modify: `pyproject.toml` (убрать `aiosqlite` из `[project].dependencies`)
- Create: `tests/integrations/__init__.py` (сейчас отсутствует, из-за чего пакет собирается неявно)

**Interfaces:**
- Consumes: `db_session_factory`, `clean_slot` из задачи 3.
- Produces: ничего нового; те же тесты, работающие против настоящей схемы.

- [ ] **Step 1: Перенести файлы, которые проверяют хранилище**

Три файла переезжают в `tests/integration/`, потому что теперь им нужна настоящая база:

```bash
git mv tests/integrations/test_database_agent_store.py tests/integration/test_database_agent_store.py
git mv tests/integrations/test_database_onboarding_repository.py tests/integration/test_database_onboarding_repository.py
git mv tests/core/test_activity.py tests/integration/test_activity.py
```

- [ ] **Step 2: Заменить локальную фикстуру engine на общую**

В каждом из трёх перенесённых файлов удалить блок вида

```python
engine = create_async_engine("sqlite+aiosqlite:///:memory:")

@event.listens_for(engine.sync_engine, "connect")
def _enable_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

async with engine.begin() as connection:
    await connection.run_sync(Base.metadata.create_all)
```

и все связанные импорты (`create_async_engine`, `event`, `Base`). Вместо этого тест принимает фикстуры:

```python
async def test_agent_store_persists_agent(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    store = DatabaseAgentStore(db_session_factory, cipher=PlainTextCipher())
    ...
```

- [ ] **Step 3: Заменить выдуманные идентификаторы владельцев на персон слота**

Раньше тесты брали `uuid4()` для `owner_id`, и в SQLite это проходило. В настоящей базе `agents.owner_id` ссылается на `profiles`, поэтому владельцем должна быть персона слота:

```python
owner_id = clean_slot.persona("full").user_id
```

Пройти по всем местам, где создаётся агент, черновик онбординга или событие, и подставить персону. Разным тестам внутри файла лучше брать разных персон (`full`, `empty`, `flow`), чтобы они не мешали друг другу.

- [ ] **Step 4: Прогнать и чинить то, что вскроется**

Run: `uv run pytest -m db -v`

Ожидаемые новые падения — это и есть польза задачи: ограничения на значения, которых не было в SQLite, триггеры `set_updated_at`, отличия типов. Каждое падение разобрать по существу: если ошибка в тесте — править тест, если расхождение модели и миграции — править модель или добавлять миграцию. Заплатки не делать.

- [ ] **Step 5: Оставшиеся два файла — оставить на подделках, но убрать SQLite**

`tests/api/test_agents_api.py` и `tests/core/test_agent_runtime.py` проверяют поведение, а не хранилище, и должны остаться быстрыми. Там база нужна только как приёмник истории — заменить `sqlite_session_factory` на `None`, если тест не проверяет запись, либо перенести конкретный тест в `tests/integration/`, если проверяет. Решение принимать по каждому тесту отдельно, глядя на его утверждения.

- [ ] **Step 6: Убрать aiosqlite из зависимостей**

```bash
uv remove aiosqlite
grep -rn "aiosqlite" --include=*.py --include=*.toml . | grep -v .venv
```

Expected: пусто.

- [ ] **Step 7: Прогнать всё и закоммитить**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check
uv run pytest -q
git add -A
git commit -m "test: перевести тесты хранилища на базу Dev вместо SQLite"
```

---

### Task 5: Единая подделка Telegram

**Files:**
- Create: `src/mimic42/testing/telegram/__init__.py`
- Create: `src/mimic42/testing/telegram/account.py`
- Create: `src/mimic42/testing/telegram/auth_client.py`
- Create: `src/mimic42/testing/telegram/client.py`
- Test: `tests/testing/__init__.py`, `tests/testing/test_fake_telegram.py`
- Modify (удаление дублей): `tests/core/test_onboarding_persistence.py:21`, `tests/core/test_onboarding_linkage.py:18`, `tests/api/test_onboarding_api.py:18`, `tests/core/test_agent_runtime.py:23`, `tests/integrations/test_telegram_tools.py:22`

**Interfaces:**
- Consumes: протоколы `TelegramAuthClient`, `TelegramAuthClientFactory` (`src/mimic42/core/onboarding.py:138,157`), `TelegramClientLike` (`src/mimic42/core/agent_runtime.py:82`).
- Produces:
  - `FakeTelegramAccount` — общее состояние: `phone`, `authorized`, `requires_password`, `expected_code`, `password`, `sent: list[SentMessage]`, `incoming: list[IncomingMessage]`, `read_marks: list[str]`.
    - `def script_code(self, code: str) -> None`
    - `def require_password(self, password: str) -> None`
    - `async def deliver(self, *, chat_id: int, text: str, sender_id: int = 999) -> None` — изображает входящее сообщение.
  - `FakeTelegramAuthClient`, `FakeTelegramAuthClientFactory(account: FakeTelegramAccount)` — реализуют протокол входа.
  - `FakeTelegramClient(account: FakeTelegramAccount)` — реализует `TelegramClientLike`.
  - `ACCOUNTS: dict[UUID, FakeTelegramAccount]` — реестр по `agent_id`, чтобы сервер и тест смотрели в одно состояние.

- [ ] **Step 1: Написать падающий тест на непрерывный сценарий**

Главное, чего не умеют четыре нынешние подделки: пройти вход и сразу работать тем же аккаунтом.

```python
# tests/testing/test_fake_telegram.py
from __future__ import annotations

import pytest

from mimic42.core.onboarding import TelegramPasswordRequiredError
from mimic42.testing.telegram import (
    FakeTelegramAccount,
    FakeTelegramAuthClientFactory,
    FakeTelegramClient,
)


async def test_login_then_work_share_one_account() -> None:
    account = FakeTelegramAccount()
    account.script_code("12345")

    auth = FakeTelegramAuthClientFactory(account).build(api_id=1, api_hash="hash")
    await auth.connect()
    await auth.send_code_request("+79990000000")
    await auth.sign_in(phone="+79990000000", code="12345")
    session_string = auth.save_session()

    assert account.authorized is True
    assert session_string

    client = FakeTelegramClient(account)
    assert await client.is_user_authorized() is True
    await client.send_message("42", "привет")
    assert account.sent[-1].chat_id == "42"
    assert account.sent[-1].text == "привет"


async def test_wrong_code_is_rejected() -> None:
    account = FakeTelegramAccount()
    account.script_code("12345")
    auth = FakeTelegramAuthClientFactory(account).build(api_id=1, api_hash="hash")
    await auth.send_code_request("+79990000000")

    with pytest.raises(ValueError):
        await auth.sign_in(phone="+79990000000", code="00000")
    assert account.authorized is False


async def test_two_factor_password_is_requested() -> None:
    account = FakeTelegramAccount()
    account.script_code("12345")
    account.require_password("секрет")
    auth = FakeTelegramAuthClientFactory(account).build(api_id=1, api_hash="hash")
    await auth.send_code_request("+79990000000")

    with pytest.raises(TelegramPasswordRequiredError):
        await auth.sign_in(phone="+79990000000", code="12345")

    await auth.sign_in(phone="+79990000000", code="12345", password="секрет")
    assert account.authorized is True


async def test_incoming_message_reaches_the_registered_handler() -> None:
    account = FakeTelegramAccount()
    account.authorized = True
    client = FakeTelegramClient(account)
    seen: list[str] = []

    client.add_event_handler(lambda event: _remember(seen, event))
    await account.deliver(chat_id=42, text="как дела")

    assert seen == ["как дела"]


async def _remember(seen: list[str], event: object) -> None:
    seen.append(getattr(event, "text", ""))
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `uv run pytest tests/testing/test_fake_telegram.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'mimic42.testing.telegram'`.

- [ ] **Step 3: Реализовать состояние аккаунта**

```python
# src/mimic42/testing/telegram/account.py
"""Одно состояние поддельного телеграм-аккаунта на весь сценарий:
вход, отправленное, входящее, отметки о прочтении."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SentMessage:
    chat_id: str
    text: str
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class IncomingMessage:
    chat_id: int
    message_id: int
    text: str
    sender_id: int


class FakeIncomingEvent:
    """Форма события Telethon, на которую рассчитывает рантайм."""

    def __init__(self, message: IncomingMessage, client: object) -> None:
        self.chat_id = message.chat_id
        self.sender_id = message.sender_id
        self.id = message.message_id
        self.text = message.text
        self.message = message.text
        self.client = client

    async def get_chat(self) -> object:
        return type("Chat", (), {"id": self.chat_id, "username": None})()

    async def get_reply_message(self) -> object | None:
        return None

    async def get_input_chat(self) -> object:
        return await self.get_chat()


class FakeTelegramAccount:
    def __init__(self) -> None:
        self.phone: str | None = None
        self.authorized = False
        self.expected_code: str | None = None
        self.password: str | None = None
        self.password_satisfied = True
        self.code_requested = False
        self.sent: list[SentMessage] = []
        self.incoming: list[IncomingMessage] = []
        self.read_marks: list[str] = []
        self.handlers: list[Callable[[Any], Awaitable[None]]] = []
        self._next_message_id = 1000

    def script_code(self, code: str) -> None:
        self.expected_code = code

    def require_password(self, password: str) -> None:
        self.password = password
        self.password_satisfied = False

    async def deliver(self, *, chat_id: int, text: str, sender_id: int = 999) -> None:
        self._next_message_id += 1
        message = IncomingMessage(
            chat_id=chat_id,
            message_id=self._next_message_id,
            text=text,
            sender_id=sender_id,
        )
        self.incoming.append(message)
        for handler in list(self.handlers):
            await handler(FakeIncomingEvent(message, client=self))

    async def download_media(self, message: Any, file: Any = None, **kwargs: Any) -> Any:
        return None
```

- [ ] **Step 4: Реализовать клиент входа**

```python
# src/mimic42/testing/telegram/auth_client.py
from __future__ import annotations

from mimic42.core.onboarding import TelegramPasswordRequiredError
from mimic42.testing.telegram.account import FakeTelegramAccount


class FakeTelegramAuthClient:
    def __init__(self, account: FakeTelegramAccount) -> None:
        self._account = account

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def send_code_request(self, phone: str) -> object:
        self._account.phone = phone
        self._account.code_requested = True
        return type("SentCode", (), {"phone_code_hash": "fake-hash"})()

    async def sign_in(
        self,
        *,
        phone: str | None = None,
        code: str | None = None,
        phone_code_hash: str | None = None,
        password: str | None = None,
    ) -> object:
        account = self._account
        if password is not None:
            if password != account.password:
                raise ValueError("Неверный пароль двухфакторной защиты")
            account.password_satisfied = True
            account.authorized = True
            return type("User", (), {"id": 777})()
        if account.expected_code is not None and code != account.expected_code:
            raise ValueError("Неверный код подтверждения")
        if not account.password_satisfied:
            raise TelegramPasswordRequiredError
        account.authorized = True
        return type("User", (), {"id": 777})()

    def save_session(self) -> str:
        if not self._account.authorized:
            raise RuntimeError("Сессия не создана: вход не завершён")
        return f"fake-session:{self._account.phone}"


class FakeTelegramAuthClientFactory:
    def __init__(self, account: FakeTelegramAccount) -> None:
        self._account = account

    def build(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
    ) -> FakeTelegramAuthClient:
        if session_string:
            self._account.authorized = True
        return FakeTelegramAuthClient(self._account)
```

- [ ] **Step 5: Реализовать рабочий клиент**

```python
# src/mimic42/testing/telegram/client.py
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mimic42.testing.telegram.account import FakeTelegramAccount, SentMessage


class FakeTelegramClient:
    def __init__(self, account: FakeTelegramAccount) -> None:
        self.account = account
        self.requests: list[object] = []
        self.connected = False

    async def __call__(self, request: Any) -> Any:
        self.requests.append(request)
        name = type(request).__name__
        if "ReadHistory" in name:
            self.account.read_marks.append(str(getattr(request, "peer", "")))
        return {}

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def is_user_authorized(self) -> bool:
        return self.account.authorized

    async def send_message(self, entity: str, message: str, **kwargs: Any) -> object:
        self.account.sent.append(SentMessage(chat_id=str(entity), text=message, kwargs=kwargs))
        return type("Message", (), {"id": len(self.account.sent)})()

    def add_event_handler(
        self,
        callback: Callable[[Any], Awaitable[None]],
        event: object | None = None,
    ) -> None:
        self.account.handlers.append(callback)
```

```python
# src/mimic42/testing/telegram/__init__.py
from mimic42.testing.telegram.account import (
    FakeIncomingEvent,
    FakeTelegramAccount,
    IncomingMessage,
    SentMessage,
)
from mimic42.testing.telegram.auth_client import (
    FakeTelegramAuthClient,
    FakeTelegramAuthClientFactory,
)
from mimic42.testing.telegram.client import FakeTelegramClient

__all__ = [
    "FakeIncomingEvent",
    "FakeTelegramAccount",
    "FakeTelegramAuthClient",
    "FakeTelegramAuthClientFactory",
    "FakeTelegramClient",
    "IncomingMessage",
    "SentMessage",
]
```

- [ ] **Step 6: Прогнать тесты подделки**

Run: `uv run pytest tests/testing/test_fake_telegram.py -v`
Expected: PASS.

- [ ] **Step 7: Выкинуть четыре старые подделки**

По одному файлу за раз, каждый раз прогоняя тесты:

1. `tests/core/test_onboarding_persistence.py` — удалить `FakeTelegramAuthClient` и `FakeTelegramAuthFactory`, импортировать новые.
2. `tests/core/test_onboarding_linkage.py` — то же.
3. `tests/api/test_onboarding_api.py` — то же; фабрика там наследует протокол, новая подходит по форме.
4. `tests/core/test_agent_runtime.py` — удалить `FakeTelegramClient`, `FakeIncomingEvent`, `FakeIncomingMessage`, использовать новые; `emit_message` заменяется на `account.deliver(...)`.
5. `tests/integrations/test_telegram_tools.py` — самый крупный (`FakeTelethonClient`, 1300+ строк тестов). Если его форма заметно шире, чем `FakeTelegramClient`, дополнить новый клиент недостающими методами, а не оставлять вторую подделку.

Run после каждого файла: `uv run pytest -q`

- [ ] **Step 8: Коммит**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check
git add -A
git commit -m "feat(test): одна подделка Telegram вместо четырёх"
```

---

### Task 6: Швы для подмены провайдеров в прод-коде

**Files:**
- Modify: `src/mimic42/api/app.py:150-202` (сигнатура `create_app` и тело `lifespan`)
- Modify: `src/mimic42/core/manager.py:53-65` (конструктор `AgentManager`), `:200-220` (`_build_runtime_with_memory`)
- Test: `tests/api/test_app_factories.py`

**Interfaces:**
- Consumes: `FakeTelegramAuthClientFactory`, `FakeTelegramClient` из задачи 5.
- Produces:
  - `create_app(..., telegram_factory: TelegramAuthClientFactory | None = None, telegram_client_factory: Callable[[AgentRuntimeConfig], TelegramClientLike] | None = None, langchain_agent_factory: LangChainAgentFactory | None = None)`.
  - `AgentManager(..., telegram_client_factory=..., langchain_agent_factory=...)`, где
    `LangChainAgentFactory = Callable[[AgentRuntimeConfig, list[BaseTool], async_sessionmaker[AsyncSession] | None], LangChainAgentLike]`.
  - Значения по умолчанию — сегодняшние: `TelethonAuthClientFactory()`, `build_telegram_client`, `build_langchain_agent`.

- [ ] **Step 1: Написать падающий тест на подмену**

```python
# tests/api/test_app_factories.py
from __future__ import annotations

from mimic42.api.app import create_app
from mimic42.config import Settings
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramAuthClientFactory


async def test_create_app_uses_injected_telegram_factory() -> None:
    account = FakeTelegramAccount()
    app = create_app(
        settings=Settings(database_connection_string=None),
        telegram_factory=FakeTelegramAuthClientFactory(account),
    )
    service = app.state.onboarding_service
    client = service._telegram_factory.build(api_id=1, api_hash="hash")
    await client.send_code_request("+79990000000")
    assert account.phone == "+79990000000"


def test_create_app_defaults_to_telethon() -> None:
    from mimic42.integrations.telegram_auth import TelethonAuthClientFactory

    app = create_app(settings=Settings(database_connection_string=None))
    assert isinstance(app.state.onboarding_service._telegram_factory, TelethonAuthClientFactory)
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `uv run pytest tests/api/test_app_factories.py -v`
Expected: FAIL, `TypeError: create_app() got an unexpected keyword argument 'telegram_factory'`.

- [ ] **Step 3: Добавить параметры в `create_app`**

В сигнатуру добавить три необязательных параметра. В теле:

```python
    app_telegram_factory = telegram_factory or TelethonAuthClientFactory()
    app_onboarding_service = onboarding_service or AgentOnboardingService(
        telegram_factory=app_telegram_factory,
        agent_store=agent_store,
    )
```

и в `lifespan`, где создаётся сервис на базе, тоже подставить `app_telegram_factory` вместо `TelethonAuthClientFactory()`. В создании `AgentManager` внутри `lifespan` пробросить `telegram_client_factory` и `langchain_agent_factory`.

- [ ] **Step 4: Добавить параметры в `AgentManager`**

В конструктор — два новых необязательных параметра; в `_build_runtime_with_memory` заменить жёсткие вызовы:

```python
    def _build_runtime_with_memory(self, config: AgentRuntimeConfig) -> MimicAgentRuntime:
        telegram_client = self._telegram_client_factory(config)
        ...
            langchain_agent=self._langchain_agent_factory(
                config,
                build_telegram_langchain_tools(
                    cast(TelethonRequestClient, telegram_client),
                    agent_id=config.agent_id,
                    session_factory=self.session_factory,
                ),
                self.session_factory,
            ),
```

где в конструкторе:

```python
        self._telegram_client_factory = telegram_client_factory or (
            lambda config: cast(TelegramClientLike, build_telegram_client(config))
        )
        self._langchain_agent_factory = langchain_agent_factory or (
            lambda config, tools, session_factory: build_langchain_agent(
                config, tools=tools, session_factory=session_factory
            )
        )
```

- [ ] **Step 5: Прогнать тесты**

Run: `uv run pytest -q`
Expected: PASS, включая все существующие тесты — умолчания не изменились.

- [ ] **Step 6: Коммит**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check
git add -A
git commit -m "feat: параметризовать фабрики Telegram и LLM в create_app и AgentManager"
```

---

### Task 7: Тестовая точка входа сервера

**Files:**
- Create: `src/mimic42/testing/server.py`
- Create: `src/mimic42/testing/registry.py`
- Test: `tests/integration/test_testing_server.py`

**Interfaces:**
- Consumes: швы из задачи 6, подделку из задачи 5, слоты из задачи 2.
- Produces:
  - `registry.account_for(agent_id: UUID) -> FakeTelegramAccount` — один аккаунт на агента, создаётся по требованию; `registry.reset() -> None`.
  - `build_test_app(settings: Settings | None = None) -> FastAPI` — приложение с настоящей базой и поддельными провайдерами.
  - `app` — готовый экземпляр для `uvicorn mimic42.testing.server:app`.
  - Тест-онли эндпоинты: `POST /__test__/reset` (тело `{"slot": "a"}`) — чистит данные слота; `POST /__test__/telegram/{agent_id}/deliver` (тело `{"chat_id": int, "text": str}`) — изображает входящее сообщение; `GET /__test__/telegram/{agent_id}/sent` — что агент отправил.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/integration/test_testing_server.py
from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from mimic42.testing.server import build_test_app
from mimic42.testing.slots import Slot


async def test_reset_endpoint_clears_slot_data(clean_slot: Slot) -> None:
    app = build_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/__test__/reset", json={"slot": clean_slot.name})
    assert response.status_code == 200


async def test_health_endpoint_still_works() -> None:
    app = build_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")
    assert response.json()["status"] == "ok"
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `uv run pytest tests/integration/test_testing_server.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'mimic42.testing.server'`.

- [ ] **Step 3: Реализовать реестр аккаунтов**

```python
# src/mimic42/testing/registry.py
"""Один поддельный телеграм-аккаунт на агента: сервер и тест смотрят
в одно и то же состояние."""

from __future__ import annotations

from uuid import UUID

from mimic42.testing.telegram import FakeTelegramAccount

_ACCOUNTS: dict[UUID, FakeTelegramAccount] = {}
_ONBOARDING_ACCOUNT = FakeTelegramAccount()


def account_for(agent_id: UUID) -> FakeTelegramAccount:
    account = _ACCOUNTS.get(agent_id)
    if account is None:
        account = FakeTelegramAccount()
        account.authorized = True
        _ACCOUNTS[agent_id] = account
    return account


def onboarding_account() -> FakeTelegramAccount:
    """Аккаунт, через который проходит вход в телегу во время онбординга."""
    return _ONBOARDING_ACCOUNT


def reset() -> None:
    _ACCOUNTS.clear()
    globals()["_ONBOARDING_ACCOUNT"] = FakeTelegramAccount()
```

- [ ] **Step 4: Реализовать тестовый сервер**

Ключевое: `create_app` вызывается БЕЗ `agent_store` и `onboarding_service`, чтобы отработала настоящая ветка старта с настоящей базой.

```python
# src/mimic42/testing/server.py
"""Точка входа сервера для тестов: настоящая база и настоящий API,
поддельные Telegram и модель.

Запуск: uv run uvicorn mimic42.testing.server:app --port 8000
"""

from __future__ import annotations

import os
from uuid import UUID

from fastapi import FastAPI
from pydantic import BaseModel

from mimic42.api.app import create_app
from mimic42.config import Settings
from mimic42.testing import registry
from mimic42.testing.cleanup import purge_slot_data
from mimic42.testing.llm import ScriptedAgentFactory
from mimic42.testing.slots import SLOTS
from mimic42.testing.telegram import FakeTelegramAuthClientFactory, FakeTelegramClient


class ResetRequest(BaseModel):
    slot: str


class DeliverRequest(BaseModel):
    chat_id: int
    text: str


def _test_settings() -> Settings:
    return Settings(
        database_connection_string=os.environ["TEST_DATABASE_CONNECTION_STRING"],
        supabase_url=os.environ["TEST_SUPABASE_URL"],
        secret_key=os.environ["TEST_SECRET_KEY"],
        telegram_api_id=int(os.environ.get("TEST_TELEGRAM_API_ID", "1")),
        telegram_api_hash=os.environ.get("TEST_TELEGRAM_API_HASH", "test-api-hash"),
        cors_allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
    )


def build_test_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or _test_settings()
    application = create_app(
        settings=app_settings,
        telegram_factory=FakeTelegramAuthClientFactory(registry.onboarding_account()),
        telegram_client_factory=lambda config: FakeTelegramClient(
            registry.account_for(config.agent_id)
        ),
        langchain_agent_factory=ScriptedAgentFactory(),
    )
    _mount_test_routes(application, app_settings)
    return application


def _mount_test_routes(application: FastAPI, settings: Settings) -> None:
    @application.post("/__test__/reset")
    async def reset(request: ResetRequest) -> dict[str, str]:
        slot = next(item for item in SLOTS if item.name == request.slot)
        await purge_slot_data(settings.database_connection_string or "", slot)
        registry.reset()
        return {"status": "ok"}

    @application.post("/__test__/telegram/{agent_id}/deliver")
    async def deliver(agent_id: UUID, request: DeliverRequest) -> dict[str, str]:
        await registry.account_for(agent_id).deliver(
            chat_id=request.chat_id, text=request.text
        )
        return {"status": "ok"}

    @application.get("/__test__/telegram/{agent_id}/sent")
    async def sent(agent_id: UUID) -> list[dict[str, str]]:
        account = registry.account_for(agent_id)
        return [{"chat_id": item.chat_id, "text": item.text} for item in account.sent]


app = build_test_app()
```

`ScriptedAgentFactory` берётся из задачи 9, которая выполняется раньше этой. Экземпляр фабрики нужно положить в `application.state.scripted_agents`, иначе тесты не смогут задавать сценарии:

```python
    scripted = ScriptedAgentFactory()
    application = create_app(..., langchain_agent_factory=scripted)
    application.state.scripted_agents = scripted
```

- [ ] **Step 5: Проверить запуск руками**

```bash
set -a && source .env.test && set +a
uv run uvicorn mimic42.testing.server:app --port 8000 &
curl -s http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/__test__/reset -H 'Content-Type: application/json' -d '{"slot":"a"}'
kill %1
```

Expected: `{"status":"ok","service":"mimic42-api"}` и `{"status":"ok"}`.

- [ ] **Step 6: Коммит**

```bash
uv run pytest -q && uv run ruff check . && uv run ty check
git add -A
git commit -m "feat(test): точка входа сервера с настоящей базой и поддельной телегой"
```

---

### Task 8: Тест старта приложения

**Files:**
- Test: `tests/integration/test_app_lifespan.py`

**Interfaces:**
- Consumes: `build_test_app` (задача 7), `db_session_factory` и `clean_slot` (задача 3), `DatabaseAgentStore`.
- Produces: ничего.

Это то самое, что сейчас не выполняется ни в одном тесте: создание движка, расшифровка Fernet, восстановление включённых агентов после перезапуска.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/integration/test_app_lifespan.py
from __future__ import annotations

from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.testing.server import build_test_app
from mimic42.testing.slots import Slot


async def test_running_agent_is_restored_after_restart(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()
    store = DatabaseAgentStore(db_session_factory)
    # Агент лежит в базе в состоянии «запущен», как после падения процесса.
    await store.create_agent(
        agent_id=agent_id,
        owner_id=owner_id,
        name="восстановленный",
        soul_markdown="спокойный помощник, отвечает коротко",
    )
    await store.update_status(agent_id, AgentRuntimeState.RUNNING)

    app = build_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        async with app.router.lifespan_context(app):
            statuses = await app.state.agent_manager.list_agents()
            assert agent_id in {status.agent_id for status in statuses}
            assert await client.get("/health")
```

Точные имена методов `DatabaseAgentStore` и `AgentManager` сверить по `src/mimic42/integrations/database_agent_store.py` и `src/mimic42/core/manager.py` — если сигнатуры отличаются, подставить настоящие, а тест по смыслу оставить тем же.

- [ ] **Step 2: Запустить**

Run: `uv run pytest tests/integration/test_app_lifespan.py -v`

Если тест падает не из-за опечаток, а по существу — это найденный баг в восстановлении агентов. Разобраться по-настоящему, а не обойти.

- [ ] **Step 3: Добавить тест на зашифрованную сессию**

```python
async def test_encrypted_telegram_session_is_decrypted_on_start(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    test_dsn: str,
) -> None:
    """Сессия телеги лежит в базе зашифрованной; при старте она должна
    расшифроваться тем же ключом, иначе агент не поднимется."""
    import os

    from mimic42.core.crypto import FernetSecretCipher

    cipher = FernetSecretCipher(os.environ["TEST_SECRET_KEY"])
    owner_id = clean_slot.persona("empty").user_id
    agent_id = uuid4()
    store = DatabaseAgentStore(db_session_factory, cipher=cipher)
    await store.create_agent(
        agent_id=agent_id,
        owner_id=owner_id,
        name="с сессией",
        soul_markdown="спокойный помощник, отвечает коротко",
    )
    await store.save_telegram_session(agent_id, "fake-session:+79990000000")

    app = build_test_app()
    async with app.router.lifespan_context(app):
        config = await app.state.agent_store.get_runtime_config(agent_id)

    assert config.telegram_session_string == "fake-session:+79990000000"
```

Имя метода сохранения сессии (`save_telegram_session` или как он называется в `DatabaseAgentStore`) сверить по `src/mimic42/integrations/database_agent_store.py`.

- [ ] **Step 4: Коммит**

```bash
uv run pytest -m db -q
git add tests/integration/test_app_lifespan.py
git commit -m "test: покрыть старт приложения и восстановление агентов"
```

---

### Task 9: Сценарные ответы модели

**Files:**
- Create: `src/mimic42/testing/llm.py`
- Test: `tests/integration/test_llm_resilience.py`

**Interfaces:**
- Consumes: `LangChainAgentLike` (`src/mimic42/core/agent_runtime.py:122`).
- Produces:
  - `ScriptedAgent(script: list[ScriptedTurn])` — реализует `ainvoke`.
  - `ScriptedTurn` — варианты: `Reply(text)`, `ToolCall(name, arguments)`, `Empty()`, `UnknownTool(name)`, `Garbage(payload)`, `Repeat(name, times)`.
  - `ScriptedAgentFactory(default_reply: str = "готово")` — подставляется в `langchain_agent_factory`; `set_script(agent_id: UUID, script: list[ScriptedTurn]) -> None`.

- [ ] **Step 1: Написать падающие тесты устойчивости**

Смысл — не мозг агента, а то, что приложение не падает и честно записывает ошибку.

```python
# tests/integration/test_llm_resilience.py
from __future__ import annotations

from uuid import uuid4

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import AgentRuntimeConfig
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.testing import registry
from mimic42.testing.llm import Empty, Garbage, UnknownTool
from mimic42.testing.peer import FakePeer
from mimic42.testing.server import build_test_app
from mimic42.testing.slots import Slot, plain_dsn

CHAT_ID = 4242


async def _running_agent(
    app: object,
    db_session_factory: async_sessionmaker[AsyncSession],
    slot: Slot,
) -> tuple[object, object]:
    """Создаёт агента в базе, запускает его и возвращает (agent_id, peer)."""
    owner_id = slot.persona("full").user_id
    agent_id = uuid4()
    store = DatabaseAgentStore(db_session_factory)
    await store.create_agent(
        agent_id=agent_id,
        owner_id=owner_id,
        name="устойчивый",
        soul_markdown="спокойный помощник, отвечает коротко",
    )
    config = await store.get_runtime_config(agent_id)
    await app.state.agent_manager.create_agent(config, start=True)
    return agent_id, FakePeer(registry.account_for(agent_id), chat_id=CHAT_ID)


async def test_unknown_tool_is_recorded_as_failure(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    test_dsn: str,
) -> None:
    """Модель попросила несуществующий инструмент: событие должно
    сохраниться со статусом «не удалось», а не «успех»."""
    app = build_test_app()
    async with app.router.lifespan_context(app):
        agent_id, peer = await _running_agent(app, db_session_factory, clean_slot)
        app.state.scripted_agents.set_script(agent_id, [UnknownTool()])

        await peer.send("сделай что-нибудь")

        connection = await asyncpg.connect(plain_dsn(test_dsn))
        try:
            statuses = await connection.fetch(
                "select status from public.agent_events where agent_id = $1", agent_id
            )
        finally:
            await connection.close()
    assert statuses, "событие об использовании инструмента вообще не записалось"
    assert {row["status"] for row in statuses} == {"failed"}


async def test_empty_answer_does_not_send_empty_message(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Пустой ответ модели не должен превращаться в пустое сообщение в телеге."""
    app = build_test_app()
    async with app.router.lifespan_context(app):
        agent_id, peer = await _running_agent(app, db_session_factory, clean_slot)
        app.state.scripted_agents.set_script(agent_id, [Empty()])

        await peer.send("привет")

        account = registry.account_for(agent_id)
    assert [message for message in account.sent if not message.text.strip()] == []


async def test_garbage_arguments_do_not_crash_the_runtime(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Мусор вместо ответа модели: агент остаётся в рабочем состоянии."""
    app = build_test_app()
    async with app.router.lifespan_context(app):
        agent_id, peer = await _running_agent(app, db_session_factory, clean_slot)
        app.state.scripted_agents.set_script(agent_id, [Garbage()])

        await peer.send("привет")

        status = await app.state.agent_manager.get_status(agent_id)
    assert status.state.value in {"running", "error"}
    assert status.state.value == "running", "кривой ответ модели не должен ронять агента"
```

Точные имена методов `DatabaseAgentStore` и `AgentManager` сверить по `src/mimic42/integrations/database_agent_store.py` и `src/mimic42/core/manager.py`; если сигнатуры отличаются — подставить настоящие, смысл проверок не менять.

- [ ] **Step 2: Реализовать сценарного агента**

```python
# src/mimic42/testing/llm.py
"""Заготовленные ответы модели: правильные и намеренно кривые.
Живая модель сюда не входит — она проверяется отдельным набором."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass
class Reply:
    text: str


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class Empty:
    pass


@dataclass
class UnknownTool:
    name: str = "несуществующий_инструмент"


@dataclass
class Garbage:
    payload: Any = "не json"


@dataclass
class Repeat:
    name: str
    times: int = 10


ScriptedTurn = Reply | ToolCall | Empty | UnknownTool | Garbage | Repeat


class ScriptedAgent:
    def __init__(self, script: list[ScriptedTurn], default_reply: str) -> None:
        self._script = list(script)
        self._default_reply = default_reply
        self.calls: list[dict[str, object]] = []

    async def ainvoke(
        self,
        input_data: dict[str, object],
        context: object | None = None,
    ) -> object:
        self.calls.append(input_data)
        turn: ScriptedTurn = self._script.pop(0) if self._script else Reply(self._default_reply)
        return _render(turn)


def _render(turn: ScriptedTurn) -> object:
    match turn:
        case Reply(text=text):
            return {"messages": [{"role": "assistant", "content": text}]}
        case Empty():
            return {"messages": []}
        case Garbage(payload=payload):
            return payload
        case UnknownTool(name=name) | ToolCall(name=name):
            arguments = turn.arguments if isinstance(turn, ToolCall) else {}
            return {
                "messages": [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"name": name, "args": arguments, "id": "call-1"}],
                    }
                ]
            }
        case Repeat(name=name, times=times):
            return {
                "messages": [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"name": name, "args": {}, "id": f"call-{index}"}
                            for index in range(times)
                        ],
                    }
                ]
            }


@dataclass
class ScriptedAgentFactory:
    default_reply: str = "готово"
    scripts: dict[UUID, list[ScriptedTurn]] = field(default_factory=dict)
    built: dict[UUID, ScriptedAgent] = field(default_factory=dict)

    def set_script(self, agent_id: UUID, script: list[ScriptedTurn]) -> None:
        self.scripts[agent_id] = script

    def __call__(
        self,
        config: Any,
        tools: Any,
        session_factory: Any,
    ) -> ScriptedAgent:
        agent = ScriptedAgent(self.scripts.get(config.agent_id, []), self.default_reply)
        self.built[config.agent_id] = agent
        return agent
```

Форму возвращаемого значения сверить с тем, что реально ожидает `MimicAgentRuntime` от `ainvoke` (см. `src/mimic42/core/agent_runtime.py` и `FakeLangChainAgent` в старых тестах) — она должна совпадать один в один, иначе тесты проверят не то.

- [ ] **Step 3: Прогнать и дописать тела тестов**

Run: `uv run pytest tests/integration/test_llm_resilience.py -v`

Каждое падение, которое вскроет реальную дыру (ошибка инструмента, записанная как успех; пустое сообщение, ушедшее в телегу), — чинить в прод-коде.

- [ ] **Step 4: Дописать тесты устойчивости (после задачи 7)**

Тела из шага 1 поднимают тестовый сервер, поэтому выполняются, когда задача 7 готова. Вернуться сюда и прогнать:

Run: `uv run pytest tests/integration/test_llm_resilience.py -v`

- [ ] **Step 5: Коммит**

```bash
uv run pytest -q && uv run ruff check . && uv run ty check
git add -A
git commit -m "feat(test): сценарные ответы модели, включая заведомо кривые"
```

---

### Task 10: Роль собеседника

**Files:**
- Create: `src/mimic42/testing/peer.py`
- Test: `tests/integration/test_conversation.py`

**Interfaces:**
- Consumes: реестр (задача 7), подделку (задача 5).
- Produces:
  - `class ConversationPeer(Protocol)`: `async def send(self, text: str) -> None`, `async def wait_for_reply(self, timeout: float = 10.0) -> str`, `async def history(self) -> list[str]`, `async def was_read(self) -> bool`.
  - `FakePeer(account: FakeTelegramAccount, chat_id: int)` — реализация поверх состояния в памяти.

Это главный задел на будущее: когда появится живая телега, рядом встанет `RealPeer` поверх второго настоящего аккаунта, а тесты не изменятся.

- [ ] **Step 1: Написать падающий тест диалога**

```python
# tests/integration/test_conversation.py
from __future__ import annotations

from mimic42.testing.peer import FakePeer
from mimic42.testing.telegram import FakeTelegramAccount


async def test_peer_sends_and_waits_for_reply() -> None:
    account = FakeTelegramAccount()
    account.authorized = True
    peer = FakePeer(account, chat_id=42)

    await peer.send("привет")
    # Ответ появляется, когда агент кладёт сообщение в отправленные.
    await account_reply(account, chat_id=42, text="привет, чем помочь")

    assert await peer.wait_for_reply(timeout=1.0) == "привет, чем помочь"
    assert await peer.history() == ["привет", "привет, чем помочь"]


async def account_reply(account: FakeTelegramAccount, *, chat_id: int, text: str) -> None:
    from mimic42.testing.telegram import FakeTelegramClient

    await FakeTelegramClient(account).send_message(str(chat_id), text)
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `uv run pytest tests/integration/test_conversation.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'mimic42.testing.peer'`.

- [ ] **Step 3: Реализовать собеседника**

```python
# src/mimic42/testing/peer.py
"""Роль собеседника: то, чем тест разговаривает с Мимиком.

Тесты пишутся против этого интерфейса, а не против подделки напрямую.
Когда появится живая телега, рядом встанет реализация поверх второго
настоящего аккаунта, и тесты менять не придётся.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from mimic42.testing.telegram import FakeTelegramAccount


class ConversationPeer(Protocol):
    async def send(self, text: str) -> None: ...

    async def wait_for_reply(self, timeout: float = 10.0) -> str: ...

    async def history(self) -> list[str]: ...

    async def was_read(self) -> bool: ...


class FakePeer:
    def __init__(self, account: FakeTelegramAccount, chat_id: int) -> None:
        self._account = account
        self._chat_id = chat_id
        self._seen_replies = 0

    async def send(self, text: str) -> None:
        await self._account.deliver(chat_id=self._chat_id, text=text)

    async def wait_for_reply(self, timeout: float = 10.0) -> str:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            replies = self._replies()
            if len(replies) > self._seen_replies:
                self._seen_replies += 1
                return replies[self._seen_replies - 1]
            await asyncio.sleep(0.05)
        raise TimeoutError(f"Ответ не пришёл за {timeout} секунд")

    async def history(self) -> list[str]:
        incoming = [
            (index, message.text)
            for index, message in enumerate(self._account.incoming)
            if message.chat_id == self._chat_id
        ]
        outgoing = [
            (index, message.text)
            for index, message in enumerate(self._account.sent)
            if message.chat_id == str(self._chat_id)
        ]
        merged = [text for _, text in incoming] + [text for _, text in outgoing]
        return merged

    async def was_read(self) -> bool:
        return str(self._chat_id) in " ".join(self._account.read_marks)

    def _replies(self) -> list[str]:
        return [
            message.text
            for message in self._account.sent
            if message.chat_id == str(self._chat_id)
        ]
```

Порядок в `history` должен быть хронологическим — если после реализации тест на порядок падает, добавить в `SentMessage` и `IncomingMessage` общий счётчик и сортировать по нему.

- [ ] **Step 4: Сквозной тест диалога через живой сервер**

```python
# дописать в tests/integration/test_conversation.py
from __future__ import annotations

from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.testing import registry
from mimic42.testing.llm import Reply
from mimic42.testing.server import build_test_app
from mimic42.testing.slots import Slot


async def test_whole_turn_reaches_the_database_and_the_api(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Сообщение пришло, агент ответил, переписка сохранилась и видна через API."""
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()
    store = DatabaseAgentStore(db_session_factory)
    await store.create_agent(
        agent_id=agent_id,
        owner_id=owner_id,
        name="собеседник",
        soul_markdown="спокойный помощник, отвечает коротко",
    )

    app = build_test_app()
    async with app.router.lifespan_context(app):
        config = await app.state.agent_store.get_runtime_config(agent_id)
        await app.state.agent_manager.create_agent(config, start=True)
        app.state.scripted_agents.set_script(agent_id, [Reply("привет, чем помочь")])

        peer = FakePeer(registry.account_for(agent_id), chat_id=4242)
        await peer.send("привет")
        assert await peer.wait_for_reply(timeout=10.0) == "привет, чем помочь"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get(f"/api/v1/agents/{agent_id}/messages")

    assert response.status_code == 200
    texts = [item["content"] for item in response.json()]
    assert "привет" in texts
    assert "привет, чем помочь" in texts
```

Путь эндпоинта истории сообщений и форму ответа сверить по `src/mimic42/api/app.py`. Запрос пойдёт через проверку токена — в этом тесте её обходим, передав `auth_verifier` в `build_test_app`; если такой возможности нет, добавить необязательный параметр `auth_verifier` в `build_test_app` и прокинуть его в `create_app`.

- [ ] **Step 5: Коммит**

```bash
uv run pytest -q && uv run ruff check . && uv run ty check
git add -A
git commit -m "feat(test): роль собеседника как задел под живую телегу"
```

---

### Task 11: Браузерные тесты против живого бэкенда

**Files:**
- Modify: `frontend/playwright.config.ts`
- Modify: `frontend/e2e/helpers.ts`
- Modify: `frontend/e2e/auth.setup.ts`
- Modify: `frontend/e2e/onboarding.spec.ts`, `frontend/e2e/agent.spec.ts`, `frontend/e2e/auth.spec.ts`, `frontend/e2e/unauth.spec.ts`
- Delete: `frontend/e2e/stub/server.ts`
- Create: `frontend/e2e/global-setup.ts`, `frontend/e2e/global-teardown.ts`

**Interfaces:**
- Consumes: тестовый сервер (задача 7), слоты (задача 2).
- Produces: `E2E_SLOT` в окружении процесса Playwright; хелперы `resetBackend(request)`, `deliverMessage(request, agentId, text)`, `sentMessages(request, agentId)` вместо `resetStub`, `patchStubRow`, `readStubRows`.

- [ ] **Step 1: Занять слот в global setup**

```typescript
// frontend/e2e/global-setup.ts
import { spawnSync } from 'node:child_process';

export default function globalSetup(): void {
  const result = spawnSync('uv', ['run', 'python', '-m', 'mimic42.testing.slot_cli', 'acquire'], {
    cwd: '..',
    encoding: 'utf8',
  });
  if (result.status !== 0) throw new Error(`Не удалось занять слот: ${result.stderr}`);
  process.env.E2E_SLOT = result.stdout.trim();
}
```

Понадобится маленький модуль `src/mimic42/testing/slot_cli.py` с командами `acquire` и `release`, печатающий имя слота в stdout, — написать его здесь же, опираясь на `acquire_slot`/`release_slot` из задачи 2.

- [ ] **Step 2: Переписать webServer**

Стаб уходит, вместо него — настоящий бэкенд:

```typescript
  webServer: [
    {
      command: 'uv run uvicorn mimic42.testing.server:app --port 8000',
      cwd: '..',
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: process.env.CI ? 'bun run build && bun run start' : 'bun run dev',
      url: APP_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: { ...testEnv, PORT: String(APP_PORT) },
    },
  ],
```

где `testEnv` теперь указывает на настоящий Dev-проект:

```typescript
const testEnv = {
  NEXT_PUBLIC_SUPABASE_URL: process.env.TEST_SUPABASE_URL!,
  NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.TEST_SUPABASE_ANON_KEY!,
  NEXT_PUBLIC_API_BASE_URL: 'http://127.0.0.1:8000',
};
```

- [ ] **Step 3: Переписать список пользователей под слот**

`USERS` в `helpers.ts` строится из `E2E_SLOT`: для слота `a` — почты `e2e-full@mimic42.test` и так далее, для слота `b` — с суффиксом `-b`, идентификаторы из `SLOTS`. Держать это в одном месте: экспортировать из питона JSON-описание слотов командой `uv run python -m mimic42.testing.slot_cli describe` и читать его в `helpers.ts`, чтобы два списка не разъезжались.

- [ ] **Step 4: Переписать вход**

`loginViaForm` не меняется — форма та же. Меняется то, что за ней: настоящий Supabase проверяет пароль и выдаёт настоящий токен. В `auth.setup.ts` заменить `resetStub(request)` на `resetBackend(request)`, который дёргает `POST http://127.0.0.1:8000/__test__/reset`.

- [ ] **Step 5: Выкинуть перехваты API из спеков**

Во всех спеках убрать `page.route('**/api/v1/**')` и `mockApi`. Онбординг теперь идёт по-настоящему: форма шлёт запрос, настоящий бэкенд отвечает, поддельная телега изображает код. Чтобы код был предсказуем, перед шагом ввода задать его через тестовый эндпоинт — добавить в `server.py` `POST /__test__/telegram/onboarding/script` с телом `{"code": "12345", "password": null}`.

- [ ] **Step 6: Переписать ожидания по realtime**

Стаб намеренно отдавал 404 на websocket, чтобы интерфейс показывал состояние «офлайн». В Dev публикация на таблицу агентов включена, поэтому realtime работает по-настоящему. Найти все проверки офлайн-состояния и переписать их на живое обновление: изменить статус агента через API и дождаться, что дашборд обновился сам, без перезагрузки страницы.

- [ ] **Step 7: Освободить слот в teardown**

```typescript
// frontend/e2e/global-teardown.ts
import { spawnSync } from 'node:child_process';

export default function globalTeardown(): void {
  spawnSync('uv', ['run', 'python', '-m', 'mimic42.testing.slot_cli', 'release',
    process.env.E2E_SLOT ?? ''], { cwd: '..', encoding: 'utf8' });
}
```

- [ ] **Step 8: Удалить стаб**

```bash
git rm frontend/e2e/stub/server.ts
grep -rn "STUB_URL\|resetStub\|patchStubRow\|readStubRows" frontend/e2e
```

Expected: пусто.

- [ ] **Step 9: Прогнать браузерные тесты**

```bash
set -a && source .env.test && set +a
cd frontend && bun run test:e2e
```

Ожидаются падения — это и есть расхождения фронта с настоящим бэкендом, ради которых всё затевалось. Каждое разбирать по существу: если неправ фронт — править фронт, если бэкенд — бэкенд.

- [ ] **Step 10: Коммит**

```bash
cd frontend && bunx next lint && bun run typecheck && bun test
cd .. && git add -A
git commit -m "test(e2e): браузерные тесты против живого бэкенда и базы Dev"
```

---

### Task 12: CI

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: всё предыдущее.
- Produces: джобы `backend`, `backend-db`, `frontend`, `e2e`, `migrations-drift`.

- [ ] **Step 1: Оставить быстрые тесты как есть**

В джобе `backend` заменить команду тестов на `uv run pytest -m "not db" -W error -q`, чтобы она не требовала секретов и не занимала слот.

- [ ] **Step 2: Добавить джобу тестов на базе**

```yaml
  backend-db:
    name: backend-db
    runs-on: ubuntu-latest
    timeout-minutes: 20
    if: github.event.pull_request.head.repo.full_name == github.repository
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv python install
      - run: uv sync --locked --all-groups
      - name: Tests against Dev database
        run: uv run pytest -m db -W error -q
        env:
          TEST_DATABASE_CONNECTION_STRING: ${{ secrets.TEST_DATABASE_CONNECTION_STRING }}
          TEST_SUPABASE_URL: ${{ secrets.TEST_SUPABASE_URL }}
          TEST_SUPABASE_ANON_KEY: ${{ secrets.TEST_SUPABASE_ANON_KEY }}
          TEST_SECRET_KEY: ${{ secrets.TEST_SECRET_KEY }}
          TEST_USER_PASSWORD: ${{ secrets.TEST_USER_PASSWORD }}
          TEST_TELEGRAM_API_ID: '1'
          TEST_TELEGRAM_API_HASH: test-api-hash
```

Условие `if` нужно, потому что на PR из форков секретов нет: джоба скипается, а не падает.

- [ ] **Step 3: Переписать джобу e2e**

Добавить установку Python и uv (нужен бэкенд), те же секреты в окружении и `working-directory: frontend` только для шагов bun.

- [ ] **Step 4: Добавить стража от расхождения миграций**

```yaml
  migrations-drift:
    name: migrations-drift
    runs-on: ubuntu-latest
    if: github.event.pull_request.head.repo.full_name == github.repository
    steps:
      - uses: actions/checkout@v4
      - uses: supabase/setup-cli@v1
        with:
          version: latest
      - name: Compare local migrations with Dev
        run: supabase migration list --linked
        env:
          SUPABASE_ACCESS_TOKEN: ${{ secrets.SUPABASE_ACCESS_TOKEN }}
          SUPABASE_DB_PASSWORD: ${{ secrets.TEST_DB_PASSWORD }}
          SUPABASE_PROJECT_ID: ipqylrdmmjitemjrygej
```

Команда печатает таблицу; добавить шаг, который падает, если в колонке Remote есть пропуски — например, разбором вывода через `grep -c`.

- [ ] **Step 5: Проверить на PR**

Открыть черновой PR и убедиться: быстрые тесты зелёные, тесты на базе зелёные, браузерные зелёные, второй одновременный прогон занимает второй слот и не мешает первому.

- [ ] **Step 6: Коммит**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: тесты на базе Dev, живой бэкенд в e2e, страж миграций"
```

---

## Проверка целиком

1. `supabase migration list --linked` — Dev совпадает с репозиторием.
2. `uv run pytest -m "not db" -q` — быстрые тесты зелёные без сети и без секретов.
3. `uv run pytest -m db -q` — тесты на настоящей базе зелёные; второй прогон подряд тоже зелёный, значит очистка работает.
4. `env -u TEST_DATABASE_CONNECTION_STRING uv run pytest -m db -q` — скипается, не падает.
5. Два прогона одновременно занимают разные слоты; третий ждёт и падает по таймауту с внятным сообщением.
6. `cd frontend && bun run test:e2e` — против живого бэкенда, в сетевых запросах нет обращений к стабу.
7. Руками: поднять `uv run uvicorn mimic42.testing.server:app` и `bun run dev`, войти персоной `full`, увидеть агентов из Dev, пройти онбординг на поддельной телеге до конца.
8. Проверить, что данные разработчика в Dev на месте: очистка тронула только тестовые учётки.

## Что этот план не делает

- Не подключает живую телегу и живую модель — только оставляет для них место (`ConversationPeer`, выбор фабрик при запуске).
- Не чинит то, что бэкенд ходит в базу служебным подключением в обход правил доступа.
- Не накатывает миграции в прод.
