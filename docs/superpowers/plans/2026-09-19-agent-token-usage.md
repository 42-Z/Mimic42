# Пожизненный счётчик токенов в «Аналитике» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Показывать в «Аналитике» агента пожизненный счётчик входных и выходных токенов, считая каждый вызов модели.

**Architecture:** Новый middleware `TokenUsageMiddleware` на `awrap_model_call` суммирует `usage_metadata` каждого вызова модели и инкрементит счётчики агента атомарным upsert в отдельной таблице `agent_token_usage` (вне горячей строки `agents`). Фронтенд читает одну строку напрямую из Supabase и рисует карточку, не зависящую от периода.

**Tech Stack:** Python 3.12, LangChain 1.3 (`langchain.agents.middleware`), SQLAlchemy 2 + asyncpg, PostgreSQL/Supabase, pytest, Next.js 14 + React Query + Tailwind, bun test.

**Spec:** `docs/superpowers/specs/2026-09-19-agent-token-usage-design.md`

---

## Карта файлов

| Файл | Действие | Ответственность |
| --- | --- | --- |
| `supabase/migrations/<timestamp>_add_agent_token_usage.sql` | создать (CLI) | таблица + RLS |
| `src/mimic42/integrations/database_models.py` | изменить | ORM-модель `AgentTokenUsageModel` |
| `src/mimic42/core/token_usage.py` | создать | `TokenUsageRecorder` (атомарный инкремент, fail-open) |
| `src/mimic42/integrations/token_usage_middleware.py` | создать | `TokenUsageMiddleware` (сумма usage за вызов модели) |
| `src/mimic42/integrations/langchain_agent.py` | изменить | регистрация middleware |
| `tests/core/test_token_usage.py` | создать | fail-open рекордера (без БД) |
| `tests/integration/test_token_usage.py` | создать | накопление в БД (маркер `db`) |
| `tests/integrations/test_token_usage_middleware.py` | создать | суммирование/пропуски/ошибки middleware |
| `tests/integrations/test_langchain_agent.py` | изменить | состав middleware в `build_langchain_agent` |
| `frontend/src/types/supabase.ts` | изменить | типы таблицы (генерация CLI или вручную) |
| `frontend/src/lib/queryClient.ts` | изменить | ключ `analytics.usage` |
| `frontend/src/hooks/useTelegramSession.ts` | изменить | хук `useTokenUsage` |
| `frontend/src/lib/format.ts` | создать | `formatCompactNumber` |
| `frontend/src/components/agent/TokenUsageCard.tsx` | создать | карточка + чистый `TokenUsageStats` |
| `frontend/src/__tests__/format.test.ts` | создать | тесты форматтера |
| `frontend/src/__tests__/token-usage-card.test.tsx` | создать | тесты презентационного компонента |
| `frontend/src/components/agent/TabAnalytics.tsx` | изменить | рендер карточки над тумблером 7/30 |

Порядок задач: данные → бэкенд → фронтенд → финальная проверка. Первые четыре задачи не зависят от фронтенда.

---

### Task 1: Миграция `agent_token_usage`

**Files:**
- Create: `supabase/migrations/<timestamp>_add_agent_token_usage.sql` (файл создаёт CLI, имя печатает команда)

- [ ] **Step 1: Создать файл миграции CLI**

Run (из корня репозитория):

```bash
supabase migration new add_agent_token_usage
```

Expected: `Created new migration at supabase/migrations/<timestamp>_add_agent_token_usage.sql`

- [ ] **Step 2: Заполнить миграцию**

Записать в созданный файл:

