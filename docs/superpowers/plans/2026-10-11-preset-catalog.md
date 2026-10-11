# Preset Catalog Implementation Plan

**Goal:** Дать пользователям вкладку «Каталог пресетов»: список пресетов, избранное, собственные пресеты с публикацией для всех. Окно выбора пресета у Мимика показывает наши четыре пресета, избранное и собственные.

**Architecture:** Всё держится на Supabase под RLS, бэкенд (Python) не меняется. `prompt_presets` получает владельца и флаг публикации, новая таблица `prompt_preset_favorites` хранит избранное. Фронтенд читает и пишет напрямую через `supabase-js` (как уже делают `usePromptPresets` и `useAgentDetails`). Выбор пресета в окне агента и онбординге считается на клиенте чистой функцией `pickablePresets`. Новая страница `/presets` — три раздела: «Каталог», «Избранное», «Мои».

**Tech Stack:** Supabase Postgres (SQL-миграция, RLS, колоночные гранты), Next.js 14 App Router, React 18, TanStack Query v5, TypeScript, zod, Tailwind 3 поверх shadcn/radix-обёрток из `frontend/src/components/ui/`, `bun test` + Testing Library, pytest (интеграционные тесты `-m db`, Playwright `-m e2e`).

**Spec:** `docs/superpowers/specs/2026-10-11-preset-catalog-design.md`
**Issue:** https://github.com/42-Z/Mimic42/issues/67 (назначена на crbanana)

---

## 0. Состояние на момент плана

Уже сделано, всё локально и ничего не закоммичено:

| Что | Где | Статус |
|---|---|---|
| Назначение issue #67 на crbanana | GitHub | сделано |
| Спека | `docs/superpowers/specs/2026-10-11-preset-catalog-design.md` | написана |
| Черновик миграции | `supabase/migrations/20261011103120_preset_catalog.sql` | **написан, нигде не применён и не проверен**; имя файла создано `supabase migration new` |
| Зависимости | `frontend/node_modules`, `.venv` | установлены (`bun install --frozen-lockfile`, `uv sync --locked --all-groups`) |
| Supabase CLI 2.100.1 (версия из CI) | папка scratchpad, вне репозитория | скачан, хеш сверен с `checksums.txt` релиза |

Решения владельца (зафиксированы в спеке):

1. В окне выбора: **наши четыре всегда + избранное + свои**. Остальное из каталога попадает туда только через избранное.
2. Публикация: **сразу, без модерации**.

## 1. Ограничения среды и как мы их обходим

Проверено, а не предположено:

- **Postgres по TCP из этой песочницы недоступен** (порты 5432 и 6543 пула Dev не отвечают; в документации среды raw-TCP базы через прокси не поддерживаются). Значит здесь **не работают**: `supabase db push --db-url`, `psql`, `uv run pytest -m db`, e2e-сервер тестов (ему нужен `DATABASE_CONNECTION_STRING`).
- Доступно по HTTPS: Supabase MCP (`execute_sql`, `list_migrations`, `get_advisors`, `generate_typescript_types`) к проекту **Mimic42 Dev** (`ipqylrdmmjitemjrygej`), `supabase-js` с фронтенда, скачивание документации.
- **Supabase MCP не пропускает разрушительный SQL** (`drop`, `revoke`, `delete`, даже на временной таблице с откатом): сервер требует подтверждение, которое в облачной сессии некому подтвердить, вызов возвращается с `MCP tool call requires approval`/`cancelled`. Запросы на чтение и безобидный SQL проходят. URL коннектора claude.ai править нельзя, так что отключить подтверждения нельзя. Обходить проверку переписыванием SQL не нужно: миграция содержит `drop policy` и `revoke`, и это правильное содержимое.
- Переменные окружения указывают на Dev, не на прод (`assert_test_project` в `mimic42.testing.slots` разрешает только Dev). Прод — проект `ajcznltdbwvhmhgzufzv` («Mimic 42»), его в этой задаче **не трогаем**.
- CI (`.github/workflows/ci.yml`) запускается на `pull_request` и `push` в `main`. Пуш в рабочую ветку без PR CI не запускает. Джобы `backend-db`, `e2e`, `migrations-drift` пройдут только после открытия PR, а по `AGENTS.md` PR открывается после проверки владельцем локально.

Стратегия проверки, исходя из этого:

| Что проверяем | Чем здесь | Что остаётся владельцу / CI |
|---|---|---|
| Синтаксис и поведение миграции, RLS | Те же 21 сценарий (45 проверок) на **локальном Postgres 16** (`pgserver` из PyPI): исходное состояние строится из настоящих миграций репозитория, роли Supabase и `auth.uid()` воссозданы. После применения на Dev: проверки только на чтение через MCP (каталог, права, история, advisors) | сценарии на самом Dev через `verify.sql` в SQL Editor (по желанию), `uv run pytest -m db` (джоба `backend-db`) |
| Дрейф миграций | Запись в `supabase_migrations.schema_migrations` с тем же `version`, что у файла (см. задачу 1) | джоба `migrations-drift` |
| Фронтенд-логика и компоненты | `bun test`, `bunx next lint`, `bun run typecheck` | — |
| Страница в браузере | Dev-сервер Next + Playwright-скрипт из scratchpad против реального Supabase Dev (логин персоной слота, бэкенд FastAPI не нужен для `/presets`) | сквозной e2e (`uv run pytest tests/e2e`) |
| Python-тесты БД и e2e | пишутся, импортируются (`pytest --collect-only`), проходят `ruff`/`ty`; **выполнить их здесь нельзя**, и итоговый отчёт скажет об этом прямо | владелец локально и CI |

## 2. Global Constraints

- Порядок работ: Task 1 → 2 → 3 → … → 9. Task 3, 4 и 5 зависят от типов из Task 1.
- Python-код продукта не меняется. Из Python трогаем только тестовую инфраструктуру (`src/mimic42/testing/cleanup.py`) и тесты.
- Миграции только через Supabase CLI. Файл уже создан командой `supabase migration new`; не переименовывать и не создавать руками. Пуш в прод-базу запрещён.
- Типы фронтенда `frontend/src/types/supabase.ts` генерируются, руками не правятся. Если генератор даёт большой посторонний диф, остановиться и решить отдельно.
- UI: сначала скилл `impeccable` (`impeccable context` один раз за сессию, затем `reference/new-work.md` и `reference/craft-floor.md` перед правкой), затем `shadcn` (`bunx --bun shadcn@latest info`, `docs <component>`, `add ... --dry-run` и `--diff` до установки). Тёмная палитра и токены из `DESIGN.md` неизменны: никаких новых оттенков, только `bg-card`, `border-border`, `text-muted-foreground`, `text-success`, `text-destructive`. Иконки только `lucide-react`.
- Все тексты интерфейса на русском. Комментарии в коде: doc-комментарии и «почему», без заголовочных (`// === ... ===`).
- Не создавать файлов вне исходников, кроме спеки и этого плана. Скрипты проверки живут в scratchpad, не в репозитории.
- Инкрементальной верификации через пуш нет: сначала все проверки локально, потом один пуш.
- Полный pre-PR набор (Task 7) запускается один раз перед пушем.
- Коммиты: Conventional Commits, тема в одну строку, в конце трейлеры `Co-Authored-By` и `Claude-Session`. Ветка `claude/practical-knuth-kbxqyl`. PR не открывать.
- Секреты (пароль БД, ключи) в вывод и в файлы репозитория не попадают.

## 3. Требует вашего подтверждения

Это единственные места, где я выйду за рамки «пишу файлы в репозиторий»:

1. **Применить миграцию к Dev скриптом `apply.sql` в SQL Editor Dashboard** (выполняете вы). `supabase db push` отсюда не достаёт до базы, а MCP не пропускает такой SQL (раздел 1). Скрипт делает ровно то, что `db push`: исполняет операторы файла и записывает в `schema_migrations` строку с версией файла и теми же операторами, одной транзакцией; повторный запуск останавливается защитой. Dev общая (её используют CI и ваши локальные прогоны), миграция аддитивная. Без применения `migrations-drift` и `backend-db` будут красными в PR. Откат описан в приложении А.
2. **Добавить shadcn-компоненты** `tabs`, `badge`, `empty` командой CLI (после `--dry-run`, `--diff`). Если они окажутся несовместимы с Tailwind 3 или токенами проекта, соберу из существующих обёрток (`Card`, `Button`, `Alert`) и роверного таб-бара со страницы агента.

## 4. Task 1: Миграция в Dev и типы

**Files:**
- Modify (при необходимости): `supabase/migrations/20261011103120_preset_catalog.sql`
- Regenerate: `frontend/src/types/supabase.ts`

