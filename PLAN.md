# Несколько агентов у одного пользователя

## Контекст

Сейчас пользователь может завести ровно одного агента, хотя вся модель данных и рантайм на это не рассчитаны — они уже мультиагентные:

- `agents.owner_id` — обычный FK с индексом, не UNIQUE; RLS-политики на всех таблицах уже проверяют владение через `agents.owner_id`.
- `AgentManager._agents: dict[UUID, MimicAgentRuntime]` (`src/mimic42/core/manager.py:57`) — реестр по `agent_id`, `list_agents(owner_id=...)` фильтрует по владельцу, восстановление на старте (`src/mimic42/api/app.py:194-217`) поднимает всех агентов со статусом `running`.
- Telethon-сессии хранятся как зашифрованный `StringSession` в `telegram_sessions` (`integrations/telethon_client.py:12-17`), Mem0 уже неймспейсится по `agent_id` (`integrations/mem0_memory.py`), `soul_prompt` и `settings` — per-agent.
- Сайдбар (`frontend/src/components/layout/Sidebar.tsx:116-148`) уже рисует список всех агентов со статусными точками.

Единственное, что действительно ограничивает — путь создания агента:

1. **`agent_onboarding_sessions.owner_id uuid not null unique`** (`supabase/migrations/20260519224500_agent_base.sql:72`) — физически одна строка онбординга на пользователя.
2. `AgentOnboardingService.request_telegram_code` (`src/mimic42/core/onboarding.py:187-195`) при повторном вызове находит строку через `get_by_owner` и **переиспользует её `onboarding_id`**. Так как `agent_id == onboarding_id`, второй онбординг перезаписывает первого агента.
3. Фронтенд делает `upsert(..., { onConflict: 'owner_id' })` (`frontend/src/hooks/useOnboarding.ts:80-87`), а страница онбординга при `completed_agent_id != null` показывает экран «Агент создан» (`frontend/src/app/(dashboard)/onboarding/page.tsx:69`) — второй заход невозможен.
4. Нет удаления агента: ни `DELETE /api/v1/agents/{id}`, ни метода снятия рантайма с реестра.
5. Дашборд работает с `agents[0]` (`frontend/src/app/(dashboard)/dashboard/page.tsx:30,37`).

Цель: пользователь заводит сколько угодно агентов через тот же мастер онбординга, а главная страница показывает сводку и управление сразу по всем его агентам, включая удаление.

## Решения

- `agent_id` остаётся равным `onboarding_id`. Каждый запуск мастера создаёт **новую** строку онбординга, поэтому идентификаторы больше не конфликтуют, и `completed_agent_id UNIQUE` остаётся корректным (одна сессия ↔ один агент).
- Отдельной страницы `/agents` нет — весь список и управление живут на `/dashboard`.
- Существующие строки онбординга не трогаем: миграция только снимает ограничение.

---

## 1. Миграция БД

Новый файл `supabase/migrations/<timestamp>_multi_agent_per_user.sql`:

```sql
-- Пользователь может проходить онбординг многократно: одна сессия = один агент
alter table public.agent_onboarding_sessions
    drop constraint if exists agent_onboarding_sessions_owner_id_key;

-- Статусы агентов должны приезжать в дашборд по realtime
alter publication supabase_realtime add table public.agents;
```

Замечания:

- Имя ограничения проверено в подключённом проекте (`ajcznltdbwvhmhgzufzv`): `agent_onboarding_sessions_owner_id_key`. Рядом есть `agent_onboarding_sessions_completed_agent_id_key` — его оставляем, связь «одна сессия ↔ один агент» остаётся в силе.
- Отдельный индекс `agent_onboarding_sessions_owner_id_idx` уже существует (`agent_base.sql:147`), поэтому после снятия unique-индекса поиск по `owner_id` не деградирует — добавлять ничего не нужно.
- `agents` не входит в публикацию `supabase_realtime` — проверено запросом к `pg_publication_tables`, там только `agent_events` и `agent_messages` (`agent_base.sql:352-353`). Из-за этого `useAgentStatusRealtime` (`frontend/src/hooks/useRealtimeFeed.ts:140-174`) не срабатывает никогда. Для дашборда со списком агентов живой статус обязателен, поэтому добавляем таблицу в публикацию здесь.
- Текущие данные (3 агента, 4 строки онбординга у 5 профилей) подтверждают инвариант `agents.id == agent_onboarding_sessions.id` во всех завершённых сессиях. Есть одна брошенная строка со статусом `not_started` — после правки фронтенда её владелец продолжит мастер с шага Telegram, что корректно.
- SQLAlchemy-модель `AgentOnboardingSessionModel` (`src/mimic42/integrations/database_models.py:85-111`) unique на `owner_id` не объявляла — правки не требует.