```sql
-- Пожизненные счётчики токенов агента (issue #81). Живут отдельно от строки
-- agents: каждый вызов модели инкрементит их upsert-ом и не трогает
-- agents.updated_at/его триггер.
create table public.agent_token_usage (
    agent_id uuid primary key references public.agents(id) on delete cascade,
    input_tokens bigint not null default 0,
    output_tokens bigint not null default 0,
    updated_at timestamptz not null default now()
);

alter table public.agent_token_usage enable row level security;

create policy "Users can read token usage of their agents"
on public.agent_token_usage
for select
to authenticated
using (
    exists (
        select 1
        from public.agents
        where agents.id = agent_token_usage.agent_id
            and agents.owner_id = auth.uid()
    )
);
```

- [ ] **Step 3: Применить миграцию в Dev**

Run:

```bash
supabase db push
```

Expected: `Applying migration <timestamp>_add_agent_token_usage.sql` без ошибок.
Если CLI не залогинен/проект не связан — попросить хозяина выполнить `supabase login` и `supabase link --project-ref ipqylrdmmjitemjrygej`, затем повторить.

- [ ] **Step 4: Проверить список миграций и advisors**

Run:

```bash
supabase migration list --linked
supabase db advisors
```

Expected: миграция видна и в Local, и в Remote; advisors не находит проблем по новой таблице.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/*_add_agent_token_usage.sql
git commit -m "feat(db): add agent_token_usage table"
```

---

### Task 2: ORM-модель и `TokenUsageRecorder`

**Files:**
- Modify: `src/mimic42/integrations/database_models.py` (импорт `BigInteger`, модель в конце файла)
- Create: `src/mimic42/core/token_usage.py`
- Test: `tests/integration/test_token_usage.py` (маркер `db` ставится автоматически по пути)
- Test: `tests/core/test_token_usage.py`

- [ ] **Step 1: Написать падающий db-тест накопления**

Создать `tests/integration/test_token_usage.py`:

```python
from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.token_usage import TokenUsageRecorder
from mimic42.integrations.database_models import AgentModel, AgentTokenUsageModel
from mimic42.testing.slots import Slot


async def _seed_agent(
    db_session_factory: async_sessionmaker[AsyncSession],
    *,
    agent_id: UUID,
    owner_id: UUID,
) -> None:
    async with db_session_factory() as session:
        session.add(
            AgentModel(
                id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                soul_prompt="soul",
            )
        )
        await session.commit()


async def test_token_usage_recorder_accumulates_per_agent(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()
    await _seed_agent(db_session_factory, agent_id=agent_id, owner_id=owner_id)

    recorder = TokenUsageRecorder(db_session_factory)
    await recorder.add(agent_id=agent_id, input_tokens=100, output_tokens=20)
    await recorder.add(agent_id=agent_id, input_tokens=50, output_tokens=10)

    async with db_session_factory() as session:
        row = await session.get(AgentTokenUsageModel, agent_id)

    assert row is not None
    assert row.input_tokens == 150
    assert row.output_tokens == 30
```

- [ ] **Step 2: Убедиться, что тест падает**

Run:

```bash
uv run pytest tests/integration/test_token_usage.py -m db -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'mimic42.core.token_usage'`.

- [ ] **Step 3: Написать падающий тест fail-open**

Создать `tests/core/test_token_usage.py`:

```python
from __future__ import annotations

from typing import Any
from uuid import uuid4

from mimic42.core.token_usage import TokenUsageRecorder


async def test_token_usage_recorder_swallows_write_failure() -> None:
    class BrokenFactory:
        def __call__(self) -> Any:
            raise RuntimeError("db down")

    recorder = TokenUsageRecorder(BrokenFactory())  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    await recorder.add(agent_id=uuid4(), input_tokens=10, output_tokens=5)
```

- [ ] **Step 4: Убедиться, что тест падает**

Run:

```bash
uv run pytest tests/core/test_token_usage.py -v
```

Expected: FAIL — тот же `ModuleNotFoundError`.

- [ ] **Step 5: Добавить ORM-модель**

В `src/mimic42/integrations/database_models.py` расширить импорт SQLAlchemy:

```python
from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
```

В конец файла (после `AgentTimerModel`) добавить:

```python
class AgentTokenUsageModel(Base):
    __tablename__ = "agent_token_usage"

    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [ ] **Step 6: Написать `TokenUsageRecorder`**

Создать `src/mimic42/core/token_usage.py`:

```python
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import func

from mimic42.integrations.database_models import AgentTokenUsageModel

logger = logging.getLogger("mimic42.token_usage")


class TokenUsageRecorder:
    """Adds model token usage to the lifetime per-agent counters.

    The recorder must never break an agent turn: every write runs in its own
    session and every failure is downgraded to a warning.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, *, agent_id: UUID, input_tokens: int, output_tokens: int) -> None:
        try:
            stmt = pg_insert(AgentTokenUsageModel).values(
                agent_id=agent_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[AgentTokenUsageModel.agent_id],
                set_={
                    "input_tokens": AgentTokenUsageModel.input_tokens
                    + stmt.excluded.input_tokens,
                    "output_tokens": AgentTokenUsageModel.output_tokens
                    + stmt.excluded.output_tokens,
                    "updated_at": func.now(),
                },
            )
            async with self._session_factory() as db_session:
                await db_session.execute(stmt)
                await db_session.commit()
        except Exception:
            logger.warning(
                "Failed to record token usage for agent %s",
                agent_id,
                exc_info=True,
            )
```

`updated_at` задаётся в `set_` вручную: `ON CONFLICT DO UPDATE` не применяет Python-side
`onupdate` (документация SQLAlchemy — PostgreSQL, INSERT…ON CONFLICT).

- [ ] **Step 7: Убедиться, что тесты проходят**

Run:

```bash
uv run pytest tests/core/test_token_usage.py -v
uv run pytest tests/integration/test_token_usage.py -m db -v
```

Expected: PASS оба. Db-тест требует выполненного Task 1 и `.env` с Dev-DSN.

- [ ] **Step 8: Проверка линтерами и типами**

Run:

```bash
uv run ruff check src/mimic42/core/token_usage.py src/mimic42/integrations/database_models.py tests/core/test_token_usage.py tests/integration/test_token_usage.py
uv run ty check
```

Expected: без замечаний.

- [ ] **Step 9: Commit**

```bash
git add src/mimic42/core/token_usage.py src/mimic42/integrations/database_models.py tests/core/test_token_usage.py tests/integration/test_token_usage.py
git commit -m "feat(core): token usage recorder with atomic upsert"
```

---

### Task 3: `TokenUsageMiddleware`

**Files:**
- Create: `src/mimic42/integrations/token_usage_middleware.py`
- Test: `tests/integrations/test_token_usage_middleware.py`

- [ ] **Step 1: Написать падающие тесты middleware**

Создать `tests/integrations/test_token_usage_middleware.py`:

```python
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from langchain.agents.middleware import ModelResponse
from langchain_core.messages import AIMessage

from mimic42.integrations.token_usage_middleware import TokenUsageMiddleware


class FakeRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def add(self, *, agent_id: Any, input_tokens: int, output_tokens: int) -> None:
        self.calls.append(
            {"agent_id": agent_id, "input_tokens": input_tokens, "output_tokens": output_tokens}
        )


def _ai_message(input_tokens: int, output_tokens: int) -> AIMessage:
    return AIMessage(
        content="ok",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )


async def test_middleware_sums_usage_across_messages() -> None:
    agent_id = uuid4()
    recorder = FakeRecorder()
    middleware = TokenUsageMiddleware(agent_id=agent_id, recorder=recorder)

    async def handler(request: Any) -> ModelResponse:
        return ModelResponse(result=[_ai_message(10, 2), _ai_message(5, 3)])

    await middleware.awrap_model_call(object(), handler)

    assert recorder.calls == [{"agent_id": agent_id, "input_tokens": 15, "output_tokens": 5}]


async def test_middleware_accepts_bare_ai_message() -> None:
    agent_id = uuid4()
    recorder = FakeRecorder()
    middleware = TokenUsageMiddleware(agent_id=agent_id, recorder=recorder)

    async def handler(request: Any) -> AIMessage:
        return _ai_message(7, 1)

    await middleware.awrap_model_call(object(), handler)

    assert recorder.calls == [{"agent_id": agent_id, "input_tokens": 7, "output_tokens": 1}]


async def test_middleware_skips_when_usage_metadata_absent() -> None:
    recorder = FakeRecorder()
    middleware = TokenUsageMiddleware(agent_id=uuid4(), recorder=recorder)

    async def handler(request: Any) -> ModelResponse:
        return ModelResponse(result=[AIMessage(content="ok")])

    await middleware.awrap_model_call(object(), handler)

    assert recorder.calls == []


async def test_middleware_does_not_record_model_failure() -> None:
    recorder = FakeRecorder()
    middleware = TokenUsageMiddleware(agent_id=uuid4(), recorder=recorder)

    async def failing_handler(request: Any) -> Any:
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        await middleware.awrap_model_call(object(), failing_handler)

    assert recorder.calls == []


async def test_middleware_survives_recorder_failure() -> None:
    from mimic42.core.token_usage import TokenUsageRecorder

    class BrokenFactory:
        def __call__(self) -> Any:
            raise RuntimeError("db down")

    middleware = TokenUsageMiddleware(
        agent_id=uuid4(),
        recorder=TokenUsageRecorder(BrokenFactory()),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    )

    async def handler(request: Any) -> ModelResponse:
        return ModelResponse(result=[_ai_message(3, 1)])

    response = await middleware.awrap_model_call(object(), handler)
    assert response.result[0].usage_metadata["input_tokens"] == 3
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run:

```bash
uv run pytest tests/integrations/test_token_usage_middleware.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'mimic42.integrations.token_usage_middleware'`.

- [ ] **Step 3: Написать middleware**

Создать `src/mimic42/integrations/token_usage_middleware.py`:

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware

from mimic42.core.token_usage import TokenUsageRecorder

ModelCallHandler = Callable[[Any], Awaitable[Any]]


def _usage_totals(response: Any) -> tuple[int, int]:
    """Sum input/output tokens over every message of one model call.

    Handles both shapes an ``awrap_model_call`` handler may return: a
    ``ModelResponse`` (``result`` is a list) and a bare ``AIMessage``.
    """
    result = getattr(response, "result", None)
    messages = result if isinstance(result, list) else [response]
    input_tokens = 0
    output_tokens = 0
    for message in messages:
        usage = getattr(message, "usage_metadata", None)
        if not isinstance(usage, dict):
            continue
        input_tokens += int(usage.get("input_tokens") or 0)
        output_tokens += int(usage.get("output_tokens") or 0)
    return input_tokens, output_tokens


class TokenUsageMiddleware(AgentMiddleware):
    """Adds the token usage of every model call to the agent's lifetime counter."""

    def __init__(self, *, agent_id: Any, recorder: TokenUsageRecorder) -> None:
        self._agent_id = agent_id
        self._recorder = recorder

    async def awrap_model_call(self, request: Any, handler: ModelCallHandler) -> Any:
        response = await handler(request)
        input_tokens, output_tokens = _usage_totals(response)
        if input_tokens or output_tokens:
            await self._recorder.add(
                agent_id=self._agent_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        return response
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run:

```bash
uv run pytest tests/integrations/test_token_usage_middleware.py -v
```

Expected: PASS все пять.

- [ ] **Step 5: Commit**

```bash
git add src/mimic42/integrations/token_usage_middleware.py tests/integrations/test_token_usage_middleware.py
git commit -m "feat(integrations): token usage middleware"
```

---

### Task 4: Регистрация middleware в `build_langchain_agent`

**Files:**
- Modify: `src/mimic42/integrations/langchain_agent.py`
- Test: `tests/integrations/test_langchain_agent.py`

- [ ] **Step 1: Написать падающие тесты состава middleware**

В конец `tests/integrations/test_langchain_agent.py` добавить:

```python
def test_build_langchain_agent_registers_token_usage_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "graph"

    monkeypatch.setattr(langchain_agent_module, "create_agent", fake_create_agent)

    build_langchain_agent(
        _config("mistral-small"),
        session_factory=object(),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    )

    middleware = captured["middleware"]
    assert any(isinstance(m, TokenUsageMiddleware) for m in middleware)


def test_build_langchain_agent_has_no_middleware_without_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "graph"

    monkeypatch.setattr(langchain_agent_module, "create_agent", fake_create_agent)

    build_langchain_agent(_config("mistral-small"))

    assert captured["middleware"] == []
```

Обновить импорты в шапке теста:

```python
from mimic42.integrations.langchain_agent import build_chat_model, build_langchain_agent
from mimic42.integrations.token_usage_middleware import TokenUsageMiddleware
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run:

```bash
uv run pytest tests/integrations/test_langchain_agent.py -v
```

Expected: FAIL — `ImportError: cannot import name 'build_langchain_agent'` (нет в существующем импорте) и/или `TokenUsageMiddleware` отсутствует в списке.

- [ ] **Step 3: Зарегистрировать middleware**

В `src/mimic42/integrations/langchain_agent.py` добавить импорты:

```python
from mimic42.core.token_usage import TokenUsageRecorder
from mimic42.integrations.token_usage_middleware import TokenUsageMiddleware
```

Заменить блок сбора middleware в `build_langchain_agent`:

```python
    middleware: list[Any] = []
    if session_factory is not None:
        recorder = ActivityRecorder(session_factory)
        middleware.append(ActivityMiddleware(agent_id=config.agent_id, recorder=recorder))
        middleware.append(
            TokenUsageMiddleware(
                agent_id=config.agent_id,
                recorder=TokenUsageRecorder(session_factory),
            )
        )
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run:

```bash
uv run pytest tests/integrations/test_langchain_agent.py -v
```

Expected: PASS все семь.

- [ ] **Step 5: Полная проверка бэкенда**

Run:

```bash
uv run ruff check
uv run ty check
uv run pytest -m "not db"
```

Expected: без замечаний, все не-db тесты зелёные.

- [ ] **Step 6: Commit**

```bash
git add src/mimic42/integrations/langchain_agent.py tests/integrations/test_langchain_agent.py
git commit -m "feat(integrations): register token usage middleware"
```

---

### Task 5: Типы Supabase, ключ запроса и хук `useTokenUsage`

**Files:**
- Modify: `frontend/src/types/supabase.ts` (после блока `agent_onboarding_sessions`, перед `agents:`)
- Modify: `frontend/src/lib/queryClient.ts`
- Modify: `frontend/src/hooks/useTelegramSession.ts`

- [ ] **Step 1: Обновить типы генератором**

Run (из `frontend/`, миграция уже применена в Dev на Task 1):

```bash
bun run generate:types
```

Expected: команда завершается без ошибок, в `src/types/supabase.ts` появляется `agent_token_usage`.
Проверка:

```bash
grep -n "agent_token_usage" src/types/supabase.ts
```

Если CLI не залогинен — вставить блок вручную в `frontend/src/types/supabase.ts` (алфавитное место: после закрывающей `},` блока `agent_onboarding_sessions`, перед `agents: {`):

```ts
      agent_token_usage: {
        Row: {
          agent_id: string
          input_tokens: number
          output_tokens: number
          updated_at: string
        }
        Insert: {
          agent_id: string
          input_tokens?: number
          output_tokens?: number
          updated_at?: string
        }
        Update: {
          agent_id?: string
          input_tokens?: number
          output_tokens?: number
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "agent_token_usage_agent_id_fkey"
            columns: ["agent_id"]
            isOneToOne: true
            referencedRelation: "agents"
            referencedColumns: ["id"]
          },
        ]
      }
```

- [ ] **Step 2: Добавить ключ запроса**

В `frontend/src/lib/queryClient.ts`, в секции `analytics`, после `kpisAll`:

```ts
    usage: (agentId: string) => [...queryKeys.analytics.all, agentId, 'usage'] as const,
```

- [ ] **Step 3: Добавить хук**

В конец `frontend/src/hooks/useTelegramSession.ts` (секция аналитики, рядом с `useAnalyticsData`):

```ts
/**
 * Fetch the agent's lifetime token counters from Supabase.
 * Counters always accumulate; the hook is independent of the day range.
 */