**Interfaces:**
- Produces: колонки `prompt_presets.owner_id`, `prompt_presets.is_published`; `slug` необязателен; таблица `prompt_preset_favorites`; триггер лимита; политики и гранты по спеке.

- [ ] **Step 1: Перечитать черновик глазами ревьюера.** Проверить: `to authenticated` и `(select auth.uid())` во всех политиках; по одной политике на операцию; колоночные гранты не включают `slug`, `sort_order`, `is_active`; триггер лимита `security invoker` и `set search_path = ''`; цикла политик нет (политики избранного читают `prompt_presets`, обратной ссылки нет).
- [x] **Step 2: Прогнать SQL с откатом на локальном Postgres 16.** Генератор (scratchpad) режет файл на операторы как CLI, исполняет их в `do`-блоке и после сценариев завершает `raise exception`, который откатывает всё; результат несёт текст ошибки. Выполнено: 45 из 45 PASS, `owner_id` после отката отсутствует.
- [ ] **Step 3: Сценарии проверки RLS.** Выполняются в той же транзакции под `set local role authenticated` и `select set_config('request.jwt.claims', '{"sub":"<uuid>","role":"authenticated"}', true)`. Персоны слота `a` (из `slots.py`): автор `11111111-1111-1111-1111-000000000002`, чужой `11111111-1111-1111-1111-000000000005`. Каждый запрещающий случай парный: проверка отказа плюс проверка, что строка цела.

| # | Сценарий | Ожидание |
|---|---|---|
| 1 | Автор вставляет `(owner_id=автор, title, summary, body)` | строка создана, `is_published=false`, `slug is null`, `sort_order=0`, `is_active=true` |
| 2 | Автор вставляет с `owner_id=чужой` | `42501` (RLS) |
| 3 | Автор вставляет с колонкой `slug` / `sort_order` / `is_active` | `42501` (нет колоночного права) |
| 4 | Автор вставляет `is_published=true` | допустимо |
| 5 | Чужой читает личный пресет автора | 0 строк; после публикации автором — 1 строка |
| 6 | Чужой делает `update` / `delete` чужого пресета | `UPDATE 0` / `DELETE 0`, строка цела |
| 7 | Автор меняет `owner_id` своей строки | `42501` (нет права на колонку) |
| 8 | Автор меняет `title`, `body`, `settings`, `is_published` | допустимо |
| 9 | Любой пользователь читает наши четыре | 4 строки, с `slug`, `owner_id is null` |
| 10 | Любой пользователь пишет/удаляет наш пресет | `42501` / `DELETE 0` |
| 11 | Вставка пресета с длиной `title` 81, `summary` 201, `body` 50 001, `settings` > 16 КиБ | `23514` для каждого |
| 12 | 51-я вставка пресета одним владельцем | `23514` с текстом «Достигнут лимит собственных пресетов (50)» |
| 13 | Под ролью `postgres`: строка без владельца и без `slug`; строка с владельцем и с `slug`; строка без владельца с `is_published = false` | `23514` во всех трёх случаях (`prompt_presets_slug_only_for_curated` дважды, `prompt_presets_curated_is_published`) |
| 14 | Избранное: свой пользователь добавляет опубликованный чужой, наш, свой личный | допустимо |
| 15 | Избранное: чужой личный пресет по id | `42501` (WITH CHECK через RLS пресета) |
| 16 | Избранное: `user_id` чужого | `42501` |
| 17 | Избранное: читает только свои строки; удалять чужие нельзя | 0 строк / `DELETE 0` |
| 18 | Автор снимает публикацию | у чужого запись избранного остаётся, но пресет не читается |
| 19 | Автор удаляет пресет | избранные строки всех пользователей исчезают каскадом |
| 20 | `anon`: любой доступ к обеим таблицам | `42501` |
| 21 | Права: у `authenticated` нет `truncate`/`update` по `owner_id`/`slug`; у `anon` ничего | через `has_table_privilege`, `has_column_privilege` |