## 2. Бэкенд: онбординг создаёт новую сессию

`src/mimic42/core/onboarding.py`

- `AgentOnboardingService.request_telegram_code(credentials, *, onboarding_id: UUID | None = None)`:
  - если `onboarding_id` передан — загрузить строку через `self._repository.get(onboarding_id)`, проверить `session.owner_id == credentials.owner_id` (иначе `PermissionError`/спец-исключение, которое роут превратит в 403), сохранить уже введённые `name` / `soul_prompt`;
  - если не передан — `uuid4()`, как сейчас в ветке `else` (`onboarding.py:193-195`).
- Убрать `get_by_owner` из протокола `OnboardingRepository` (`onboarding.py:106`) и из `InMemoryOnboardingRepository` (`onboarding.py:122-126`) — после отказа от «одна сессия на владельца» этот метод не имеет корректной семантики.

`src/mimic42/integrations/database_onboarding.py`

- Удалить `DatabaseOnboardingRepository.get_by_owner` (`:49-58`).

`src/mimic42/api/app.py`

- `TelegramLoginRequest` (модель запроса `POST /api/v1/onboarding/telegram`) получает необязательное поле `onboarding_id: UUID | None = None`; роут `request_telegram_code` (`app.py:267`) прокидывает его в сервис.
- Обработать `OnboardingNotFoundError` → 404 и несовпадение владельца → 403 рядом с существующей обработкой ошибок Telethon.

## 3. Бэкенд: удаление агента

`src/mimic42/core/manager.py` — новый метод `AgentManager.remove_agent(agent_id)`:

- под `self._lock` достать рантайм из `self._agents` и удалить запись из словаря (удалять до `stop()`, чтобы параллельный `get_agent` не поднял его заново);
- вне лока вызвать `runtime.stop()` (идемпотентен, `agent_runtime.py:167-186`: снимает задачу планировщика, закрывает http-клиент, отключает Telethon), исключения гасить с логированием — строку в БД надо удалить даже если Telegram-отключение упало;
- если агента нет в реестре — не ошибка, просто выходим (агент мог быть остановлен и выгружен).

`src/mimic42/core/agent_store.py` — в протокол `AgentStore` добавить `delete_agent(agent_id: UUID) -> None`; реализовать в `InMemoryAgentStore` (выкинуть из `_agents` и `_configs`).

`src/mimic42/integrations/database_agent_store.py` — `DatabaseAgentStore.delete_agent`:

- удалить строки `agent_onboarding_sessions`, у которых `completed_agent_id == agent_id`. Это обязательный шаг: FK объявлен `on delete set null` (`agent_base.sql:81`), и без явного удаления после сноса агента останется «черновик» онбординга со статусом `authorized`, который мастер подхватит как незавершённый;
- удалить строку `agents` — `telegram_sessions`, `message_threads`, `agent_messages`, `agent_events`, `agent_timers` уйдут каскадом.

`src/mimic42/api/app.py` — новый роут `DELETE /api/v1/agents/{agent_id}` (204):

- `_ensure_agent_owner` (`app.py:642`) для проверки владения;
- `manager.remove_agent(agent_id)`;
- `store.delete_agent(agent_id)`;
- best-effort очистка долговременной памяти: `Mem0LongTermMemory.clear_all_memories(agent_id)` уже есть (`integrations/mem0_memory.py:64-65`), надо только вызвать его при наличии `_get_long_term_memory(app)` и погасить исключение с логированием. Попутно дописать `delete_all` в протокол `Mem0ClientLike` (`mem0_memory.py:10-19`) — сейчас метод вызывается, но в протоколе не объявлен, `ty` на это ругается.

Протокол `AgentManagerLike` в начале `app.py` (`:52-73`) дополнить сигнатурой `remove_agent`.

## 4. Фронтенд: мастер создаёт новую сессию каждый раз

`frontend/src/hooks/useOnboarding.ts`

- `useOnboardingSession` — выбирать последнюю строку `.is('completed_agent_id', null)` в дополнение к `.eq('owner_id', user.id)`, т. е. только незавершённый черновик. Завершённые сессии больше не блокируют мастер.
- `useSaveOnboardingStep` — вместо `upsert({ onConflict: 'owner_id' })` (`:80-87`) принимать `sessionId: string | null`: при `null` делать `insert` новой строки (id генерирует БД, возвращаем через `.select().single()`), иначе `update(...).eq('id', sessionId)`. Хук возвращает актуальную строку, страница держит её id.
- `useFinalizeAgent` — убрать несуществующее поле `system_prompt` из тела запроса (`:194-198`; ни в `FinalizeAgentInput`, ни в `OnboardingSessionRow` его нет — сейчас это скрытая ошибка типов, замаскированная `typescript.ignoreBuildErrors` в `frontend/next.config.js`). После успеха инвалидировать `queryKeys.onboarding.session()` и `queryKeys.agents.list()` и вести на `/dashboard`.
- Новый хук `useDiscardOnboardingDraft` — удаляет черновик по id (для кнопки «Начать заново»).
- `useStartTelegramAuth` — передавать `onboarding_id` текущего черновика в `onboardingApi.startTelegram`.