export function useTokenUsage(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: queryKeys.analytics.usage(agentId),
    queryFn: async () => {
      const supabase = getSupabaseClient();
      const { data, error } = await supabase
        .from('agent_token_usage')
        .select('input_tokens, output_tokens')
        .eq('agent_id', agentId)
        .maybeSingle();

      if (error) throw error;
      return {
        input_tokens: data?.input_tokens ?? 0,
        output_tokens: data?.output_tokens ?? 0,
      };
    },
    enabled: isValidId,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}
```

- [ ] **Step 4: Проверить типы**

Run (из `frontend/`):

```bash
bun run typecheck
```

Expected: без ошибок. Если `agent_token_usage` не появился в `Database`, TypeScript укажет `from('agent_token_usage')` как неизвестную таблицу — значит Step 1 не выполнен.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/supabase.ts frontend/src/lib/queryClient.ts frontend/src/hooks/useTelegramSession.ts
git commit -m "feat(frontend): lifetime token usage query hook"
```

---

### Task 6: Форматтер, карточка и рендер в «Аналитике»

**Files:**
- Create: `frontend/src/lib/format.ts`
- Test: `frontend/src/__tests__/format.test.ts`
- Create: `frontend/src/components/agent/TokenUsageCard.tsx`
- Test: `frontend/src/__tests__/token-usage-card.test.tsx`
- Modify: `frontend/src/components/agent/TabAnalytics.tsx`