- [ ] **Step 4: Исправить найденное в файле миграции, повторить Step 2–3 до зелёного.** Файл остаётся единственным источником правды.
- [ ] **Step 5: Применить к Dev.** Вы выполняете `apply.sql` в SQL Editor проекта Mimic42 Dev (Dashboard покажет предупреждение о разрушительных операциях, подтвердить). Формат истории проверен по существующим строкам Dev: колонки `version`, `statements text[]`, `name`; у CLI в `statements` лежат отдельные операторы файла с ведущими комментариями, скрипт делает так же. Не использовать `apply_migration`: он сгенерирует свой `version`, и `migrations-drift` покажет расхождение.
- [ ] **Step 6: Проверка после применения (я, только чтение через MCP).** `list_migrations` содержит `20261011103120`; сверка версий Dev с именами файлов в `supabase/migrations/` по логике джобы `migrations-drift`; каталог: колонки, ограничения, триггер, политики, `has_*_privilege`; `get_advisors` (security и performance): новых предупреждений по этим двум таблицам быть не должно. По желанию вы запускаете `verify.sql` в SQL Editor: итог в тексте ошибки `RESULT (rolled back)`, ожидается `ИТОГО: PASS=45 FAIL=0`.
- [ ] **Step 7: Регенерировать типы.** MCP `generate_typescript_types` для Dev, записать в `frontend/src/types/supabase.ts`. Сверить `git diff`: меняются только `prompt_presets`, новая `prompt_preset_favorites`. Если лишнее — остановиться.
- [ ] **Step 8: Проверка на старых клиентах.** Прежний код фронтенда делает `select *` с `eq('is_active', true)`: после миграции он продолжает работать и получает больше колонок. Убедиться запросом под ролью `authenticated`.

## 5. Task 2: Очистка слота и интеграционные тесты БД

**Files:**
- Modify: `src/mimic42/testing/cleanup.py`
- Modify: `tests/integration/test_cleanup.py`
- Modify: `tests/integration/test_prompt_presets.py`
- Create: `tests/integration/test_preset_catalog.py`

**Interfaces:**
- Consumes: схема из задачи 1.
- Produces: `purge_slot_data` убирает пользовательские пресеты и избранное тестовых персон.

- [ ] **Step 1:** В `purge_slot_data` в той же транзакции перед удалением агентов: `delete from public.prompt_preset_favorites where user_id = any($1::uuid[])`, затем `delete from public.prompt_presets where owner_id = any($1::uuid[])` (каскад уберёт чужое избранное пользовательских пресетов).
- [ ] **Step 2:** `test_cleanup.py`: тест «purge убирает пресеты и избранное своего слота и не трогает чужой слот и наши четыре».
- [ ] **Step 3:** `test_prompt_presets.py`: ожидание `EXPECTED_SLUGS` остаётся, тест чтения под `authenticated` считает наши пресеты (`where owner_id is null`), не все строки (в базе теперь могут лежать пользовательские). Тест сида фильтрует `where owner_id is null`.
- [ ] **Step 4:** `test_preset_catalog.py` по образцу `test_onboarding_rls.py` (`_act_as_client`, `clean_slot.persona(...)`, `pytest.raises(asyncpg.InsufficientPrivilegeError, match=...)`, фикстура `clean_slot`). Тесты (по сценариям из таблицы Step 3 задачи 1): `test_author_creates_private_preset`, `test_client_cannot_set_curated_columns`, `test_private_preset_hidden_until_published`, `test_other_user_cannot_edit_or_delete`, `test_owner_cannot_be_reassigned`, `test_curated_presets_readable_not_writable`, `test_length_and_size_limits`, `test_own_preset_limit`, `test_favorites_only_for_visible_presets`, `test_favorites_are_private`, `test_unpublish_hides_from_favorites_and_delete_cascades`, `test_anon_has_no_access`.
- [ ] **Step 5: Что запускаемо здесь:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, `uv run pytest tests/integration/test_preset_catalog.py tests/integration/test_prompt_presets.py tests/integration/test_cleanup.py -m db --collect-only -q` (импорт и сбор без подключения к БД). **Выполнить тесты здесь нельзя** (нет TCP до Dev); поведение уже подтверждено SQL-сценариями задачи 1, а прогон `-m db` остаётся за владельцем и CI.

## 6. Task 3: Слой данных и чистая логика фронтенда

**Files:**
- Modify: `frontend/src/types/index.ts` (`PromptPresetRow`: `slug: string | null`, `owner_id: string | null`, `is_published: boolean`)
- Modify: `frontend/src/lib/queryClient.ts` (ключи `presets.favorites()`, `presets.all` уже есть)
- Modify: `frontend/src/hooks/usePromptPresets.ts`
- Create: `frontend/src/lib/presets/catalog.ts`
- Create: `frontend/src/lib/presets/errors.ts`
- Create: `frontend/src/hooks/useCurrentUserId.ts`
- Create: `frontend/src/hooks/usePresetFavorites.ts`
- Create: `frontend/src/hooks/usePresetMutations.ts`
- Tests: `frontend/src/__tests__/preset-catalog.test.ts`, `preset-errors.test.ts`, обновить `prompt-presets.test.ts`, новый `preset-favorites.test.ts`