`frontend/src/lib/api.ts` — `OnboardingTelegramInput` получает `onboarding_id`; `agentsApi` получает `remove: (id) => apiClient.delete(...)`.

`frontend/src/types/index.ts` — обновить `OnboardingTelegramInput`, добавить тип ответа удаления; выкинуть мёртвый шаг `system_prompt` из `OnboardingStep` (`:264`) и связанные с ним `systemPromptSchema` / `DEFAULT_SYSTEM_PROMPT` в `lib/validators.ts` и `lib/constants.ts`, раз колонку уже удалили миграцией `20260524144659_remove_system_prompt.sql`.

`frontend/src/app/(dashboard)/onboarding/page.tsx`

- Снять блокировку `if (session?.completed_agent_id) return <OnboardingComplete/>` (`:69`) — она больше не нужна, потому что хук отдаёт только черновики.
- Прокидывать id черновика (или `null`) в шаги; шаг «Имя» создаёт строку.
- Добавить кнопку «Начать заново», сбрасывающую черновик.
- В заголовок добавить ссылку «← К агентам» на `/dashboard`, чтобы из мастера можно было выйти.

`frontend/src/middleware.ts` — редирект на `/onboarding` при нуле агентов (`:72-83`) оставляем как есть; он не мешает заходить в мастер при уже существующих агентах.

## 5. Фронтенд: главная страница по всем агентам

`frontend/src/app/(dashboard)/dashboard/page.tsx` переписывается с «один выбранный агент» на сводку по всем:

- **KPI-строка по всем агентам.** Новый хук `useAllAgentsKPIs(agentIds: string[])` рядом с `useDashboardKPIs` в `frontend/src/hooks/useTelegramSession.ts`: те же четыре запроса, но `.in('agent_id', agentIds)` вместо `.eq(...)`. Ключ кэша — новый `queryKeys.analytics.kpisAll(agentIds)` в `lib/queryClient.ts`. Переиспользовать существующую вёрстку `KPIRow` (`dashboard/page.tsx:138-199`).
- **Сетка карточек агентов.** По образцу карточек в `TabMemory` (`frontend/src/app/(dashboard)/agent/[id]/page.tsx`, ~750): `Card variant="glass"`, имя (через `sanitizeText` из `lib/sanitize.ts`), `AgentStatusBadge`, номер телефона Telegram, время последнего запуска, кнопки «Запустить»/«Стоп» (`useStartAgent` / `useStopAgent`), ссылка на `/agent/{id}`, кнопка удаления. Плюс карточка-плейсхолдер «+ Новый агент» → `/onboarding`.
- **Удаление.** Новый хук `useDeleteAgent` в `frontend/src/hooks/useAgents.ts` по образцу `useStartAgent` (optimistic `onMutate` → откат в `onError` → инвалидация `agents.list()` в `onSettled`). В UI — существующий `ConfirmDialog` из `components/ui/modal.tsx` с `variant="danger"`, в тексте явно предупредить, что удалятся история сообщений, события и Telegram-сессия. После удаления — тост через `useToast`.
- **Объединённый live-feed.** Новый хук `useMultiAgentRealtimeFeed(agentIds: string[])` в `frontend/src/hooks/useRealtimeFeed.ts`: **один канал** `agent-feed-all` с фильтром `agent_id=in.(uuid1,uuid2,...)` на `agent_messages` и `agent_events` — фильтр `in.()` в `postgres_changes` поддерживается (проверено по докам Supabase, это `= ANY`, лимит 100 значений, uuid без кавычек проходят). Сообщения сливаются в общий отсортированный список; в элементе фида показывать, какому агенту он принадлежит (у `AgentMessageRow`/`AgentEventRow` есть `agent_id`). Существующий `useRealtimeFeed` оставить — он используется на странице агента.
- **Типы фида.** `FeedItem.direction` объявлен как `'incoming' | 'outgoing' | undefined`, а `AgentMessageRow.direction` — просто `string`; из-за этого `useRealtimeFeed.ts:112` и `agent/[id]/page.tsx:401` не проходят `tsc`. При правке хука привести типы в согласие (сузить в `types/index.ts` до реального набора значений enum `agent_message_direction` либо честно расширить `FeedItem`).
- **Живые статусы.** `useAgentStatusRealtime` вызывать по одному разу на агента (после добавления `agents` в публикацию из шага 1 он наконец начнёт работать); либо сделать вариант хука, подписывающийся на UPDATE `agents` без фильтра — RLS отдаст только своих.
- Пустое состояние `NoAgents` (`:353`) оставить.