- [ ] **Step 1: Написать падающий тест форматтера**

Создать `frontend/src/__tests__/format.test.ts`:

```ts
import { describe, it, expect } from 'bun:test';
import { formatCompactNumber } from '@/lib/format';

describe('formatCompactNumber', () => {
  it('маленькие числа не сокращает', () => {
    expect(formatCompactNumber(0)).toBe('0');
    expect(formatCompactNumber(999)).toBe('999');
  });

  it('тысячи — с одной десятой до 100 тыс', () => {
    expect(formatCompactNumber(1_234)).toBe('1,2 тыс');
    expect(formatCompactNumber(12_345)).toBe('12,3 тыс');
    expect(formatCompactNumber(123_456)).toBe('123 тыс');
  });

  it('миллионы — с одной десятой', () => {
    expect(formatCompactNumber(1_234_567)).toBe('1,2 млн');
    expect(formatCompactNumber(12_345_678)).toBe('12,3 млн');
  });

  it('некорректные и отрицательные значения — ноль', () => {
    expect(formatCompactNumber(-5)).toBe('0');
    expect(formatCompactNumber(Number.NaN)).toBe('0');
  });
});
```

- [ ] **Step 2: Убедиться, что тест падает**

Run (из `frontend/`):

```bash
bun test src/__tests__/format.test.ts
```