**Interfaces (Produces):**

```ts
// lib/presets/catalog.ts
export const PRESET_LIMITS = { title: 80, summary: 200, body: 50_000, maxOwn: 50 } as const;
export const presetFormSchema: z.ZodType<PresetFormValues>;   // title/summary/body trim, body min 10, enabled_tools: string[] | null
export function isCuratedPreset(p: PromptPresetRow): boolean;                 // owner_id === null
export function isOwnPreset(p: PromptPresetRow, userId: string | null): boolean;
export function sortPresets(ps: PromptPresetRow[]): PromptPresetRow[];        // наши по sort_order, затем свои и чужие от новых к старым
export function searchPresets(ps: PromptPresetRow[], query: string): PromptPresetRow[];   // title+summary, без регистра
export function pickablePresets(ps, favoriteIds: ReadonlySet<string>, userId: string | null): PromptPresetRow[];
export function toolCountLabel(p: PromptPresetRow): string;                   // «Все инструменты» | «16 из 91»
export function presetSettings(enabledTools: string[] | null): Record<string, unknown> | null;
```

```ts
// hooks
usePromptPresets(): UseQueryResult<PromptPresetRow[]>            // все видимые, RLS отсекает чужие личные
usePresetFavoriteIds(): UseQueryResult<Set<string>>
useToggleFavorite(): UseMutationResult<void, Error, { presetId: string; favorite: boolean }>   // оптимистично, откат при ошибке
useSavePreset(): UseMutationResult<PromptPresetRow, Error, { id?: string } & PresetFormValues>  // insert с owner_id | update без owner_id
useDeletePreset(), useSetPresetPublished()
usePickablePresets(): { data: PromptPresetRow[]; isLoading: boolean; isError: boolean }        // ∪ наши ∪ избранное ∪ свои
useCurrentUserId(): UseQueryResult<string | null>                // supabase.auth.getUser()
```

- [ ] **Step 1: Падающие тесты** (`bun test`) на все чистые функции и на форму запросов к фейковому клиенту (существующий приём из `prompt-presets.test.ts`). Случаи: порядок (наши по `sort_order`, остальные по `created_at` убыв.); поиск по названию и описанию, пустой запрос; `pickablePresets` берёт все наши, избранные чужие и свои личные, но не чужие неизбранные и не чужие избранные, которых нет в списке (скрытые); дубликатов нет; `userId=null` не считает ничего «своим»; схема формы (обрезка пробелов, границы 80/200/50 000, `body` ≥ 10); `presetSettings(null)` → `null`, список → `{enabled_tools}`; `insert` отправляет `owner_id`, `update` его не отправляет; ошибки PostgREST (`23514` с текстом лимита, `42501`, сетевая) превращаются в понятные русские сообщения.
- [ ] **Step 2:** Реализация. Фетчеры — отдельные экспортируемые функции (как `fetchPromptPresets`), чтобы тестировать без react-query. `staleTime` по умолчанию клиента (30 с) вместо `Infinity`: каталог живой, публикации других пользователей должны появляться; избранное обновляется при возврате в окно (`refetchOnWindowFocus`).
- [ ] **Step 3:** Мутации инвалидируют `queryKeys.presets.all`; избранное обновляется оптимистично с откатом и тостом об ошибке (по образцу других мутаций проекта).
- [ ] **Step 4:** `cd frontend && bun test src/__tests__/preset-*.test.ts src/__tests__/prompt-presets.test.ts` — зелёное.

## 7. Task 4: Окно выбора на новых правилах

**Files:**
- Modify: `frontend/src/components/agent/PresetPicker.tsx`
- Modify: `frontend/src/__tests__/preset-picker.test.tsx`