`frontend/src/components/layout/Sidebar.tsx` — под списком агентов добавить пункт «+ Новый агент» → `/onboarding`.

## 6. Отдельно: найденный дефект рантайма

При разборе кода нашёлся не связанный с задачей баг, из-за которого не работают таймеры агента. В `src/mimic42/api/app.py:181-188` продакшн-`AgentManager` создаётся без `session_factory=session_factory`, поэтому:

- `MimicAgentRuntime` получает `session_factory=None` и не запускает планировщик (`core/agent_runtime.py:160`);
- инструмент `set_wakeup_timer` всегда возвращает ошибку «Database session factory or agent_id not configured» (`integrations/telegram_tools.py:2141-2145`).

Починка — одна строка. Делаем её в рамках этой же ветки; если не нужно, скажите, и я вынесу отдельно.

## 7. Тесты

Проверено: `get_by_owner` в тестах не используется вообще (только 4 ссылки в `src/`), и ни один тест не закрепляет поведение «повторный вызов переиспользует сессию». Поэтому при необязательном параметре `onboarding_id` существующие тесты продолжают проходить без правок — прогнать и убедиться.

Добавить:

- сервис: два последовательных прохода онбординга одного владельца дают два разных `agent_id` и две строки в `agent_onboarding_sessions`;
- `DatabaseAgentStore.create_from_onboarding` дважды с разными `onboarding_id` → два агента у одного владельца;
- `AgentManager.remove_agent`: останавливает запущенный рантайм, убирает его из реестра, повторный вызов не падает;
- `DatabaseAgentStore.delete_agent`: удаляет агента и связанную строку онбординга, не задевает других агентов владельца;
- API: `DELETE /api/v1/agents/{id}` — 204 для владельца, 404 для чужого агента;
- фронт (vitest): `deriveOnboardingStep` для черновика без `completed_agent_id`.

## Проверка

1. `uv run pytest` — базовый прогон сейчас: **82 passed**, должно остаться зелёным и вырасти на новые тесты.
   `ruff check .` и `ty check` — в репозитории уже есть долг, не связанный с задачей (25 ошибок ruff и 98 диагностик ty, сосредоточены в `integrations/telegram_tools.py`, `integrations/langchain_agent.py`, `core/agent_runtime.py` и тестах). Критерий — не увеличить эти числа; чинить чужой долг в этой ветке не будем.
2. `cd frontend && bun run lint && bun run typecheck && bun run test && bun run build`. `typecheck` обязателен отдельно: `next.config.js` выставляет `typescript.ignoreBuildErrors: true`, поэтому `build` ошибки типов не покажет. Сейчас `typecheck` падает на 5 ошибках, все в файлах, которые мы и так правим (`hooks/useOnboarding.ts:197` — `system_prompt`, `hooks/useRealtimeFeed.ts:112` и `agent/[id]/page.tsx:401` — сужение `direction` до `'incoming' | 'outgoing'`, `agent/[id]/page.tsx:209` — `reasoning_effort`). Цель — довести фронтенд до нуля ошибок типов.
3. Применить миграцию: `supabase db push` (или `supabase migration up` локально), убедиться, что unique снят и `agents` есть в публикации:
   `select conname from pg_constraint where conrelid = 'public.agent_onboarding_sessions'::regclass;`
4. Живой прогон: `uv run uvicorn mimic42.main:app --reload` + `bun dev`.
   - На `/dashboard` виден существующий агент, KPI и фид работают.
   - «+ Новый агент» → мастер проходится с нуля на **другом** номере Telegram → в БД появляется вторая строка `agent_onboarding_sessions` и второй `agents` → оба агента видны на дашборде и в сайдбаре.
   - Запустить обоих одновременно, написать в оба Telegram-аккаунта, убедиться, что каждый отвечает своим характером и сообщения пишутся с правильным `agent_id`.
   - Перезапустить бэкенд — оба поднимаются из `running` (`app.py:194`).
   - Удалить второго агента: рантайм останавливается, строки `agents` / `telegram_sessions` / `agent_messages` уходят, первый агент продолжает работать, мастер после этого начинает с чистого листа.
5. Только после живого теста — PR (по памяти проекта PR открывается после проверки пользователем).