Expected: FAIL — `Cannot find module '@/lib/format'`.

- [ ] **Step 3: Написать форматтер**

Создать `frontend/src/lib/format.ts`:

```ts
/**
 * Компактная запись крупных счётчиков: 12 300 → «12,3 тыс»,
 * 1 200 000 → «1,2 млн». Малые значения округляются до целого,
 * некорректный ввод схлопывается в ноль.
 */
export function formatCompactNumber(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return '0';
  }
  if (value < 1_000) {
    return Math.round(value).toString();
  }
  const thousands = value / 1_000;
  if (thousands < 1_000) {
    const rounded = thousands < 100 ? thousands.toFixed(1) : thousands.toFixed(0);
    if (Number(rounded) < 1_000) {
      return `${rounded.replace('.', ',')} тыс`;
    }
  }
  return `${(value / 1_000_000).toFixed(1).replace('.', ',')} млн`;
}
```

- [ ] **Step 4: Убедиться, что тест проходит**

Run (из `frontend/`):

```bash
bun test src/__tests__/format.test.ts
```

Expected: PASS.

- [ ] **Step 5: Написать падающий тест карточки**

Создать `frontend/src/__tests__/token-usage-card.test.tsx`:

```tsx
import { describe, expect, test } from 'bun:test';
import { render, screen } from '@testing-library/react';
import { TokenUsageStats } from '@/components/agent/TokenUsageCard';

describe('TokenUsageStats', () => {
  test('показывает входные, выходные и сумму', () => {
    render(<TokenUsageStats inputTokens={12_300} outputTokens={4_500} isLoading={false} />);
    expect(screen.getByText('12,3 тыс')).toBeTruthy();
    expect(screen.getByText('4,5 тыс')).toBeTruthy();
    expect(screen.getByText('16,8 тыс')).toBeTruthy();
    expect(screen.getByText('Входные')).toBeTruthy();
    expect(screen.getByText('Выходные')).toBeTruthy();
    expect(screen.getByText('Всего')).toBeTruthy();
  });

  test('нули показываются как нули', () => {
    render(<TokenUsageStats inputTokens={0} outputTokens={0} isLoading={false} />);
    expect(screen.getAllByText('0')).toHaveLength(3);
  });

  test('пока идёт загрузка — вместо чисел скелетон', () => {
    render(<TokenUsageStats inputTokens={0} outputTokens={0} isLoading />);
    expect(screen.queryByText('Всего')).toBeNull();
  });
});
```