- [ ] **Step 1: Тесты.** Обновить фикстуры (`slug: string | null`, `owner_id`, `is_published`). Добавить: выбор идёт по `id` (два пресета с `slug: null` не конфликтуют); у пресета видны метки «Наш» / «Ваш» / «Личный»; в подвале есть ссылка «Каталог пресетов» на `/presets`, открывается в новой вкладке (`target="_blank"`, `rel="noopener noreferrer"`), чтобы форма агента и черновик онбординга не терялись; пустой список показывает «Пока нет доступных пресетов» и ссылку на каталог. Существующие тесты (подтверждение перед заменой, перенос `enabled_tools`, пустой allowlist, ошибка загрузки) проходят без изменения поведения.
- [ ] **Step 2:** `PresetPicker` берёт список из `usePickablePresets()`. `PresetPickerDialog` сохраняет прежний интерфейс (`presets`, `isLoading`, `isError`, `currentValue`, `onApply`) и получает один необязательный проп `currentUserId?: string | null` (по умолчанию `null`): по нему и по `owner_id` строки считается метка «Ваш». Выбор: `selectedId` вместо `selectedSlug`, `key={preset.id}`. `data-testid="open-presets"`, `preset-body`, `preset-tools` не менять: на них завязаны e2e.
- [ ] **Step 3:** Места использования (`TabSettings.tsx`, онбординг `page.tsx`) менять не нужно: интерфейс `PresetPicker` (`currentValue`, `onApply`) прежний. Проверить `bun run typecheck`.

## 8. Task 5: Страница каталога

**Files:**
- Create: `frontend/src/app/(dashboard)/presets/page.tsx`
- Create: `frontend/src/components/presets/PresetCatalog.tsx` (контейнер: хуки, вкладки в URL `?tab=`)
- Create: `frontend/src/components/presets/PresetCatalogView.tsx` (презентация без сети — для тестов)
- Create: `frontend/src/components/presets/PresetCard.tsx`
- Create: `frontend/src/components/presets/PresetPreviewDialog.tsx`
- Create: `frontend/src/components/presets/PresetFormDialog.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx` (пункт «Каталог пресетов», иконка `Library` или `Store` из lucide, `exact: false`)
- Possibly create via CLI: `frontend/src/components/ui/{tabs,badge,empty}.tsx` (после `--dry-run`/`--diff`, см. раздел 3)
- Tests: `preset-card.test.tsx`, `preset-catalog-view.test.tsx`, `preset-form.test.tsx`

**UX-спецификация (режим Operate: сканируемость, привычные паттерны, бренд в деталях):**

- Шапка страницы: один `h1` «Каталог пресетов» (`CardTitle as="h1"` по DESIGN.md), строка описания, справа кнопка «Создать пресет» (`Button`, иконка `Plus`).
- Под шапкой: поиск (`Input`, «Поиск по названию и описанию») и вкладки «Каталог · N», «Избранное · N», «Мои · N». Вкладки с роверным tabindex: переиспользовать `nextTabFocusIndex` из `lib/keyboard.ts` и разметку вкладок страницы агента (`role="tablist"`, `aria-selected`, `aria-controls`). Активная вкладка в URL (`/presets?tab=favorites`).
- Сетка карточек: 1 колонка на мобильном, 2 на `lg`, 3 на `2xl`. Карточка: название (`font-display`), описание, метки (Space Mono, `rounded-sm`): «Наш» (нейтральная), «Ваш» (primary), «Личный» / «Опубликован» только у своих, «Инструменты: 16 из 91» или «Все инструменты». Действия: «Посмотреть», звезда избранного (`aria-pressed`, `aria-label="Добавить в избранное: <название>"`; у наших нет звезды, вместо неё подпись «Всегда в выборе»), у своих ещё «Изменить» и переключатель публикации (`Switch`, `label="Опубликовать: <название>"`).
- Состояния: загрузка (скелетоны карточек), ошибка загрузки (`Alert` с кнопкой «Повторить»), пусто в «Избранное» («Здесь будут пресеты, которые вы отметите звездой» + кнопка «Открыть каталог»), пусто в «Мои» («У вас пока нет своих пресетов» + «Создать пресет»), пустой результат поиска («Ничего не найдено»).
- Предпросмотр: `Modal` с полным текстом (`pre`, как в окне выбора), числом инструментов и действиями «В избранное»/«Закрыть».
- Форма пресета (`Modal`, режим создания и правки): поля «Название» (счётчик 80), «Краткое описание» (200), «Промпт» (`Textarea`, счётчик 50 000), опциональный блок «Настройки инструментов» с переключателем «Задать набор инструментов» и переиспользуемым `ToolsSettings` (по умолчанию выключено: `settings = null`, «включены все»), переключатель «Опубликовать в каталоге» (по умолчанию выключен), валидация zod с ошибками под полями, кнопки «Отмена» / «Сохранить». При достижении лимита 50 кнопка «Создать пресет» отключена с пояснением. Enter внутри формы не отправляет её из поля поиска инструментов (как в `ToolsSettings`).
- Удаление: `ConfirmDialog` «Удалить пресет? Он пропадёт и у тех, кто добавил его в избранное. Агенты, к которым пресет уже применён, не изменятся».
- Доступность: фокус в модалках возвращается (`Modal` уже умеет), все интерактивные элементы с видимым фокусом, статусы не только цветом, контраст как в DESIGN.md.
- Мобильная версия: карточки на всю ширину, действия переносятся, форма в `Modal` скроллится внутри.

