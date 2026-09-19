# Дизайн: пожизненный счётчик токенов в «Аналитике» агента

Issue: https://github.com/42-Z/Mimic42/issues/81
Дата: 2026-09-19

## Цель

Показывать на вкладке «Аналитика» агента пожизненный счётчик потраченных токенов:
раздельно входные и выходные. Считать каждый вызов модели, включая промежуточные
вызовы tool-loop и structured output — это фактическое биллинг-потребление агента.
Счётчик не зависит от выбранного периода (7/30 дней) и не сбрасывается.

## Контекст (по коду и документации)

- Аналитика сейчас читает Supabase напрямую: `useAnalyticsData` тянет `agent_messages`
  и `agent_events`, `TabAnalytics` рисует графики по дням. Токенов нет нигде.
- Каждый вызов модели проходит через middleware-хук `awrap_model_call`
  (`ActivityMiddleware`), который уже оборачивает модельные вызовы
  (`src/mimic42/integrations/activity_middleware.py`).
- `ModelResponse.result` — список `BaseMessage`; у `AIMessage` есть `usage_metadata`
  с `input_tokens` / `output_tokens` / `total_tokens`
  (https://reference.langchain.com/python/langchain/agents/middleware/types/ModelResponse).
- `ChatOpenRouter` заполняет `usage_metadata`; OpenRouter в non-streaming ответах
  (у нас `ainvoke`) возвращает usage всегда, включая срабатывание fallback-модели
  (https://docs.langchain.com/oss/python/integrations/chat/openrouter,
  https://openrouter.ai/docs/cookbook/administration/usage-accounting).
- Память не восстанавливает `usage_metadata` при загрузке истории
  (`database_memory.py` собирает сообщения из `type`/`content`/`tool_calls`), поэтому
  двойного счёта из контекста не будет.
- Трекинг usage — задокументированный кейс `wrap_model_call`
  (https://docs.langchain.com/oss/python/langchain/middleware/custom).

## Решение

### 1. Схема данных

Новая таблица `public.agent_token_usage`:

| колонка | тип | примечание |
| --- | --- | --- |
| `agent_id` | uuid PK | `references agents(id) on delete cascade` |
| `input_tokens` | bigint not null default 0 | |
| `output_tokens` | bigint not null default 0 | |
| `updated_at` | timestamptz not null default now() | диагностика; обновляется вручную в upsert |

- RLS включён. Политика `select` для `authenticated`: владелец агента
  (`exists (select 1 from agents where agents.id = agent_token_usage.agent_id
  and agents.owner_id = auth.uid())`). Политик на запись нет — пишет только бэкенд
  под service role.
- Миграция создаётся через `supabase migration new add_agent_token_usage`
  (скилл Supabase), затем `supabase db advisors` и `supabase db push` в Dev.
- SQLAlchemy-модель `AgentTokenUsageModel` в
  `src/mimic42/integrations/database_models.py`.
- Бэкфилла нет: у существующих агентов отсчёт начинается с 0, исторических
  usage-данных не существует.
- После применения миграции типы фронтенда обновляются `bun run generate:types`
  (генерируются из Dev-проекта).

### 2. Захват токенов (бэкенд)

- Новый `src/mimic42/core/token_usage.py`: `TokenUsageRecorder(session_factory)` с
  методом `add(agent_id, input_tokens, output_tokens)`. Внутри — атомарный upsert:

  ```python
  stmt = pg_insert(AgentTokenUsageModel).values(...)
  stmt = stmt.on_conflict_do_update(
      index_elements=[AgentTokenUsageModel.agent_id],
      set_={
          "input_tokens": AgentTokenUsageModel.input_tokens + stmt.excluded.input_tokens,
          "output_tokens": AgentTokenUsageModel.output_tokens + stmt.excluded.output_tokens,
          "updated_at": func.now(),
      },
  )
  ```

  `updated_at` задаётся в `set_` вручную: `ON CONFLICT DO UPDATE` не применяет
  Python-side `onupdate` (документация SQLAlchemy, PostgreSQL — INSERT…ON CONFLICT).
  Каждый вызов — своя сессия, ошибки глотаются в warning (как в `ActivityRecorder`):
  учёт не должен ронять turn.
- Новый `src/mimic42/integrations/token_usage_middleware.py`:
  `TokenUsageMiddleware(agent_id, recorder)` с `awrap_model_call`. После успешного
  `handler(request)` суммирует `input_tokens` и `output_tokens` по всем элементам
  `response.result` (поддерживается и ответ-`AIMessage`, и `ModelResponse`).
  Запись выполняется только если сумма > 0; отсутствие `usage_metadata` у сообщения
  не мешает остальным.
- `build_langchain_agent` (`langchain_agent.py`) добавляет
  `TokenUsageMiddleware` в список middleware рядом с `ActivityMiddleware` — при
  наличии `session_factory`. `ActivityMiddleware` не меняется, его тест на
  «тихий успех» остаётся валидным.
- Каждый вызов модели = отдельный инкремент: промежуточные tool-loop и вызовы
  structured output считаются. Если провайдер не вернул usage — вклад 0.
- Ошибка самого вызова модели: `handler` бросает исключение — middleware ничего не
  пишет (сгоревшие запросы не тарифицируются).

### 3. Чтение и UI

- Новый хук `useTokenUsage(agentId)` в `frontend/src/hooks/useTelegramSession.ts`:
  `select input_tokens, output_tokens from agent_token_usage where agent_id = ...`
  (`.maybeSingle()`), `staleTime: 60_000`, `refetchInterval: 60_000`.
  Ключ — `queryKeys.analytics.usage(agentId)` в `frontend/src/lib/queryClient.ts`.
- В `TabAnalytics` — карточка «Токены за всё время» выше тумблера 7/30:
  два числа (входные/выходные) и итог. Карточка не зависит от 7/30. Пока данные
  грузятся — `Skeleton`; если строки нет — нули.
- Компактный формат чисел (`12,3 тыс`, `1,2 млн`) — чистая функция с тестом.
  Оформление: существующий `Card variant="glass"`, mono-шрифт; входные — цвет
  `plasma`, выходные — `neon` (как «Сообщения»/«Действия» в графиках).
- Ссылок на карточку с дашборда нет: счётчик показывается только в «Аналитике».

### 4. Ошибки и краевые случаи

- Провайдер не вернул usage — вклад 0, запись пропускается.
- Сбой записи в БД — warning, turn продолжается (fail-open).
- Агент удалён между вызовом и записью — FK-каскад/ошибка записи → warning.
- Счётчики не сбрасываются при рестарте/перезапуске агента — живут в БД.
- `bigint` исключает переполнение на любой реалистичной истории.

## Проверка

- Backend-тесты:
  - middleware: суммирует usage по нескольким сообщениям; пропускает вызов без
    `usage_metadata`; не пишет при нулевой сумме; сбой рекордера не роняет turn;
    ошибка вызова модели не пишет ничего;
  - recorder: повторные `add` складывают значения (интеграционный тест на БД,
    маркер `db`; требует применённой в Dev миграции);
  - `build_langchain_agent` кладёт middleware в список при `session_factory`.
- Frontend: `bun test` — форматтер чисел; при наличии паттерна компонентных тестов —
  рендер карточки с нулями/значениями.
- Команды: `uv run ruff check`, `uv run ty check`, `uv run pytest`,
  `cd frontend && bun run lint && bun run typecheck && bun test`.
- Ручная проверка: запустить агента в Dev, отправить сообщение, убедиться, что
  счётчик в «Аналитике» вырос.

## Вне скоупа

- Денежная стоимость (`cost` из OpenRouter), график токенов по дням, счётчики на
  дашборде, разбивка по моделям, backfill истории, сброс счётчика, realtime-обновление
  счётчика (хватает периодического refetch).