- [ ] **Step 6: Убедиться, что тест падает**

Run (из `frontend/`):

```bash
bun test src/__tests__/token-usage-card.test.tsx
```

Expected: FAIL — `Cannot find module '@/components/agent/TokenUsageCard'`.

- [ ] **Step 7: Написать карточку**

Создать `frontend/src/components/agent/TokenUsageCard.tsx`:

```tsx
'use client';

import { useTokenUsage } from '@/hooks/useTelegramSession';
import { Card, Skeleton } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { formatCompactNumber } from '@/lib/format';

export function TokenUsageCard({ agentId }: { agentId: string }) {
  const { data, isLoading } = useTokenUsage(agentId);

  return (
    <Card variant="glass" padding="md" data-testid="token-usage-card">
      <h3 className="font-mono text-xs text-void-400 uppercase tracking-wider mb-4">
        Токены за всё время
      </h3>
      <TokenUsageStats
        inputTokens={data?.input_tokens ?? 0}
        outputTokens={data?.output_tokens ?? 0}
        isLoading={isLoading}
      />
    </Card>
  );
}

export function TokenUsageStats({
  inputTokens,
  outputTokens,
  isLoading,
}: {
  inputTokens: number;
  outputTokens: number;
  isLoading: boolean;
}) {
  if (isLoading) {
    return <Skeleton className="h-10 w-64" />;
  }

  return (
    <div className="flex flex-wrap gap-x-10 gap-y-4">
      <TokenStat label="Входные" value={inputTokens} className="text-plasma-400" />
      <TokenStat label="Выходные" value={outputTokens} className="text-neon-400" />
      <TokenStat label="Всего" value={inputTokens + outputTokens} className="text-void-200" />
    </div>
  );
}

function TokenStat({
  label,
  value,
  className,
}: {
  label: string;
  value: number;
  className: string;
}) {
  return (
    <div title={value.toLocaleString('ru-RU')}>
      <div className={cn('font-mono text-2xl', className)}>{formatCompactNumber(value)}</div>
      <div className="font-mono text-[10px] uppercase tracking-wider text-void-500 mt-1">
        {label}
      </div>
    </div>
  );
}
```