- [ ] **Step 1:** `impeccable context` (один раз), прочитать `reference/new-work.md`, `reference/craft-floor.md`. Сверить с `DESIGN.md` и `PRODUCT.md` (тёмный мир не менять).
- [ ] **Step 2:** shadcn: `cd frontend && bunx --bun shadcn@latest info`, `docs tabs badge empty`, `add tabs badge empty --dry-run` и `--diff`. Проверить совместимость с Tailwind 3 (`tailwind.config.ts`, токены `globals.css`) и `radix-nova`; прочитать каждый добавленный файл. Если несовместимы — собрать из существующих обёрток.
- [ ] **Step 3: Падающие тесты** презентационных компонентов: карточка (метки по владельцу и публикации, звезда у чужих/без звезды у наших, `aria-pressed`, вызовы колбэков), вид каталога (вкладки считают и фильтруют, поиск, пустые состояния, ошибка с повтором, отключённая кнопка при лимите), форма (валидация, сборка `settings` через `presetSettings`, публикация, режим правки подставляет значения).
- [ ] **Step 4:** Реализация, пункт в `Sidebar.tsx`. Иконка не меняет доступных имён навигации. Подпись пункта в свёрнутом состоянии — через `title`, как у остальных.
- [ ] **Step 5: Единый проход проверки интерфейса** (не цикл): `bun run dev`, Playwright-скрипт из scratchpad логинится персоной слота (`e2e-full@mimic42.test`, пароль `TEST_USER_PASSWORD`) через Supabase Auth по HTTPS, проходит сценарий: создать личный пресет → опубликовать → открыть вторым пользователем → добавить в избранное → открыть окно выбора у агента (если агента без бэкенда создать нельзя, проверить окно через страницу онбординга) → удалить. Скриншоты десктоп и мобильный одним пакетом; исправления одним пакетом; не более одного повторного прохода. Созданные скриптом строки удаляются через MCP `execute_sql`.

## 9. Task 6: E2E-тест и общая проверка

**Files:**
- Modify: `tests/e2e/test_agent.py` (при необходимости фикстуры)
- Create: `tests/e2e/test_preset_catalog.py`

- [ ] **Step 1:** Сценарии Playwright в стиле `test_agent.py` (`persona_page`, `expect`): «создать пресет, опубликовать, найти его вторым пользователем, отметить звездой, увидеть в окне выбора у агента и применить»; «личный пресет не виден другому»; «удаление убирает пресет из избранного». Использовать `data-testid` и ARIA-имена из задачи 5. Фикстура `auth_states` чистит слот через `purge_slot_data` — теперь вместе с пресетами.
- [ ] **Step 2:** Выполнить здесь нельзя (нужен тестовый сервер с БД по TCP). Проходят `ruff`, `ty` и `pytest tests/e2e --collect-only -q`. Прогон остаётся за владельцем и CI.

## 10. Task 7: Полный набор проверок перед пушем (один раз)

Команды `AGENTS.md`, все запускаются подряд, при красном — исправить всё найденное и повторить набор целиком:

```bash
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -m "not db and not e2e and not real_tg and not real_llm" -W error -q
uv run pytest tests/integration tests/e2e --collect-only -q          # сбор db/e2e-тестов без подключения
cd frontend && bun install --frozen-lockfile && bunx next lint && bun run typecheck && bun test
```

Дополнительно: `git status` без лишних файлов (скачанный CLI и скрипты — в scratchpad), `git diff --stat` соответствует плану, секретов в диффе нет (`grep` по строке подключения и ключам).

## 11. Task 8: Коммиты и пуш

Пять коммитов (Conventional Commits, тема одной строкой), в конце каждого:

```
Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017Ez2ahkjc9KxNjt3AnwsFg
```

