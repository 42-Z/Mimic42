# Tool Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать каждому агенту allowlist доступных Telegram-инструментов (`agents.settings.enabled_tools`) с разделом переключателей в «Настройках», а пресетам и онбордингу — нести этот набор вместе с промптом.

**Architecture:** Хранение — `agents.settings.enabled_tools: string[]` (нет ключа = включены все 91, пустой список = не включён ни один). Бэкенд разбирает allowlist в `AgentRuntimeConfig`, фильтрует каталог `StructuredTool` при сборке рантайма и подстраховывает исполнение middleware, отклоняющей вызов отключённого инструмента. Фронтенд ведёт нейтральный каталог названий/описаний, секцию переключателей в форме «Настройки» и переносит настройки пресета в ту же форму; онбординг хранит патч настроек в черновике и финализация переносит его в созданного агента.

**Tech Stack:** Python 3.13 (`uv`, Ruff, ty, pytest), LangChain `create_agent` + middleware, Telethon-инструменты, Supabase Postgres (SQL-миграции через Supabase CLI, RLS/колоночные гранты), Next.js 14 + React 18 + TanStack Query + TypeScript, `bun test` + Testing Library, Playwright через pytest.

**Spec:** `docs/superpowers/specs/2026-10-01-tool-configuration-design.md`

## Global Constraints

- Формат настройки строго один: `agents.settings.enabled_tools` — allowlist. Ключа нет — включены все инструменты; пустой список — не включён ни один. Никакого второго формата.
- Разбор на бэкенде терпимый: мусор в значении не должен ронять агента и не должен случайно выключать все инструменты.
- Единица настройки — имя инструмента. Группы существуют только в интерфейсе.
- Обычные ответы в диалогах и «Первый комментарий» — не инструменты; их отключение настройка не задевает.
- `BASE_SYSTEM_PROMPT.txt`, память, контекст и эндпоинт `POST /agents/{id}/reload` не меняются.
- Никаких новых HTTP-эндпоинтов и новых Python-зависимостей.
- Все пользовательские строки — на русском, как в остальном интерфейсе.
- Фронтенд-команды запускаются из `frontend/`: `bun test`, `bun run typecheck`, `bunx next lint`.
- Python-команды — через `uv run`. DB-тесты: `uv run pytest -m db`; e2e: `uv run pytest -m e2e`.
- Миграции — только через Supabase CLI (`supabase migration new`), руками файл не создавать и не переименовывать.
- Продовую базу и продовые миграции в этой задаче не трогаем; Dev-база обновляется `supabase db push`.

**Отличие от спеки (структура каталога):** метаданные настроек живут в новом файле `frontend/src/lib/tools/toolInfo.ts` (упорядоченный массив), а каталог активности `frontend/src/lib/activity/toolCatalog.ts` не перестраивается. Синхронность двух списков стережёт тест `tool-info.test.ts`.

---

### Task 1: Миграция: настройки у пресетов и черновика

**Files:**
- Create: `supabase/migrations/<timestamp>_tool_configuration.sql` (файл создаёт `supabase migration new`, имя и время не сочинять)
- Modify: `tests/integration/test_prompt_presets.py`
- Modify: `tests/integration/test_onboarding_rls.py`
- Regenerate: `frontend/src/types/supabase.ts` (командой, руками не править)

**Interfaces:**
- Consumes: ничего.
- Produces: колонки `public.prompt_presets.settings jsonb` и `public.agent_onboarding_sessions.settings jsonb not null default '{}'`; колоночные гранты `insert (settings)` / `update (settings)` для `authenticated`; сид `rage_comments.settings.enabled_tools` из 16 имён. В `frontend/src/types/supabase.ts` появляются оба поля.

- [ ] **Step 1: Написать падающие тесты**

Дописать в конец `tests/integration/test_prompt_presets.py`:

```python
async def test_rage_comments_defines_tool_allowlist(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        settings = await connection.fetchval(
            "select settings from public.prompt_presets where slug = 'rage_comments'"
        )
    finally:
        await connection.close()

    assert isinstance(settings, dict)
    enabled = settings["enabled_tools"]
    assert set(enabled) == {
        "get_dialogs",
        "get_messages",
        "search_messages",
        "get_discussion_messages",
        "join_channel_discussion",
        "view_image",
        "send_text_message",
        "send_chat_action",
        "send_reaction",
        "get_message_reactions",
        "mark_chat_as_read",
        "get_chat_info",
        "check_admin_permissions",
        "get_message_buttons",
        "click_inline_button",
        "start_bot",
    }
    # Разрушительное администрирование и приватность комментатору недоступны.
    assert "delete_channel" not in enabled
    assert "set_privacy_settings" not in enabled
```

В существующий `test_authenticated_reads_but_cannot_write` добавить чтение настроек под ролью `authenticated` — сразу после `assert await connection.fetchval("select count(*) ...") == 4`:

```python
            rage = await connection.fetchval(
                "select settings from public.prompt_presets where slug = 'rage_comments'"
            )
            assert "send_text_message" in rage["enabled_tools"]
```

Дописать в конец `tests/integration/test_onboarding_rls.py`:

```python
async def test_client_can_store_tool_settings_in_draft(
    test_dsn: str,
    clean_slot: Slot,
) -> None:
    """Настройки инструментов — обычные данные черновика, их пишет визард."""
    client = clean_slot.persona("code")
    connection = await asyncpg.connect(plain_dsn(test_dsn), timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        async with connection.transaction():
            await _act_as_client(connection, client.user_id)
            draft_id = await connection.fetchval(
                "insert into public.agent_onboarding_sessions "
                "(owner_id, agent_name, soul_prompt, settings, updated_at) "
                "values ($1, 'Мой агент', 'Характер', $2::jsonb, now()) returning id",
                client.user_id,
                '{"enabled_tools": ["send_text_message"]}',
            )
            await connection.execute(
                "update public.agent_onboarding_sessions "
                "set settings = $2::jsonb, updated_at = now() where id = $1",
                draft_id,
                '{"enabled_tools": ["send_text_message", "view_image"]}',
            )
            stored = await connection.fetchval(
                "select settings from public.agent_onboarding_sessions where id = $1",
                draft_id,
            )
    finally:
        await connection.close()

    assert stored == {"enabled_tools": ["send_text_message", "view_image"]}
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `uv run pytest -m db tests/integration/test_prompt_presets.py tests/integration/test_onboarding_rls.py -v`
Expected: FAIL — `asyncpg.exceptions.UndefinedColumnError: column "settings" does not exist` (в тестах пресетов и онбординга).

- [ ] **Step 3: Создать миграцию через CLI**

Run: `supabase migration new tool_configuration`
Expected: CLI печатает путь `supabase/migrations/<timestamp>_tool_configuration.sql`. Дальше писать SQL только в этот файл.

- [ ] **Step 4: Написать SQL миграции**

```sql
-- Issue #37: настройка инструментов Мимика живёт в agents.settings.enabled_tools
-- (allowlist), а пресеты и черновик онбординга несут частичный патч настроек
-- рядом с промптом.

alter table public.prompt_presets
    add column settings jsonb;

alter table public.prompt_presets
    add constraint prompt_presets_settings_is_object
    check (settings is null or jsonb_typeof(settings) = 'object');

-- Показательный курируемый набор: комментатор читает каналы и обсуждения,
-- комментирует, ставит реакции и проходит капчу в обсуждении, но не получает
-- доступ к администрированию, профилю и приватности аккаунта.
update public.prompt_presets
set settings = jsonb_build_object(
    'enabled_tools',
    jsonb_build_array(
        'get_dialogs',
        'get_messages',
        'search_messages',
        'get_discussion_messages',
        'join_channel_discussion',
        'view_image',
        'send_text_message',
        'send_chat_action',
        'send_reaction',
        'get_message_reactions',
        'mark_chat_as_read',
        'get_chat_info',
        'check_admin_permissions',
        'get_message_buttons',
        'click_inline_button',
        'start_bot'
    )
)
where slug = 'rage_comments';

alter table public.agent_onboarding_sessions
    add column settings jsonb not null default '{}'::jsonb;

alter table public.agent_onboarding_sessions
    add constraint agent_onboarding_sessions_settings_is_object
    check (jsonb_typeof(settings) = 'object');

-- Визард пишет настройки будущего агента рядом с именем и характером.
-- Колоночные привилегии накапливаются: прежние гранты не отзываются.
grant insert (settings) on table public.agent_onboarding_sessions to authenticated;
grant update (settings) on table public.agent_onboarding_sessions to authenticated;
```

- [ ] **Step 5: Применить миграцию к Dev-базе**

Run: `supabase db push`
Expected: CLI печатает новую миграцию и `Finished supabase db push.`

Проект уже слинкован (`supabase/.temp/project-ref`). Если CLI просит логин — `supabase login`. Продовую базу не трогаем.

- [ ] **Step 6: Запустить тесты и убедиться, что проходят**

Run: `uv run pytest -m db tests/integration/test_prompt_presets.py tests/integration/test_onboarding_rls.py -v`
Expected: PASS (в пресетах 3 passed, в онбординге 5 passed).

- [ ] **Step 7: Перегенерировать типы Supabase**

Run: `cd frontend && bun run generate:types && bun run typecheck`
Expected: в `frontend/src/types/supabase.ts` у `prompt_presets` и `agent_onboarding_sessions` появилось поле `settings`; typecheck без ошибок.

- [ ] **Step 8: Коммит**

```bash
git add supabase/migrations tests/integration/test_prompt_presets.py tests/integration/test_onboarding_rls.py frontend/src/types/supabase.ts
git commit -m "feat(db): tool settings for presets and onboarding drafts"
```

---

### Task 2: Разбор настройки и конфиг рантайма

**Files:**
- Create: `src/mimic42/core/tool_config.py`
- Create: `tests/core/test_tool_config.py`
- Modify: `src/mimic42/core/agent_runtime.py:102-116`
- Modify: `src/mimic42/integrations/database_agent_store.py:24,182-211`
- Modify: `tests/integration/test_database_agent_store.py` (в конец файла)

**Interfaces:**
- Consumes: колонку `agents.settings` (существующую) из Task 1.
- Produces:
  - `parse_enabled_tools(raw: Any) -> frozenset[str] | None` в `mimic42.core.tool_config`
  - `AgentRuntimeConfig.enabled_tools: frozenset[str] | None = None`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/core/test_tool_config.py`:

```python
"""Разбор settings.enabled_tools: allowlist, который не роняет агента."""

from __future__ import annotations

from mimic42.core.tool_config import parse_enabled_tools


def test_missing_key_enables_all_tools() -> None:
    assert parse_enabled_tools(None) is None


def test_empty_list_is_an_empty_allowlist() -> None:
    assert parse_enabled_tools([]) == frozenset()


def test_list_of_names_becomes_allowlist() -> None:
    assert parse_enabled_tools(["send_text_message", " view_image "]) == frozenset(
        {"send_text_message", "view_image"}
    )


def test_non_string_items_are_dropped() -> None:
    assert parse_enabled_tools(["send_text_message", 42, None, ""]) == frozenset(
        {"send_text_message"}
    )


def test_list_without_valid_names_enables_all_tools() -> None:
    # Мусорный список не должен случайно выключить все инструменты.
    assert parse_enabled_tools([42, None, "  "]) is None


def test_unexpected_type_enables_all_tools() -> None:
    assert parse_enabled_tools({"send_text_message": True}) is None
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `uv run pytest tests/core/test_tool_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mimic42.core.tool_config'`

- [ ] **Step 3: Написать модуль**

Создать `src/mimic42/core/tool_config.py`:

```python
"""Настройка доступных агенту инструментов (settings.enabled_tools).

Ключа нет — включены все инструменты. Пустой список — честный пустой
allowlist. Нечитаемое значение не должно ни ронять агента, ни случайно
выключать всё: в этом случае ведём себя как при отсутствии ключа.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("mimic42.tool_config")


def parse_enabled_tools(raw: Any) -> frozenset[str] | None:
    """Разобрать ``settings.enabled_tools`` в allowlist имён инструментов."""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        logger.warning(
            "enabled_tools has unexpected type %s; enabling all tools",
            type(raw).__name__,
        )
        return None

    names = frozenset(item.strip() for item in raw if isinstance(item, str) and item.strip())
    if not names and raw:
        logger.warning("enabled_tools has no valid tool names; enabling all tools")
        return None
    return names
```

- [ ] **Step 4: Запустить тест и убедиться, что он проходит**

Run: `uv run pytest tests/core/test_tool_config.py -v`
Expected: PASS, 6 passed.

- [ ] **Step 5: Добавить поле в конфиг рантайма**

В `src/mimic42/core/agent_runtime.py`, в `AgentRuntimeConfig` после `reasoning_effort`:

```python
    reasoning_effort: str = Field(default="high")
    # None — allowlist не задан: доступны все инструменты. Иначе — только
    # перечисленные имена.
    enabled_tools: frozenset[str] | None = Field(default=None)
```

- [ ] **Step 6: Читать настройку при сборке конфига**

В `src/mimic42/integrations/database_agent_store.py`:

1. Добавить импорт рядом с `parse_first_comment`:

```python
from mimic42.core.tool_config import parse_enabled_tools
```

2. В `get_runtime_config`, в конструктор `AgentRuntimeConfig(...)` после `reasoning_effort`:

```python
                enabled_tools=parse_enabled_tools(
                    agent.settings.get("enabled_tools") if agent.settings else None
                ),
```

- [ ] **Step 7: Написать db-тесты чтения конфига**

Дописать в конец `tests/integration/test_database_agent_store.py`:

```python
async def test_get_runtime_config_parses_enabled_tools(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()
    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(_make_session(owner_id, agent_id, "Mimic"))
    async with db_session_factory() as db_session:
        await db_session.execute(
            update(AgentModel)
            .where(AgentModel.id == agent_id)
            .values(settings={"enabled_tools": ["send_text_message", "view_image"]})
        )
        await db_session.commit()

    config = await store.get_runtime_config(agent_id)

    assert config.enabled_tools == frozenset({"send_text_message", "view_image"})


async def test_get_runtime_config_without_enabled_tools_enables_all(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()
    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(_make_session(owner_id, agent_id, "Mimic"))

    config = await store.get_runtime_config(agent_id)

    assert config.enabled_tools is None
```

- [ ] **Step 8: Прогнать тесты и проверки**

Run: `uv run pytest tests/core/test_tool_config.py tests/integration/test_database_agent_store.py -m db -v`
Ожидание: unit-тесты и db-тесты зелёные (маркер `db` из conftest применяется к `tests/integration` автоматически; `-m db` в командной строке включает их поверх `addopts`).

Run: `uv run ruff check src/mimic42/core/tool_config.py src/mimic42/core/agent_runtime.py src/mimic42/integrations/database_agent_store.py && uv run ty check`
Expected: чисто.

- [ ] **Step 9: Коммит**

```bash
git add src/mimic42/core/tool_config.py src/mimic42/core/agent_runtime.py src/mimic42/integrations/database_agent_store.py tests/core/test_tool_config.py tests/integration/test_database_agent_store.py
git commit -m "feat(core): parse enabled tools into runtime config"
```

---

### Task 3: Фильтрация каталога и страховка исполнения

**Files:**
- Create: `src/mimic42/integrations/tool_access_middleware.py`
- Create: `tests/integrations/test_tool_access_middleware.py`
- Create: `tests/core/test_tool_allowlist_wiring.py`
- Modify: `src/mimic42/integrations/telegram_tools.py:2832-2839,3419`
- Modify: `src/mimic42/integrations/langchain_agent.py:9,20-22,119-130`
- Modify: `src/mimic42/core/manager.py:286-293,322-329`
- Modify: `tests/integrations/test_telegram_tools.py` (в конец файла)
- Modify: `tests/integrations/test_langchain_agent.py` (в конец файла)

**Interfaces:**
- Consumes: `AgentRuntimeConfig.enabled_tools` из Task 2.
- Produces:
  - `build_telegram_langchain_tools(..., enabled_tools: frozenset[str] | None = None)`
  - `ToolAccessMiddleware(enabled_tools: frozenset[str])` — `awrap_tool_call` возвращает `ToolMessage(status="error")` на отключённый инструмент.

- [ ] **Step 1: Написать падающие тесты**

Дописать в конец `tests/integrations/test_telegram_tools.py`:

```python
@pytest.mark.asyncio
async def test_tools_filtered_by_enabled_allowlist() -> None:
    client = FakeTelethonClient()
    tools = build_telegram_langchain_tools(
        cast(TelethonRequestClient, client),
        enabled_tools=frozenset({"send_text_message", "view_image"}),
    )

    assert {tool.name for tool in tools} == {"send_text_message", "view_image"}


@pytest.mark.asyncio
async def test_tools_unfiltered_without_allowlist() -> None:
    client = FakeTelethonClient()
    tools = build_telegram_langchain_tools(cast(TelethonRequestClient, client))

    assert len(tools) == 91
```

Создать `tests/integrations/test_tool_access_middleware.py`:

```python
"""Отключённый инструмент не должен выполниться даже из собранного рантайма."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from mimic42.integrations.tool_access_middleware import ToolAccessMiddleware


def _request(name: str) -> Any:
    return type("Request", (), {"tool_call": {"name": name, "args": {}, "id": "call-1"}})()


@pytest.mark.asyncio
async def test_blocks_tool_outside_allowlist() -> None:
    middleware = ToolAccessMiddleware(frozenset({"send_text_message"}))
    called = False

    async def handler(request: Any) -> Any:
        nonlocal called
        called = True
        return ToolMessage(content="ok", tool_call_id="call-1")

    result = await middleware.awrap_tool_call(_request("delete_messages"), handler)

    assert called is False
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "delete_messages" in str(result.content)


@pytest.mark.asyncio
async def test_passes_allowed_tool_through() -> None:
    middleware = ToolAccessMiddleware(frozenset({"send_text_message"}))
    sentinel = ToolMessage(content="ok", tool_call_id="call-1")

    async def handler(request: Any) -> Any:
        return sentinel

    assert await middleware.awrap_tool_call(_request("send_text_message"), handler) is sentinel
```

Дописать в конец `tests/integrations/test_langchain_agent.py`:

```python
def test_build_langchain_agent_guards_disabled_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "graph"

    monkeypatch.setattr(langchain_agent_module, "create_agent", fake_create_agent)

    config = _config("mistral-small")
    config.enabled_tools = frozenset({"send_text_message"})
    build_langchain_agent(config)

    assert any(isinstance(m, ToolAccessMiddleware) for m in captured["middleware"])


def test_build_langchain_agent_without_allowlist_has_no_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "graph"

    monkeypatch.setattr(langchain_agent_module, "create_agent", fake_create_agent)

    build_langchain_agent(_config("mistral-small"))

    assert not any(isinstance(m, ToolAccessMiddleware) for m in captured["middleware"])
```

Импорт `ToolAccessMiddleware` добавить в шапку `tests/integrations/test_langchain_agent.py`:

```python
from mimic42.integrations.tool_access_middleware import ToolAccessMiddleware
```

Создать `tests/core/test_tool_allowlist_wiring.py`:

```python
"""Менеджер передаёт allowlist в сборщик инструментов в обоих путях сборки."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from mimic42.core import manager as manager_module
from mimic42.core.agent_runtime import AgentRuntimeConfig
from mimic42.core.manager import AgentManager
from mimic42.core.memory import RuntimeMemoryService

from .test_agent_runtime import FakeLangChainAgent, FakeTelegramClient


def _config() -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_api_id=12345,
        telegram_api_hash="hash",
        telegram_session_string="session",
        system_prompt="system",
        soul_prompt="soul",
        llm_model="mistral-small",
    )


def test_memory_runtime_passes_allowlist_to_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def capturing_builder(client: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(manager_module, "build_telegram_langchain_tools", capturing_builder)
    manager = AgentManager(
        memory_service_factory=lambda config: RuntimeMemoryService(),
        telegram_client_factory=lambda config: FakeTelegramClient(),
        langchain_agent_factory=lambda config, tools, session_factory: FakeLangChainAgent(),
    )
    config = _config()
    config.enabled_tools = frozenset({"send_text_message"})

    manager._build_runtime_with_memory(config)

    assert captured["enabled_tools"] == frozenset({"send_text_message"})


def test_default_runtime_passes_allowlist_to_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def capturing_builder(client: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(manager_module, "build_telegram_langchain_tools", capturing_builder)
    monkeypatch.setattr(manager_module, "build_telegram_client", lambda config: FakeTelegramClient())
    monkeypatch.setattr(
        manager_module, "build_langchain_agent", lambda *args, **kwargs: FakeLangChainAgent()
    )
    config = _config()
    config.enabled_tools = frozenset({"view_image"})

    manager_module._build_runtime(config)

    assert captured["enabled_tools"] == frozenset({"view_image"})


def test_runtime_without_allowlist_passes_none(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def capturing_builder(client: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(manager_module, "build_telegram_langchain_tools", capturing_builder)
    manager = AgentManager(
        memory_service_factory=lambda config: RuntimeMemoryService(),
        telegram_client_factory=lambda config: FakeTelegramClient(),
        langchain_agent_factory=lambda config, tools, session_factory: FakeLangChainAgent(),
    )

    manager._build_runtime_with_memory(_config())

    assert captured["enabled_tools"] is None
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `uv run pytest tests/integrations/test_tool_access_middleware.py tests/integrations/test_langchain_agent.py tests/core/test_tool_allowlist_wiring.py tests/integrations/test_telegram_tools.py -v -k "tool or allowlist"`
Expected: FAIL — модуль `tool_access_middleware` не найден; `enabled_tools` не принимается сборщиком.

- [ ] **Step 3: Добавить фильтрацию в сборщик инструментов**

В `src/mimic42/integrations/telegram_tools.py`:

1. Сигнатура `build_telegram_langchain_tools` (строка 2832) — добавить последний параметр:

```python
def build_telegram_langchain_tools(
    client: TelethonRequestClient,
    agent_id: UUID | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    media_uploader: MediaUploader | None = None,
    send_window: Any | None = None,
    media_refs: MediaRefCache | None = None,
    enabled_tools: frozenset[str] | None = None,
) -> list[BaseTool]:
    """Expose the Telegram tools as LangChain StructuredTools.

    ``enabled_tools`` limits the exposed set to the given allowlist; ``None``
    keeps the full catalog of 91 tools.
    """