- [ ] **Step 8: Убедиться, что тест проходит**

Run (из `frontend/`):

```bash
bun test src/__tests__/token-usage-card.test.tsx
```

Expected: PASS.

- [ ] **Step 9: Встроить карточку в `TabAnalytics`**

В `frontend/src/components/agent/TabAnalytics.tsx` добавить импорт:

```tsx
import { TokenUsageCard } from '@/components/agent/TokenUsageCard';
```

В возвращаемом JSX сделать карточку первым элементом (выше тумблера 7/30):

```tsx
  return (
    <div className="space-y-6">
      <TokenUsageCard agentId={agentId} />

      <div className="flex items-center gap-2">
        {([7, 30] as const).map((d) => (
```

Остальное тело не меняется.

- [ ] **Step 10: Полная проверка фронтенда**

Run (из `frontend/`):

```bash
bun run lint
bun run typecheck
bun test
```

Expected: без ошибок, все тесты зелёные.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/lib/format.ts frontend/src/__tests__/format.test.ts frontend/src/components/agent/TokenUsageCard.tsx frontend/src/__tests__/token-usage-card.test.tsx frontend/src/components/agent/TabAnalytics.tsx
git commit -m "feat(frontend): lifetime token counter in analytics"
```

---

### Task 7: Финальная проверка и PR

**Files:** нет изменений кода — только проверки и PR.

- [ ] **Step 1: Полный прогон бэкенда**

Run:

```bash
uv run ruff check
uv run ty check
uv run pytest
```

Expected: зелёные. Db-тесты (включая `tests/integration/test_token_usage.py`) запускаются явно:
`uv run pytest -m db` — требуют Dev-DSN и применённой миграции.

- [ ] **Step 2: Полный прогон фронтенда**

Run (из `frontend/`):

```bash
bun run lint
bun run typecheck
bun test
```

Expected: зелёные.

- [ ] **Step 3: Ручная проверка на живом агенте (Dev)**

1. Запустить бэкенд и фронтенд, открыть агента → «Аналитика».
2. До сообщений карточка показывает нули.
3. Отправить агенту сообщение в Telegram (или триггер из дашборда), дождаться ответа.
4. Обновить страницу: входные/выходные токены выросли, «Всего» равно их сумме.
5. Отправить второе сообщение — значения снова выросли (накопление, не перезапись).

- [ ] **Step 4: Push и PR**

```bash
git push -u origin feat/issue-81-token-counter
gh pr create \
  --title "feat: lifetime token usage counter in analytics (issue #81)" \
  --body "Реализует #81.

- middleware awrap_model_call суммирует usage_metadata каждого вызова модели;
- пожизненные счётчики в agent_token_usage (атомарный upsert, RLS на чтение владельцу);
- карточка «Токены за всё время» в «Аналитике» агента.

Спека: docs/superpowers/specs/2026-09-19-agent-token-usage-design.md
План: docs/superpowers/plans/2026-09-19-agent-token-usage.md" \
  --base main
```

Expected: PR создан, ссылка в выводе `gh`.

---

## Заметки для исполнителя

- Никогда не коммитить `.env`/секреты; DSN и ключи не печатать в выводе.
- Db-тесты используют Dev-проект и слоты; прод-проект трогать нельзя (`assert_test_project`
  в `conftest.py`).
- Если `supabase db push`/`generate:types` требуют логина — остановиться и попросить
  хозяина выполнить `supabase login` и `supabase link --project-ref ipqylrdmmjitemjrygej`.
- При расхождении сгенерированных типов с ручным блоком из Task 5 — верить генератору.
- `usage_metadata` может отсутствовать у сообщения — это норма, вклад 0 (OpenRouter в
  non-streaming возвращает usage всегда).