1. `docs: дизайн и план каталога пресетов`
2. `feat(db): владелец, публикация и избранное для пресетов`  (миграция, типы Supabase)
3. `test(db): RLS каталога пресетов и очистка слота`
4. `feat(presets): слой данных каталога и новый выбор пресета`  (хуки, `lib/presets`, `PresetPicker`, тесты)
5. `feat(dashboard): страница каталога пресетов`  (страница, компоненты, сайдбар, e2e)

Затем `git push -u origin claude/practical-knuth-kbxqyl` (при сетевой ошибке до 4 повторов с паузой 2, 4, 8, 16 с). **PR не открываю** до вашей проверки приложения локально (правило `AGENTS.md`).

## 12. Task 9: Передача и то, что остаётся после слияния

В итоговом сообщении: что сделано, что проверено здесь (и чем), что **не** проверено (выполнение `pytest -m db`, e2e) и как это запустить:

```bash
uv run pytest -m db tests/integration/test_preset_catalog.py -W error -q
uv run pytest tests/e2e/test_preset_catalog.py -m e2e -W error -q
```

После слияния (по правилам `AGENTS.md` про базу):

1. Применить миграцию на **проде** (проект `ajcznltdbwvhmhgzufzv`). Пайплайн прод не мигрирует (`deploy/README.md`), по вашему указанию это делаю я тем же способом, что и на Dev. Условия, все обязательны: (а) вы проверили приложение локально и подтвердили; (б) миграция применена и проверена на Dev; (в) перед запуском я проверяю прод только на чтение: история миграций совпадает с репозиторием без новой, `prompt_presets` и его политики совпадают с состоянием Dev до миграции; (г) отдельное «да» от вас за строку до запуска. Порядок: **до слияния и деплоя**, миграция аддитивна, старый код её переживает (`select *` с `eq('is_active')` продолжит работать), а новый код без неё сломается. Способ запуска тот же, что на Dev (SQL Editor продового проекта или MCP, если он пропустит запрос), версия в истории `20261011103120`. После применения проверяю каталог и историю на чтение.
2. Проверить статус на доске проекта (https://github.com/orgs/42-Z/projects/2/) и перевести задачу.
3. Убедиться, что `migrations-drift`, `backend-db` и `e2e` прошли в PR, и что после деплоя страница `/presets` открывается.

## Приложение А: откат миграции на Dev

На случай, если Dev нужно вернуть (выполнять только после согласования с владельцем):

```sql
drop table if exists public.prompt_preset_favorites;
drop trigger if exists prompt_presets_enforce_limit on public.prompt_presets;
drop function if exists public.enforce_prompt_preset_limit();
drop policy if exists "Users can read published and own prompt presets" on public.prompt_presets;
drop policy if exists "Users can create their own prompt presets" on public.prompt_presets;
drop policy if exists "Users can edit their own prompt presets" on public.prompt_presets;
drop policy if exists "Users can delete their own prompt presets" on public.prompt_presets;
delete from public.prompt_presets where owner_id is not null;
drop index if exists public.prompt_presets_owner_id_idx;
alter table public.prompt_presets
    drop constraint prompt_presets_slug_only_for_curated,
    drop constraint prompt_presets_curated_is_published,
    drop constraint prompt_presets_title_length,
    drop constraint prompt_presets_summary_length,
    drop constraint prompt_presets_body_length,
    drop constraint prompt_presets_settings_size,
    alter column slug set not null,
    drop column is_published,
    drop column owner_id;
create policy "Authenticated users can read active prompt presets"
    on public.prompt_presets for select to authenticated using (is_active);
delete from supabase_migrations.schema_migrations where version = '20261011103120';
```

Права (`revoke all ... from anon, authenticated` и точечные гранты) откатывать не нужно: прежнее состояние было избыточным.

## Приложение Б: риски

| Риск | Что делаем |
|---|---|
| `execute_sql` не даёт `set local role` / транзакции | Фолбэк: `do $$ ... raise exception 'OK: ...' $$` |
| Генератор типов даёт большой посторонний диф | Остановиться, показать диф, решить с владельцем |
| shadcn-компоненты рассчитаны на Tailwind 4 | Собрать из существующих обёрток, роверный таб-бар со страницы агента |
| Политика вставки со ссылкой на собственную таблицу даёт `42P17` | Уже учтено: лимит в триггере, политики избранного не пересекаются с политиками пресетов |
| Прод получит код раньше миграции | Раздел 12, пункт 1 — миграция до деплоя |
| Окно выбора в онбординге уводит со страницы | Ссылка на каталог открывается в новой вкладке |