```

2. В теле функции заменить `return [` на `tools = [` (начало литерала списка, строка ~2859).

3. В самом конце функции, после закрывающей скобки литерала (строка 3419, `    ]`), добавить:

```python

    if enabled_tools is None:
        return tools
    return [tool for tool in tools if tool.name in enabled_tools]
```

- [ ] **Step 4: Написать middleware страховки**

Создать `src/mimic42/integrations/tool_access_middleware.py`:

```python
"""Страховка: отключённый инструмент не выполняется даже из старого рантайма."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

ToolCallHandler = Callable[[ToolCallRequest], Awaitable[Any]]


class ToolAccessMiddleware(AgentMiddleware):
    """Отклоняет вызовы инструментов, которых нет в allowlist агента.

    Список инструментов фильтруется ещё при сборке рантайма; эта проверка
    закрывает окно гонки, когда старый рантайм доживает ход после reload.
    """

    def __init__(self, enabled_tools: frozenset[str]) -> None:
        super().__init__()
        self._enabled_tools = enabled_tools

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: ToolCallHandler,
    ) -> Any:
        tool_name = request.tool_call.get("name", "unknown")
        if tool_name not in self._enabled_tools:
            return ToolMessage(
                content=f"Инструмент «{tool_name}» отключён в настройках агента.",
                tool_call_id=request.tool_call.get("id", ""),
                status="error",
            )
        return await handler(request)
```

- [ ] **Step 5: Подключить middleware и проводку конфига**

1. `src/mimic42/integrations/langchain_agent.py` — импорт:

```python
from mimic42.integrations.tool_access_middleware import ToolAccessMiddleware
```

2. В `build_langchain_agent`, между созданием `middleware` и блоком `if session_factory is not None:`:

```python
    if config.enabled_tools is not None:
        # Внешний слой к ActivityMiddleware: заблокированный вызов не должен
        # попадать в ленту активности.
        middleware.append(ToolAccessMiddleware(config.enabled_tools))
```

3. `src/mimic42/core/manager.py` — в оба вызова `build_telegram_langchain_tools` (`_build_runtime_with_memory` и `_build_runtime`) добавить последним аргументом:

```python
                    enabled_tools=config.enabled_tools,
```

- [ ] **Step 6: Прогнать тесты и проверки**

Run: `uv run pytest tests/integrations/test_tool_access_middleware.py tests/integrations/test_langchain_agent.py tests/core/test_tool_allowlist_wiring.py tests/integrations/test_telegram_tools.py -v`
Expected: все зелёные, включая прежний `test_tools_exposed_in_langchain` на 91 инструмент.

Run: `uv run ruff check src tests && uv run ty check`
Expected: чисто.

- [ ] **Step 7: Коммит**

```bash
git add src/mimic42/integrations/telegram_tools.py src/mimic42/integrations/tool_access_middleware.py src/mimic42/integrations/langchain_agent.py src/mimic42/core/manager.py tests/integrations/test_telegram_tools.py tests/integrations/test_tool_access_middleware.py tests/integrations/test_langchain_agent.py tests/core/test_tool_allowlist_wiring.py
git commit -m "feat(agent): filter telegram tools and guard disabled calls"
```

---

### Task 4: Онбординг-бэкенд: настройки черновика доезжают до агента

**Files:**
- Modify: `src/mimic42/integrations/database_models.py:117-118`
- Modify: `src/mimic42/core/onboarding.py:6,70-82`
- Modify: `src/mimic42/integrations/database_onboarding.py:27-36,67-80`
- Modify: `src/mimic42/integrations/database_agent_store.py:98-101`
- Modify: `tests/integration/test_database_onboarding_repository.py` (в конец файла)
- Modify: `tests/integration/test_database_agent_store.py` (в конец файла)

**Interfaces:**
- Consumes: колонку `agent_onboarding_sessions.settings` из Task 1.
- Produces: `OnboardingSession.settings: dict[str, Any]`; `create_from_onboarding` переносит его в `agents.settings`.

- [ ] **Step 1: Написать падающие db-тесты**

Дописать в конец `tests/integration/test_database_onboarding_repository.py`:

```python
async def test_draft_settings_round_trip(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    repository = DatabaseOnboardingRepository(db_session_factory)
    session = OnboardingSession(
        onboarding_id=uuid4(),
        owner_id=clean_slot.persona("code").user_id,
        api_id=12345,
        api_hash_secret="encrypted-hash",
        phone_number="+79990000000",
        authorization_status=TelegramLoginStatus.AUTHORIZED,
        session_secret="encrypted-session",
        name="Mimic",
        soul_prompt="Short replies",
        settings={"enabled_tools": ["send_text_message", "view_image"]},
    )

    await repository.save(session)
    loaded = await repository.get(session.onboarding_id)

    assert loaded.settings == {"enabled_tools": ["send_text_message", "view_image"]}
```

Дописать в конец `tests/integration/test_database_agent_store.py`:

```python
async def test_create_from_onboarding_carries_tool_settings(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()
    store = DatabaseAgentStore(db_session_factory)
    session = _make_session(owner_id, agent_id, "Mimic")
    session.settings = {"enabled_tools": ["send_text_message"]}

    await store.create_from_onboarding(session)

    async with db_session_factory() as db_session:
        settings = await db_session.scalar(
            select(AgentModel.settings).where(AgentModel.id == agent_id)
        )
    assert settings == {"enabled_tools": ["send_text_message"]}
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `uv run pytest -m db tests/integration/test_database_onboarding_repository.py tests/integration/test_database_agent_store.py -v`
Expected: FAIL — `OnboardingSession` не принимает `settings`; в `AgentModel.settings` пусто.

- [ ] **Step 3: Добавить колонку и поле**

1. `src/mimic42/integrations/database_models.py`, в `AgentOnboardingSessionModel` после `soul_prompt`:

```python
    soul_prompt: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
```

2. `src/mimic42/core/onboarding.py`:

- расширить импорт: `from typing import Any, Protocol`
- в `OnboardingSession` после `soul_prompt`:

```python
    soul_prompt: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Провести поле через репозиторий и финализацию**

1. `src/mimic42/integrations/database_onboarding.py`:

- в `save`, после `model.soul_prompt = session.soul_prompt`:

```python
            model.settings = session.settings
```

- в `_model_to_session`, после `soul_prompt=model.soul_prompt`:

```python
        settings=model.settings or {},
```

2. `src/mimic42/integrations/database_agent_store.py`, в `create_from_onboarding`, после `agent.soul_prompt = session.soul_prompt`:

```python
            # Настройки инструментов, выбранные пресетом в визарде, переезжают
            # в агента вместе с характером.
            agent.settings = dict(session.settings)
```

- [ ] **Step 5: Прогнать тесты**

Run: `uv run pytest -m db tests/integration/test_database_onboarding_repository.py tests/integration/test_database_agent_store.py tests/integration/test_onboarding_rls.py -v`
Expected: все зелёные, включая прежний `test_database_onboarding_repository_maps_session_rows` (сравнение `loaded == session`).

- [ ] **Step 6: Коммит**

```bash
git add src/mimic42/integrations/database_models.py src/mimic42/core/onboarding.py src/mimic42/integrations/database_onboarding.py src/mimic42/integrations/database_agent_store.py tests/integration/test_database_onboarding_repository.py tests/integration/test_database_agent_store.py
git commit -m "feat(onboarding): carry draft tool settings into the created agent"
```

---

### Task 5: Каталог инструментов с названиями и описаниями

**Files:**
- Create: `frontend/src/lib/tools/toolInfo.ts`
- Create: `frontend/src/__tests__/tool-info.test.ts`

**Interfaces:**
- Consumes: `TOOL_CATALOG` из `@/lib/activity/toolCatalog` (для теста синхронности; в компонентах — иконки через `getToolMeta`).
- Produces:
  - `interface ToolInfo { name: string; group: ToolGroup; title: string; description: string }`
  - `TOOL_INFO: ToolInfo[]` — 91 запись в порядке групп
  - `TOOL_GROUP_ORDER: { id: ToolGroup; title: string }[]` — 10 групп в фиксированном порядке.

- [ ] **Step 1: Написать падающий тест**

Создать `frontend/src/__tests__/tool-info.test.ts`:

```ts
import { describe, expect, test } from 'bun:test';
import { TOOL_CATALOG } from '@/lib/activity/toolCatalog';
import { TOOL_GROUP_ORDER, TOOL_INFO } from '@/lib/tools/toolInfo';

describe('toolInfo', () => {
  test('перечисляет все 91 инструмент каталога действий без повторов', () => {
    const names = TOOL_INFO.map((tool) => tool.name);
    expect(names.length).toBe(91);
    expect(new Set(names).size).toBe(91);
    expect(new Set(names)).toEqual(new Set(Object.keys(TOOL_CATALOG)));
  });

  test('у каждого инструмента есть название и описание', () => {
    for (const tool of TOOL_INFO) {
      expect(tool.title.trim().length).toBeGreaterThan(0);
      expect(tool.description.trim().length).toBeGreaterThan(0);
    }
  });

  test('названия уникальны: по ним интерфейс подписывает переключатели', () => {
    const titles = TOOL_INFO.map((tool) => tool.title);
    expect(new Set(titles).size).toBe(titles.length);
  });

  test('порядок групп фиксирован и покрывает все группы каталога', () => {
    expect(TOOL_GROUP_ORDER.map((group) => group.id)).toEqual([
      'messages',
      'dialogs',
      'media',
      'stickers',
      'profile',
      'groups',
      'utils',
      'folders',
      'bots',
      'privacy',
    ]);
    const known = new Set(TOOL_GROUP_ORDER.map((group) => group.id));
    for (const tool of TOOL_INFO) expect(known.has(tool.group)).toBe(true);
  });
});
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd frontend && bun test src/__tests__/tool-info.test.ts`
Expected: FAIL — модуль `@/lib/tools/toolInfo` не найден.

- [ ] **Step 3: Написать каталог**

Создать `frontend/src/lib/tools/toolInfo.ts`:

```ts
import type { ToolGroup } from '@/lib/activity/toolCatalog';

/**
 * Нейтральные названия и описания инструментов для настроек.
 * Порядок массива задаёт порядок строк внутри групп; группы идут в порядке
 * TOOL_GROUP_ORDER. Синхронность с activity-каталогом (TOOL_CATALOG) стережёт
 * __tests__/tool-info.test.ts.
 */
export interface ToolInfo {
  name: string;
  group: ToolGroup;
  title: string;
  description: string;
}

export const TOOL_GROUP_ORDER: { id: ToolGroup; title: string }[] = [
  { id: 'messages', title: 'Сообщения' },
  { id: 'dialogs', title: 'Диалоги и поиск' },
  { id: 'media', title: 'Медиа' },
  { id: 'stickers', title: 'Стикеры' },
  { id: 'profile', title: 'Профиль и контакты' },
  { id: 'groups', title: 'Группы и права' },
  { id: 'utils', title: 'Разное' },
  { id: 'folders', title: 'Папки чатов' },
  { id: 'bots', title: 'Боты и кнопки' },
  { id: 'privacy', title: 'Приватность и аккаунт' },
];

export const TOOL_INFO: ToolInfo[] = [
  // Сообщения
  { name: 'send_text_message', group: 'messages', title: 'Отправка сообщения', description: 'Отправляет текст в чат или комментарий под постом канала.' },
  { name: 'edit_text_message', group: 'messages', title: 'Редактирование сообщения', description: 'Меняет текст сообщения, отправленного ботом.' },
  { name: 'delete_messages', group: 'messages', title: 'Удаление сообщений', description: 'Удаляет сообщения в чате, в том числе у всех.' },
  { name: 'forward_messages', group: 'messages', title: 'Пересылка сообщений', description: 'Пересылает сообщения из одного чата в другой.' },
  { name: 'pin_message', group: 'messages', title: 'Закрепление сообщения', description: 'Закрепляет сообщение в чате.' },
  { name: 'unpin_message', group: 'messages', title: 'Открепление сообщения', description: 'Снимает закрепление с сообщения.' },
  { name: 'unpin_all_messages', group: 'messages', title: 'Открепление всех сообщений', description: 'Снимает закрепление со всех сообщений чата.' },
  { name: 'send_chat_action', group: 'messages', title: 'Индикатор действия', description: 'Показывает «печатает», «записывает голосовое» и похожие статусы.' },
  { name: 'send_reaction', group: 'messages', title: 'Реакции', description: 'Ставит или снимает реакцию на сообщение.' },
  { name: 'get_message_reactions', group: 'messages', title: 'Просмотр реакций', description: 'Показывает, кто и как отреагировал на сообщение.' },
  { name: 'mark_chat_as_read', group: 'messages', title: 'Отметка прочитанного', description: 'Помечает сообщения в чате прочитанными.' },
  { name: 'get_messages', group: 'messages', title: 'История сообщений', description: 'Читает историю переписки в чате.' },

  // Диалоги и поиск
  { name: 'get_dialogs', group: 'dialogs', title: 'Список диалогов', description: 'Показывает недавние чаты, каналы и переписки.' },
  { name: 'search_messages', group: 'dialogs', title: 'Поиск по сообщениям', description: 'Ищет сообщения по тексту в чате и по всем чатам.' },
  { name: 'delete_dialog', group: 'dialogs', title: 'Удаление диалога', description: 'Удаляет переписку вместе с историей.' },
  { name: 'archive_dialogs', group: 'dialogs', title: 'Архивирование чатов', description: 'Убирает чаты в архив.' },
  { name: 'unarchive_dialogs', group: 'dialogs', title: 'Разархивирование чатов', description: 'Возвращает чаты из архива.' },
  { name: 'get_common_chats', group: 'dialogs', title: 'Общие чаты', description: 'Показывает общие чаты с пользователем.' },

  // Медиа
  { name: 'send_file', group: 'media', title: 'Отправка файлов', description: 'Отправляет фото, документы, стикеры, голосовые и кружки.' },
  { name: 'view_image', group: 'media', title: 'Просмотр изображений', description: 'Открывает картинку из сообщения и описывает её содержимое.' },
  { name: 'set_profile_photo', group: 'media', title: 'Смена фото профиля', description: 'Обновляет аватар аккаунта.' },
  { name: 'send_voice_note', group: 'media', title: 'Голосовые сообщения', description: 'Записывает и отправляет голосовое сообщение.' },
  { name: 'send_video_note', group: 'media', title: 'Видеокружки', description: 'Записывает и отправляет видеокружок.' },

  // Стикеры
  { name: 'get_sticker_sets', group: 'stickers', title: 'Список стикерпаков', description: 'Показывает установленные наборы стикеров.' },
  { name: 'get_stickers_in_set', group: 'stickers', title: 'Стикеры в наборе', description: 'Показывает стикеры выбранного набора.' },
  { name: 'search_sticker_sets', group: 'stickers', title: 'Поиск стикерпаков', description: 'Ищет наборы стикеров по названию.' },
  { name: 'install_sticker_set', group: 'stickers', title: 'Установка стикерпака', description: 'Добавляет набор стикеров в аккаунт.' },
  { name: 'uninstall_sticker_set', group: 'stickers', title: 'Удаление стикерпака', description: 'Убирает набор стикеров из аккаунта.' },
  { name: 'send_sticker', group: 'stickers', title: 'Отправка стикера', description: 'Отправляет стикер в чат.' },

  // Профиль и контакты
  { name: 'get_profile', group: 'profile', title: 'Просмотр профиля', description: 'Показывает информацию о пользователе или канале.' },
  { name: 'update_profile_info', group: 'profile', title: 'Изменение профиля', description: 'Меняет имя, фамилию и описание аккаунта.' },
  { name: 'update_username', group: 'profile', title: 'Смена username', description: 'Меняет @username аккаунта.' },
  { name: 'add_contact', group: 'profile', title: 'Добавление контакта', description: 'Добавляет пользователя в контакты.' },
  { name: 'delete_contact', group: 'profile', title: 'Удаление контакта', description: 'Убирает пользователя из контактов.' },
  { name: 'get_contacts', group: 'profile', title: 'Список контактов', description: 'Показывает контакты аккаунта.' },

  // Группы и права
  { name: 'get_chat_info', group: 'groups', title: 'Информация о чате', description: 'Показывает название, описание и тип чата.' },
  { name: 'check_admin_permissions', group: 'groups', title: 'Проверка прав', description: 'Показывает права аккаунта в чате.' },
  { name: 'create_group', group: 'groups', title: 'Создание группы', description: 'Создаёт новую группу.' },
  { name: 'create_channel', group: 'groups', title: 'Создание канала', description: 'Создаёт новый канал.' },
  { name: 'invite_to_channel', group: 'groups', title: 'Приглашение участника', description: 'Добавляет пользователя в группу или канал.' },
  { name: 'kick_chat_member', group: 'groups', title: 'Исключение участника', description: 'Удаляет участника из чата.' },
  { name: 'ban_chat_member', group: 'groups', title: 'Бан участника', description: 'Запрещает участнику доступ в чат.' },
  { name: 'restrict_chat_member', group: 'groups', title: 'Ограничение участника', description: 'Ограничивает права участника в чате.' },
  { name: 'promote_chat_member', group: 'groups', title: 'Назначение администратора', description: 'Выдаёт участнику права администратора.' },
  { name: 'get_chat_members', group: 'groups', title: 'Список участников', description: 'Показывает участников чата.' },
  { name: 'get_chat_admin_log', group: 'groups', title: 'Журнал действий', description: 'Показывает историю действий администраторов.' },
  { name: 'edit_chat_title', group: 'groups', title: 'Название чата', description: 'Меняет название чата.' },
  { name: 'edit_chat_about', group: 'groups', title: 'Описание чата', description: 'Меняет описание чата.' },
  { name: 'edit_chat_photo', group: 'groups', title: 'Фото чата', description: 'Меняет аватар чата.' },
  { name: 'update_chat_public_link', group: 'groups', title: 'Публичная ссылка', description: 'Меняет публичный адрес чата.' },
  { name: 'set_chat_default_banned_rights', group: 'groups', title: 'Права по умолчанию', description: 'Настраивает права новых участников чата.' },
  { name: 'toggle_chat_signatures', group: 'groups', title: 'Подписи авторов', description: 'Включает или выключает подписи под сообщениями.' },
  { name: 'delete_channel', group: 'groups', title: 'Удаление канала', description: 'Удаляет канал или группу.' },
  { name: 'toggle_join_requests', group: 'groups', title: 'Заявки на вход', description: 'Включает или выключает заявки на вступление.' },
  { name: 'toggle_join_to_send', group: 'groups', title: 'Вход для записи', description: 'Запрещает писать до вступления в чат.' },
  { name: 'toggle_slow_mode', group: 'groups', title: 'Медленный режим', description: 'Настраивает задержку между сообщениями.' },
  { name: 'set_discussion_group', group: 'groups', title: 'Группа обсуждений', description: 'Привязывает чат обсуждений к каналу.' },
  { name: 'join_channel_discussion', group: 'groups', title: 'Вход в обсуждение', description: 'Открывает обсуждение канала и присоединяется к нему.' },
  { name: 'get_discussion_messages', group: 'groups', title: 'Чтение обсуждения', description: 'Читает комментарии под постом канала.' },
  { name: 'toggle_forum', group: 'groups', title: 'Режим форума', description: 'Включает или выключает темы в группе.' },
  { name: 'toggle_pre_history_hidden', group: 'groups', title: 'Скрытие истории', description: 'Скрывает старые сообщения от новых участников.' },
  { name: 'toggle_participants_hidden', group: 'groups', title: 'Скрытие участников', description: 'Скрывает список участников чата.' },
  { name: 'edit_chat_location', group: 'groups', title: 'Геолокация чата', description: 'Указывает местоположение чата.' },
  { name: 'toggle_anti_spam', group: 'groups', title: 'Антиспам', description: 'Включает или выключает агрессивный антиспам.' },
  { name: 'set_chat_admin_rights', group: 'groups', title: 'Права администратора', description: 'Настраивает права администратора в чате.' },
  { name: 'set_chat_banned_rights', group: 'groups', title: 'Ограничения участника', description: 'Настраивает запреты для участника.' },

  // Разное
  { name: 'join_channel', group: 'utils', title: 'Вступление в канал', description: 'Подписывает аккаунт на канал или группу.' },
  { name: 'send_poll', group: 'utils', title: 'Опросы', description: 'Отправляет опрос в чат.' },
  { name: 'transcribe_voice_note', group: 'utils', title: 'Расшифровка голосовых', description: 'Переводит голосовое сообщение в текст.' },
  { name: 'read_document_file', group: 'utils', title: 'Чтение документов', description: 'Открывает и читает присланный файл.' },
  { name: 'set_wakeup_timer', group: 'utils', title: 'Напоминание', description: 'Просыпается позже, чтобы вернуться к разговору.' },
  { name: 'mute_chat', group: 'utils', title: 'Отключение уведомлений', description: 'Убирает уведомления от чата.' },
  { name: 'unmute_chat', group: 'utils', title: 'Включение уведомлений', description: 'Возвращает уведомления от чата.' },
  { name: 'send_location', group: 'utils', title: 'Геолокация', description: 'Отправляет точку на карте.' },
  { name: 'send_venue', group: 'utils', title: 'Место на карте', description: 'Отправляет карточку места.' },
  { name: 'search_location', group: 'utils', title: 'Поиск места', description: 'Ищет место по названию.' },

  // Папки чатов
  { name: 'get_chat_folders', group: 'folders', title: 'Папки чатов', description: 'Показывает папки с чатами.' },
  { name: 'create_or_update_chat_folder', group: 'folders', title: 'Настройка папок', description: 'Создаёт или меняет папку чатов.' },
  { name: 'delete_chat_folder', group: 'folders', title: 'Удаление папок', description: 'Удаляет папку чатов.' },

  // Боты и кнопки
  { name: 'get_message_buttons', group: 'bots', title: 'Кнопки сообщения', description: 'Показывает кнопки под сообщением.' },
  { name: 'click_inline_button', group: 'bots', title: 'Нажатие кнопки', description: 'Нажимает кнопку под сообщением.' },
  { name: 'click_reply_keyboard_button', group: 'bots', title: 'Нажатие клавиатуры', description: 'Нажимает кнопку клавиатуры внизу чата.' },
  { name: 'query_inline_bot', group: 'bots', title: 'Запрос к боту', description: 'Спрашивает инлайн-бота.' },
  { name: 'send_inline_bot_result', group: 'bots', title: 'Отправка результата', description: 'Отправляет выбранный результат инлайн-бота.' },
  { name: 'start_bot', group: 'bots', title: 'Запуск бота', description: 'Открывает бота и нажимает «Старт».' },

  // Приватность и аккаунт
  { name: 'get_privacy_settings', group: 'privacy', title: 'Настройки приватности', description: 'Показывает, кто видит профиль и активность.' },
  { name: 'set_privacy_settings', group: 'privacy', title: 'Изменение приватности', description: 'Меняет настройки приватности аккаунта.' },
  { name: 'get_global_settings', group: 'privacy', title: 'Общие настройки', description: 'Показывает общие настройки аккаунта.' },
  { name: 'set_global_settings', group: 'privacy', title: 'Изменение общих настроек', description: 'Меняет общие настройки аккаунта.' },
  { name: 'get_content_settings', group: 'privacy', title: 'Настройки контента', description: 'Показывает фильтр чувствительного контента.' },
  { name: 'set_content_settings', group: 'privacy', title: 'Изменение настроек контента', description: 'Включает или выключает фильтр чувствительного контента.' },
];
```

- [ ] **Step 4: Запустить тест**

Run: `cd frontend && bun test src/__tests__/tool-info.test.ts && bun run typecheck`
Expected: 4 passed, typecheck без ошибок.

- [ ] **Step 5: Коммит**

```bash
git add frontend/src/lib/tools/toolInfo.ts frontend/src/__tests__/tool-info.test.ts
git commit -m "feat(frontend): tool settings catalog"
```

---

### Task 6: Общий переключатель `Switch`

**Files:**
- Create: `frontend/src/components/ui/switch.tsx`
- Modify: `frontend/src/components/agent/FirstCommentSettings.tsx:11-16,142-146,381-414`

**Interfaces:**
- Consumes: существующий локальный `Toggle` из `FirstCommentSettings`.
- Produces: `Switch({ checked, onChange, label })` в `@/components/ui/switch` — тот же вид и поведение (`role="switch"`).

- [ ] **Step 1: Создать общий компонент**

Создать `frontend/src/components/ui/switch.tsx`:

```tsx
'use client';

import { cn } from '@/lib/utils';

/**
 * Переключатель вкл/выкл. Вынесен из FirstCommentSettings без изменения
 * поведения: `role="switch"`, доступное имя обязательно.
 */
export function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        checked ? 'border-primary bg-primary' : 'border-border bg-muted',
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          'inline-block h-4 w-4 rounded-full bg-foreground transition-transform',
          checked ? 'translate-x-6' : 'translate-x-1',
        )}
      />
    </button>
  );
}
```

- [ ] **Step 2: Перевести FirstCommentSettings на общий компонент**

В `frontend/src/components/agent/FirstCommentSettings.tsx`:

1. Добавить импорт рядом с другими `@/components/ui/*`:

```tsx
import { Switch } from '@/components/ui/switch';
```

2. Заменить использование `<Toggle` (строка ~142):

```tsx
        <Switch
          checked={value.enabled}
          onChange={(enabled) => onChange((prev) => ({ ...prev, enabled }))}
          label="Первый комментарий"
        />
```

3. Удалить локальную функцию `Toggle` вместе с комментарием-разделителем `// ── Переключатель ──` (строки 381-414).

- [ ] **Step 3: Проверить, что ничего не сломалось**

Run: `cd frontend && bun test src/__tests__/first-comment.test.tsx && bun run typecheck && bunx next lint`
Expected: тесты первого комментария зелёные, typecheck и lint чистые.

- [ ] **Step 4: Коммит**

```bash
git add frontend/src/components/ui/switch.tsx frontend/src/components/agent/FirstCommentSettings.tsx
git commit -m "refactor(frontend): extract shared switch control"
```

---

### Task 7: Раздел «Инструменты» в настройках агента

**Files:**
- Create: `frontend/src/lib/tools/agentTools.ts`
- Create: `frontend/src/components/agent/ToolsSettings.tsx`
- Create: `frontend/src/__tests__/agent-tools.test.ts`
- Create: `frontend/src/__tests__/tools-settings.test.tsx`
- Modify: `frontend/src/lib/validators.ts:142-159`
- Modify: `frontend/src/components/agent/TabSettings.tsx`

**Interfaces:**
- Consumes: `TOOL_INFO`, `TOOL_GROUP_ORDER` из Task 5; `Switch` из Task 6; `getToolMeta` из activity-каталога.
- Produces:
  - `readEnabledTools(settings: Record<string, unknown> | null | undefined): string[] | null`
  - `ToolsSettings({ value, onChange }: { value: string[] | null; onChange: (next: string[] | null) => void })`
  - в `agentSettingsSchema` поле `enabled_tools: string[] | null | undefined`
  - `TabSettings` сохраняет `settings.enabled_tools` (при `null` — удаляет ключ).

- [ ] **Step 1: Написать падающие тесты**

Создать `frontend/src/__tests__/agent-tools.test.ts`:

```ts
import { describe, expect, test } from 'bun:test';
import { readEnabledTools } from '@/lib/tools/agentTools';
import { agentSettingsSchema } from '@/lib/validators';

describe('readEnabledTools', () => {
  test('без настроек и без ключа — режим «включены все»', () => {
    expect(readEnabledTools(null)).toBeNull();
    expect(readEnabledTools({})).toBeNull();
    expect(readEnabledTools({ enabled_tools: null })).toBeNull();
  });

  test('пустой список — пустой allowlist', () => {
    expect(readEnabledTools({ enabled_tools: [] })).toEqual([]);
  });

  test('список имён возвращается как есть', () => {
    expect(readEnabledTools({ enabled_tools: ['send_text_message', 'view_image'] })).toEqual([
      'send_text_message',
      'view_image',
    ]);
  });

  test('нестроковые элементы отбрасываются', () => {
    expect(readEnabledTools({ enabled_tools: ['send_text_message', 42, null] })).toEqual([
      'send_text_message',
    ]);
  });

  test('список без валидных строк — мусор, как и на бэкенде', () => {
    expect(readEnabledTools({ enabled_tools: [42, '  '] })).toBeNull();
  });
});

describe('agentSettingsSchema.enabled_tools', () => {
  const base = { name: 'Мимик', soul_prompt: '', model: 'openrouter/free' };

  test('принимает список, пустой список, null и отсутствие ключа', () => {
    expect(agentSettingsSchema.safeParse({ ...base, enabled_tools: ['send_text_message'] }).success).toBe(true);
    expect(agentSettingsSchema.safeParse({ ...base, enabled_tools: [] }).success).toBe(true);
    expect(agentSettingsSchema.safeParse({ ...base, enabled_tools: null }).success).toBe(true);
    expect(agentSettingsSchema.safeParse(base).success).toBe(true);
  });

  test('отклоняет нестроковые имена', () => {
    expect(agentSettingsSchema.safeParse({ ...base, enabled_tools: [42] }).success).toBe(false);
  });
});
```

Создать `frontend/src/__tests__/tools-settings.test.tsx`:

```tsx
import { describe, expect, mock, test } from 'bun:test';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ToolsSettings } from '@/components/agent/ToolsSettings';

describe('ToolsSettings', () => {
  test('свёрнутые группы показывают счётчики, раскрытие показывает инструменты', async () => {
    const user = userEvent.setup();
    render(<ToolsSettings value={null} onChange={() => {}} />);
    const section = screen.getByTestId('tools-settings');
    expect(within(section).getByText('Включено 91 из 91')).toBeTruthy();
    expect(within(section).queryByRole('switch', { name: 'Отправка сообщения' })).toBeNull();

    await user.click(within(section).getByTestId('tool-group-messages'));
    expect(within(section).getByRole('switch', { name: 'Отправка сообщения' })).toBeTruthy();
  });

  test('выключение инструмента отдаёт явный список без него', async () => {
    const user = userEvent.setup();
    const onChange = mock((_next: string[] | null) => {});
    render(<ToolsSettings value={null} onChange={onChange} />);
    const section = screen.getByTestId('tools-settings');
    await user.click(within(section).getByTestId('tool-group-messages'));
    await user.click(within(section).getByRole('switch', { name: 'Отправка сообщения' }));

    const [next] = onChange.mock.calls[0] as [string[]];
    expect(next).not.toContain('send_text_message');
    expect(next).toContain('view_image');
    expect(next.length).toBe(90);
  });

  test('поиск находит по названию и раскрывает группы', async () => {
    const user = userEvent.setup();
    render(<ToolsSettings value={null} onChange={() => {}} />);
    const section = screen.getByTestId('tools-settings');
    await user.type(within(section).getByLabel('Поиск'), 'Удаление канала');

    expect(within(section).getByRole('switch', { name: 'Удаление канала' })).toBeTruthy();
    expect(within(section).queryByRole('switch', { name: 'Отправка сообщения' })).toBeNull();
  });

  test('«Включить все» сбрасывает режим в null', async () => {
    const user = userEvent.setup();
    const onChange = mock((_next: string[] | null) => {});
    render(<ToolsSettings value={['send_text_message']} onChange={onChange} />);

    await user.click(screen.getByRole('button', { name: 'Включить все' }));

    expect(onChange).toHaveBeenCalledWith(null);
  });

  test('неизвестные каталогу имена сохраняются при переключении', async () => {
    const user = userEvent.setup();
    const onChange = mock((_next: string[] | null) => {});
    render(<ToolsSettings value={['future_tool', 'send_text_message']} onChange={onChange} />);
    const section = screen.getByTestId('tools-settings');
    await user.click(within(section).getByTestId('tool-group-messages'));
    await user.click(within(section).getByRole('switch', { name: 'Отправка сообщения' }));

    const [next] = onChange.mock.calls[0] as [string[]];
    expect(next).toContain('future_tool');
    expect(next).not.toContain('send_text_message');
  });
});
```

- [ ] **Step 2: Запустить тесты и убедиться, что падают**

Run: `cd frontend && bun test src/__tests__/agent-tools.test.ts src/__tests__/tools-settings.test.tsx`
Expected: FAIL — модули `@/lib/tools/agentTools` и `@/components/agent/ToolsSettings` не найдены.

- [ ] **Step 3: Написать чтение настройки**

Создать `frontend/src/lib/tools/agentTools.ts`:

```ts
/**
 * Настройки инструментов в `agents.settings` — зеркало
 * `src/mimic42/core/tool_config.py`.
 */

/**
 * Прочитать allowlist инструментов из settings.
 *
 * `null` — ключа нет (включены все) или значение нечитаемо. Пустой массив —
 * честный пустой allowlist. Непустой массив без валидных строк — мусор:
 * ведём себя как при отсутствии ключа, как и бэкенд.
 */
export function readEnabledTools(
  settings: Record<string, unknown> | null | undefined,
): string[] | null {
  if (!settings) return null;
  const value = settings.enabled_tools;
  if (!Array.isArray(value)) return null;
  const names = value.filter(
    (item): item is string => typeof item === 'string' && item.trim().length > 0,
  );
  if (names.length === 0 && value.length > 0) return null;
  return names;
}
```

- [ ] **Step 4: Написать секцию переключателей**

Создать `frontend/src/components/agent/ToolsSettings.tsx`:

```tsx
'use client';

import { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { getToolMeta, type ToolGroup } from '@/lib/activity/toolCatalog';
import { TOOL_GROUP_ORDER, TOOL_INFO, type ToolInfo } from '@/lib/tools/toolInfo';

/**
 * Переключатели инструментов агента.
 *
 * `value === null` — режим «включены все»: ключа в настройках нет.
 * Явный список — allowlist. Имена, которых нет в каталоге фронта, сохраняются
 * как есть: настройка не должна выключать инструменты из будущего бэкенда.
 */
export function ToolsSettings({
  value,
  onChange,
}: {
  value: string[] | null;
  onChange: (next: string[] | null) => void;
}) {
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState<string[]>([]);

  const knownNames = useMemo(() => TOOL_INFO.map((tool) => tool.name), []);
  const enabled = useMemo(() => (value === null ? null : new Set(value)), [value]);
  const normalizedQuery = query.trim().toLowerCase();

  const matches = (tool: ToolInfo) =>
    normalizedQuery.length === 0 ||
    tool.title.toLowerCase().includes(normalizedQuery) ||
    tool.description.toLowerCase().includes(normalizedQuery) ||
    tool.name.toLowerCase().includes(normalizedQuery);

  const isOn = (name: string) => enabled === null || enabled.has(name);

  const updateSelection = (mutate: (base: Set<string>) => void) => {
    const base = new Set(enabled ?? knownNames);
    mutate(base);
    onChange(Array.from(base));
  };

  const toggleTool = (name: string, next: boolean) =>
    updateSelection((base) => (next ? base.add(name) : base.delete(name)));

  const toggleGroup = (group: ToolGroup, next: boolean) => {
    const names = TOOL_INFO.filter((tool) => tool.group === group).map((tool) => tool.name);
    updateSelection((base) => {
      for (const name of names) {
        if (next) base.add(name);
        else base.delete(name);
      }
    });
  };

  const enabledCount =
    enabled === null ? knownNames.length : knownNames.filter((name) => enabled.has(name)).length;

  return (
    <section className="space-y-3" data-testid="tools-settings">
      <div className="space-y-1">
        <h3 className="font-display text-sm text-foreground">Инструменты</h3>
        <p className="font-mono text-xs text-muted-foreground max-w-prose">
          Что Мимик может делать в Telegram. Отключённые инструменты не показываются модели и не
          выполняются. Обычные ответы в диалогах от этого не зависят.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-xs text-muted-foreground">
          Включено {enabledCount} из {knownNames.length}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onChange(null)}
          disabled={enabled === null}
        >
          Включить все
        </Button>
      </div>

      <Input
        label="Поиск"
        placeholder="Название, описание или имя инструмента"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      <div className="space-y-2">
        {TOOL_GROUP_ORDER.map((group) => {
          const groupTools = TOOL_INFO.filter((tool) => tool.group === group.id);
          const visibleTools = groupTools.filter(matches);
          if (visibleTools.length === 0) return null;

          const isOpen = normalizedQuery.length > 0 || expanded.includes(group.id);
          const groupOnCount = groupTools.filter((tool) => isOn(tool.name)).length;

          return (
            <div key={group.id} className="rounded-sm border border-border">
              <div className="flex items-center justify-between gap-3 px-3 py-2">
                <button
                  type="button"
                  aria-expanded={isOpen}
                  data-testid={`tool-group-${group.id}`}
                  onClick={() =>
                    setExpanded((prev) =>
                      prev.includes(group.id)
                        ? prev.filter((id) => id !== group.id)
                        : [...prev, group.id],
                    )
                  }
                  className="flex min-w-0 flex-1 items-center gap-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                >
                  {isOpen ? (
                    <ChevronDown
                      className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                      aria-hidden="true"
                    />
                  ) : (
                    <ChevronRight
                      className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                      aria-hidden="true"
                    />
                  )}
                  <span className="font-mono text-xs text-foreground">{group.title}</span>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {groupOnCount} из {groupTools.length}
                  </span>
                </button>
                <Switch
                  checked={groupOnCount === groupTools.length}
                  onChange={(next) => toggleGroup(group.id, next)}
                  label={`Все инструменты группы «${group.title}»`}
                />
              </div>

              {isOpen && (
                <ul className="divide-y divide-border border-t border-border">
                  {visibleTools.map((tool) => {
                    const Icon = getToolMeta(tool.name).icon;
                    return (
                      <li
                        key={tool.name}
                        className="flex items-start justify-between gap-3 px-3 py-2"
                      >
                        <div className="flex min-w-0 items-start gap-2">
                          <Icon
                            className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground"
                            aria-hidden="true"
                          />
                          <div className="min-w-0">
                            <span className="block font-mono text-xs text-foreground">
                              {tool.title}
                            </span>
                            <span className="block font-mono text-[11px] text-muted-foreground">
                              {tool.description}
                            </span>
                          </div>
                        </div>
                        <Switch
                          checked={isOn(tool.name)}
                          onChange={(next) => toggleTool(tool.name, next)}
                          label={tool.title}
                        />
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
```

- [ ] **Step 5: Добавить поле в схему валидации**

В `frontend/src/lib/validators.ts`, в `agentSettingsSchema` после `first_comment`:

```ts
  // Необязательное: у агентов без настройки ключа нет — включены все.
  enabled_tools: z
    .array(z.string().min(1, 'Имя инструмента не должно быть пустым'))
    .max(200, 'Слишком много инструментов')
    .nullable()
    .optional(),
```

- [ ] **Step 6: Встроить секцию в форму и научить её сохранять**

В `frontend/src/components/agent/TabSettings.tsx`:

1. Импорты:

```tsx
import { ToolsSettings } from '@/components/agent/ToolsSettings';
import { readEnabledTools } from '@/lib/tools/agentTools';
```

2. Начальное состояние (в `useState`):

```tsx
  const [values, setValues] = useState<SettingsFormValues>({
    name: '', soul_prompt: '', reasoning_effort: 'high', model: DEFAULT_MODEL,
    first_comment: EMPTY_FIRST_COMMENT, enabled_tools: null,
  });
```

3. В `useEffect` при `details`:

```tsx
        first_comment: readFirstComment(details.settings),
        enabled_tools: readEnabledTools(details.settings),
```

4. В разметке — между блоком `reasoningOptions` и `<FirstCommentSettingsSection ...>`:

```tsx
      <ToolsSettings
        value={values.enabled_tools ?? null}
        onChange={(enabled) => {
          setValues((v) => ({ ...v, enabled_tools: enabled }));
          setDirty(true);
        }}
      />
```

5. В `handleSave` заменить формирование `submissionData` (строки 84-96) на:

```tsx
      // Merge instead of overwrite: keep settings keys the form does not own.
      const existingSettings = (details?.settings ?? {}) as Record<string, unknown>;
      const mergedSettings: Record<string, unknown> = {
        ...existingSettings,
        // Models without exposed effort selection must not receive a stale
        // stored effort: "none" keeps the request clean.
        reasoning_effort: reasoningOptions === null ? 'none' : result.data.reasoning_effort,
        model: result.data.model,
        first_comment: result.data.first_comment ?? EMPTY_FIRST_COMMENT,
      };
      if (result.data.enabled_tools != null) {
        mergedSettings.enabled_tools = result.data.enabled_tools;
      } else {
        // null — режим «включены все»: ключ убирается, а не пишется пустым.
        delete mergedSettings.enabled_tools;
      }
      const submissionData = {
        name: result.data.name,
        soul_prompt: result.data.soul_prompt,
        settings: mergedSettings,
      };
```

- [ ] **Step 7: Прогнать тесты и проверки**

Run: `cd frontend && bun test && bun run typecheck && bunx next lint`
Expected: все тесты зелёные (включая прежние `first-comment.test.tsx`, `preset-picker.test.tsx`), typecheck и lint чистые.

- [ ] **Step 8: Коммит**

```bash
git add frontend/src/lib/tools/agentTools.ts frontend/src/components/agent/ToolsSettings.tsx frontend/src/__tests__/agent-tools.test.ts frontend/src/__tests__/tools-settings.test.tsx frontend/src/lib/validators.ts frontend/src/components/agent/TabSettings.tsx
git commit -m "feat(frontend): per-agent tool toggles on settings tab"
```

---

### Task 8: Пресеты передают настройки инструментов

**Files:**
- Modify: `frontend/src/types/index.ts:404-415`
- Modify: `frontend/src/components/agent/PresetPicker.tsx`
- Modify: `frontend/src/__tests__/preset-picker.test.tsx`
- Modify: `frontend/src/components/agent/TabSettings.tsx` (только вызов `PresetPicker`)

**Interfaces:**
- Consumes: `readEnabledTools` и `TOOL_INFO` из Tasks 5/7.
- Produces:
  - `PromptPresetRow.settings: Record<string, unknown> | null`
  - `export interface AppliedPromptPreset { body: string; settings: Record<string, unknown> | null }`
  - `PresetPicker({ currentValue, onApply }: { onApply: (preset: AppliedPromptPreset) => void })`

- [ ] **Step 1: Обновить тип пресета**

В `frontend/src/types/index.ts`, в `PromptPresetRow` после `body`:

```ts
  body: string;
  settings: Record<string, unknown> | null;
```

- [ ] **Step 2: Переписать тесты пикера (падающие)**

Заменить содержимое `frontend/src/__tests__/preset-picker.test.tsx` целиком:

```tsx
import { describe, expect, mock, test } from 'bun:test';
import type { ComponentProps } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PresetPickerDialog } from '@/components/agent/PresetPicker';
import type { PromptPresetRow } from '@/types';

const PRESETS: PromptPresetRow[] = [
  {
    id: '11111111-1111-1111-1111-111111111111',
    slug: 'rage_comments',
    title: 'Рейджбейт в комментариях',
    summary: 'спорит под постами',
    body: 'ТЕЛО РЕЙДЖБЕЙТА',
    settings: null,
    sort_order: 1,
    is_active: true,
    created_at: '2026-09-20T00:00:00Z',
    updated_at: '2026-09-20T00:00:00Z',
  },
  {
    id: '22222222-2222-2222-2222-222222222222',
    slug: 'sasavot_fan',
    title: 'Фанат сасыча',
    summary: 'пацанский олд',
    body: 'ТЕЛО ФАНАТА',
    settings: { enabled_tools: ['send_text_message', 'view_image'] },
    sort_order: 2,
    is_active: true,
    created_at: '2026-09-20T00:00:00Z',
    updated_at: '2026-09-20T00:00:00Z',
  },
];

function renderDialog(overrides: Partial<ComponentProps<typeof PresetPickerDialog>> = {}) {
  const onApply = mock((_preset: { body: string; settings: Record<string, unknown> | null }) => {});
  const onClose = mock(() => {});
  render(
    <PresetPickerDialog
      isOpen
      onClose={onClose}
      presets={PRESETS}
      isLoading={false}
      isError={false}
      currentValue=""
      onApply={onApply}
      {...overrides}
    />,
  );
  return { onApply, onClose };
}

describe('PresetPickerDialog', () => {
  test('показывает названия, описания и тело первого пресета', () => {
    renderDialog();
    expect(screen.getByText('Рейджбейт в комментариях')).toBeTruthy();
    expect(screen.getByText('спорит под постами')).toBeTruthy();
    expect(screen.getByText('Фанат сасыча')).toBeTruthy();
    expect(screen.getByTestId('preset-body').textContent).toBe('ТЕЛО РЕЙДЖБЕЙТА');
  });

  test('выбор другого пресета показывает его тело и настройки инструментов', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole('option', { name: /Фанат сасыча/ }));

    expect(screen.getByTestId('preset-body').textContent).toBe('ТЕЛО ФАНАТА');
    expect(screen.getByTestId('preset-tools').textContent).toContain('2 из 91');
  });

  test('пресет без настроек не обещает настройку инструментов', () => {
    renderDialog();
    expect(screen.queryByTestId('preset-tools')).toBeNull();
  });

  test('пустое поле — применение сразу отдаёт текст и настройки наверх', async () => {
    const user = userEvent.setup();
    const { onApply } = renderDialog({ currentValue: '   ' });
    await user.click(screen.getByRole('button', { name: 'Применить пресет' }));
    expect(onApply).toHaveBeenCalledWith({ body: 'ТЕЛО РЕЙДЖБЕЙТА', settings: null });
  });

  test('непустое поле — первый клик только предупреждает, второй применяет', async () => {
    const user = userEvent.setup();
    const { onApply } = renderDialog({ currentValue: 'мой старый характер' });

    await user.click(screen.getByRole('button', { name: 'Применить пресет' }));
    expect(onApply).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toContain('будет заменён');

    await user.click(screen.getByRole('button', { name: 'Всё равно заменить' }));
    expect(onApply).toHaveBeenCalledWith({ body: 'ТЕЛО РЕЙДЖБЕЙТА', settings: null });
  });

  test('предупреждение упоминает настройки инструментов, когда пресет их несёт', async () => {
    const user = userEvent.setup();
    renderDialog({ currentValue: 'мой старый характер' });
    await user.click(screen.getByRole('option', { name: /Фанат сасыча/ }));

    await user.click(screen.getByRole('button', { name: 'Применить пресет' }));
    expect(screen.getByRole('alert').textContent).toContain('настройки инструментов');
  });

  test('смена пресета сбрасывает предупреждение', async () => {
    const user = userEvent.setup();
    const { onApply } = renderDialog({ currentValue: 'мой старый характер' });

    await user.click(screen.getByRole('button', { name: 'Применить пресет' }));
    await user.click(screen.getByRole('option', { name: /Фанат сасыча/ }));
    expect(screen.queryByRole('alert')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Применить пресет' }));
    expect(onApply).not.toHaveBeenCalled();
  });

  test('ошибка загрузки не подменяется пустым списком', () => {
    renderDialog({ presets: [], isError: true });
    expect(screen.getByRole('alert').textContent).toContain('Не удалось загрузить пресеты');
    expect(screen.queryByRole('option')).toBeNull();
  });

  test('пустой справочник говорит об этом прямо', () => {
    renderDialog({ presets: [] });
    expect(screen.getByText('Пресетов пока нет')).toBeTruthy();
  });
});
```

- [ ] **Step 3: Запустить тесты и убедиться, что падают**

Run: `cd frontend && bun test src/__tests__/preset-picker.test.tsx`
Expected: FAIL — `onApply` вызывается со строкой, `preset-tools` не найден.

- [ ] **Step 4: Обновить пикер**

В `frontend/src/components/agent/PresetPicker.tsx`:

1. Новые импорты:

```tsx
import { readEnabledTools } from '@/lib/tools/agentTools';
import { TOOL_INFO } from '@/lib/tools/toolInfo';
```

2. Экспортируемый тип и обновлённые пропсы `PresetPicker`:

```tsx
export interface AppliedPromptPreset {
  body: string;
  settings: Record<string, unknown> | null;
}

export function PresetPicker({
  currentValue,
  onApply,
}: {
  currentValue: string;
  onApply: (preset: AppliedPromptPreset) => void;
}) {
```

3. В `PresetPicker` проброс наружу остаётся один в один: `onApply={(preset) => { onApply(preset); setIsOpen(false); }}`.

4. В `PresetPickerDialog` пропс: `onApply: (preset: AppliedPromptPreset) => void`.

5. После `const willOverwrite = ...` добавить:

```tsx
  const selectedTools = selected ? readEnabledTools(selected.settings) : null;
```

6. В `handleApply` последняя строка:

```tsx
    onApply({ body: selected.body, settings: selected.settings ?? null });
```

7. Правую колонку обернуть, добавив подпись под телом:

```tsx
          <div className="space-y-2">
            <pre
              data-testid="preset-body"
              className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-sm border border-border bg-background/60 p-3 font-mono text-xs text-foreground/90"
            >
              {selected?.body}
            </pre>
            {selectedTools !== null && (
              <p data-testid="preset-tools" className="font-mono text-[11px] text-muted-foreground">
                Настроит инструменты: {selectedTools.length} из {TOOL_INFO.length}
              </p>
            )}
          </div>
```

8. Текст предупреждения:

```tsx
        {confirming && (
          <span role="alert" className="mr-auto font-mono text-xs text-amber-400">
            {selectedTools !== null
              ? 'Текущий характер и настройки инструментов будут заменены'
              : 'Текущий характер будет заменён'}
          </span>
        )}
```

- [ ] **Step 5: Применять настройки пресета в форме**

В `frontend/src/components/agent/TabSettings.tsx` заменить вызов `PresetPicker`:

```tsx
          <PresetPicker
            currentValue={values.soul_prompt}
            onApply={(preset) => {
              const enabled = readEnabledTools(preset.settings);
              setValues((v) => ({
                ...v,
                soul_prompt: preset.body,
                // Пресет без настроек инструментов не трогает текущий выбор.
                enabled_tools: enabled ?? v.enabled_tools,
              }));
              setDirty(true);
            }}
          />
```

- [ ] **Step 6: Прогнать тесты и проверки**

Run: `cd frontend && bun test && bun run typecheck && bunx next lint`
Expected: все зелёные (в том числе обновлённый `preset-picker.test.tsx`), typecheck и lint чистые.

- [ ] **Step 7: Коммит**

```bash
git add frontend/src/types/index.ts frontend/src/components/agent/PresetPicker.tsx frontend/src/__tests__/preset-picker.test.tsx frontend/src/components/agent/TabSettings.tsx
git commit -m "feat(frontend): presets apply tool settings"
```

---

### Task 9: Онбординг-фронтенд: настройки пресета в черновике

**Files:**
- Modify: `frontend/src/types/index.ts:253-263`
- Modify: `frontend/src/hooks/useOnboarding.ts:131-143`
- Modify: `frontend/src/app/(dashboard)/onboarding/page.tsx:237-305`

**Interfaces:**
- Consumes: `readEnabledTools` (Task 7), `AppliedPromptPreset` (Task 8).
- Produces: `useSaveSoulPrompt` принимает `settings?: Record<string, unknown> | null`; `OnboardingSessionRow.settings: Record<string, unknown> | null`.

- [ ] **Step 1: Добавить поле в тип строки черновика**

В `frontend/src/types/index.ts`, в `OnboardingSessionRow` после `soul_prompt`:

```ts
  soul_prompt: string | null;
  settings: Record<string, unknown> | null;
```

- [ ] **Step 2: Научить хук сохранять настройки**

В `frontend/src/hooks/useOnboarding.ts` заменить `useSaveSoulPrompt` целиком:

```ts
/**
 * Step 2: Save soul prompt and the preset's tool settings (if any)
 */
export function useSaveSoulPrompt() {
  const save = useSaveOnboardingStep();
  return {
    ...save,
    mutateAsync: ({
      sessionId,
      values,
      settings,
    }: {
      sessionId: string;
      values: SoulPromptValues;
      settings?: Record<string, unknown> | null;
    }) =>
      save.mutateAsync({
        sessionId,
        update: {
          soul_prompt: values.soul_prompt,
          // Пресет без настроек не трогает уже сохранённый черновик.
          ...(settings ? { settings } : {}),
        },
      }),
  };
}
```

- [ ] **Step 3: Подключить пресет на шаге «Характер»**

В `frontend/src/app/(dashboard)/onboarding/page.tsx`:

1. Импорт рядом с `PresetPicker`:

```tsx
import { readEnabledTools } from '@/lib/tools/agentTools';
```

2. В `StepSoul` добавить состояние рядом с `soulPrompt`:

```tsx
  // Патч настроек, который принёс выбранный пресет; сохраняется вместе с текстом.
  const [presetSettings, setPresetSettings] = useState<Record<string, unknown> | null>(null);
```

3. В `handleSubmit` заменить вызов сохранения:

```tsx
      await save.mutateAsync({
        sessionId: session.id,
        values: { soul_prompt: soulPrompt },
        settings: presetSettings,
      });
```

4. Заменить `PresetPicker`:

```tsx
              <PresetPicker
                currentValue={soulPrompt}
                onApply={(preset) => {
                  setSoulPrompt(preset.body);
                  const enabled = readEnabledTools(preset.settings);
                  if (enabled !== null) setPresetSettings({ enabled_tools: enabled });
                }}
              />
```

- [ ] **Step 4: Проверить сборку и тесты**

Run: `cd frontend && bun test && bun run typecheck && bunx next lint`
Expected: всё чисто.

- [ ] **Step 5: Коммит**

```bash
git add frontend/src/types/index.ts frontend/src/hooks/useOnboarding.ts "frontend/src/app/(dashboard)/onboarding/page.tsx"
git commit -m "feat(onboarding): save preset tool settings in the draft"
```

---

### Task 10: e2e: переключатели и настройки пресета

**Files:**
- Modify: `tests/e2e/test_agent.py` (в конец класса `TestAgentPage`)

**Interfaces:**
- Consumes: `data-testid="tools-settings"`, `data-testid="tool-group-<id>"`, `data-testid="preset-tools"`; сид `rage_comments` из Task 1.
- Produces: ничего.

- [ ] **Step 1: Написать тесты**

В конец класса `TestAgentPage` в `tests/e2e/test_agent.py` (после `test_first_comment_variants_survive_save_and_reload`):

```python
    def test_tool_toggle_survives_save_and_reload(
        self, persona_page: Callable[..., Page], api: httpx.Client, users: dict
    ) -> None:
        agent_id = _new_agent(api, users, "Инструменты")
        page = persona_page("full")
        page.goto(f"/agent/{agent_id}?tab=settings")

        tools = page.get_by_test_id("tools-settings")
        expect(tools).to_be_visible()
        expect(tools.get_by_text(re.compile(r"Включено \d+ из \d+"))).to_be_visible()

        tools.get_by_label("Поиск").fill("Отправка сообщения")
        toggle = tools.get_by_role("switch", name="Отправка сообщения")
        expect(toggle).to_have_attribute("aria-checked", "true")
        toggle.click()

        page.get_by_role("button", name="Сохранить изменения").click()
        expect(page.get_by_test_id("toast-container")).to_contain_text("Настройки сохранены")

        page.reload()
        tools = page.get_by_test_id("tools-settings")
        tools.get_by_label("Поиск").fill("Отправка сообщения")
        expect(tools.get_by_role("switch", name="Отправка сообщения")).to_have_attribute(
            "aria-checked", "false"
        )

    def test_preset_applies_tool_settings(
        self, persona_page: Callable[..., Page], api: httpx.Client, users: dict
    ) -> None:
        agent_id = _new_agent(api, users, "Инструменты пресета")
        page = persona_page("full")
        page.goto(f"/agent/{agent_id}?tab=settings")

        soul = page.get_by_label("SOUL.md — Характер")
        soul.fill("")

        page.get_by_test_id("open-presets").click()
        page.get_by_role("option", name=re.compile("Рейджбейт в комментариях")).click()
        expect(page.get_by_test_id("preset-tools")).to_contain_text("16 из 91")
        page.get_by_role("button", name="Применить пресет").click()

        tools = page.get_by_test_id("tools-settings")
        tools.get_by_label("Поиск").fill("Отправка сообщения")
        expect(tools.get_by_role("switch", name="Отправка сообщения")).to_have_attribute(
            "aria-checked", "true"
        )
        tools.get_by_label("Поиск").fill("Удаление канала")
        expect(tools.get_by_role("switch", name="Удаление канала")).to_have_attribute(
            "aria-checked", "false"
        )

        page.get_by_role("button", name="Сохранить изменения").click()
        expect(page.get_by_test_id("toast-container")).to_contain_text("Настройки сохранены")

        page.reload()
        tools = page.get_by_test_id("tools-settings")
        tools.get_by_label("Поиск").fill("Удаление канала")
        expect(tools.get_by_role("switch", name="Удаление канала")).to_have_attribute(
            "aria-checked", "false"
        )
```

- [ ] **Step 2: Прогнать e2e**

Run: `uv run pytest -m e2e tests/e2e/test_agent.py -k "tool_toggle or preset_applies_tool_settings" -v`
Expected: 2 passed. Прогон поднимает бэкенд на 8000 и фронт на 3000 — порты должны быть свободны; Dev-база очищается фикстурой `auth_states`.

- [ ] **Step 3: Коммит**

```bash
git add tests/e2e/test_agent.py
git commit -m "test(e2e): tool toggles and preset tool settings"
```

---

### Task 11: Финальные проверки и пуш ветки

**Files:**
- Не меняются.

- [ ] **Step 1: Полный набор бэкенда**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -m "not db and not e2e and not real_tg and not real_llm" -W error -q`
Expected: чисто, все тесты зелёные.

- [ ] **Step 2: DB-набор бэкенда**

Run: `uv run pytest -m db -W error -q`
Expected: зелёные (идёт против Dev-базы; замок не требуется — это не real_tg).

- [ ] **Step 3: Полный набор фронтенда**

Run: `cd frontend && bunx next lint && bun run typecheck && bun test`
Expected: чисто, все тесты зелёные.

- [ ] **Step 4: Пуш ветки**

```bash
git push -u origin feat/tool-config
```

PR не открывать: сначала хозяин проверяет приложение локально.

**Проверка вручную после Task 11:**

1. `cd frontend && bun run dev`, бэкенд — `uv run uvicorn mimic42.main:app --reload`.
2. Открыть агента → «Настройки»: секция «Инструменты» со счётчиком «Включено 91 из 91», группы свёрнуты, поиск работает.
3. Выключить пару инструментов, «Сохранить изменения» — тост «Настройки сохранены», после перезагрузки страницы состояние на месте.
4. Применить пресет «Рейджбейт» на пустое поле SOUL.md: под телом написано «Настроит инструменты: 16 из 91», после применения в секции включено 16 инструментов.
5. Сохранить, перезагрузить — allowlist сохранился; запустить агента и убедиться, что он продолжает отвечать в диалогах (обычные ответы не инструменты).
6. Пройти онбординг до шага «Характер», применить «Рейджбейт», продолжить до конца: у созданного агента в «Настройках» включено 16 инструментов.
