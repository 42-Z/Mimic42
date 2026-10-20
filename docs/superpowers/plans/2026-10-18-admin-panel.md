# Админ-панель — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить в текущий сайт закрытую админ-панель для просмотра пользователей, управления официальными и опубликованными пресетами, смены общей пары Telegram API ID/HASH и просмотра общей статистики.

**Architecture:** FastAPI проверяет административное назначение в базе при каждом запросе; браузер не получает привилегированный Supabase-клиент. Изолированный административный router использует существующий пул SQLAlchemy, отдельный репозиторий и транзакционный журнал изменений. Next.js расширяет нынешнюю оболочку четырьмя подразделами; обычные права владельцев и сохранённые Telegram-сессии не меняются.

**Tech Stack:** Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2 async, Supabase Postgres и CLI 2.100.1, Next.js 14.2, React 18, TypeScript, Tailwind 3.4, shadcn/ui Radix, TanStack Query 5, существующий Recharts 2, uv, Bun, pytest и Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-18-admin-panel-design.md`.

## Порядок и ограничения

- Работа только в уже созданной `feat/admin-panel`, в текущей папке. Новый worktree пользователь отклонил. Пользователь явно поручил выполнить этот план.
- Это одна административная подсистема с общими доступом, аудитом и навигацией. Выполнять этапы последовательно: база → права → модерация → административные операции → UI → локальная проверка. Независимые UI-задачи можно делегировать после закрепления API-контрактов.
- Не менять LangChain, Telethon-рантайм, Mem0, модель по умолчанию, существующие пользовательские полномочия и глобальную визуальную систему.
- Не запускать живые `real_tg`/`real_llm` для этой задачи. Проверка смены defaults использует поддельный Telegram-клиент.
- Не применять миграции, не назначать администраторов и не менять настройки в production во время разработки. Обычные тесты не должны читать `.env` как неявный источник внешних сервисов.
- Команды Python выполняются из корня через `uv run`; команды Bun — из `frontend/`. В каждом этапе сначала новая точечная проверка, затем реализация и та же проверка. Полный набор — только перед PR после подтверждения пользователем локальной работы.
- Для каждой указанной точечной команды ожидаемый результат до изменения — отказ нового сценария по проверяемому поведению, после — PASS с exit code 0. Сбой подключения, ошибка фикстуры или пропуск сценария не считаются подтверждением ни отказа, ни исправления.
- После каждого завершённого этапа отмечать его пункты и делать отдельный Conventional Commit с указанной темой. Не включать чужие изменения через `git add .`.
- Миграции создаёт `supabase migration new`; не выдумывать timestamp. Пользователь разрешил скорректировать уже применённые в Dev, но ещё не выпущенные migration-файлы, чтобы production path не блокировал живые записи и не имел окна отказа favorites; production не затрагивать. Текущий набор: `20261018095739_admin_platform.sql`, `20261018101931_restrict_admin_service_role_grants.sql`, `20261018132159_admin_audit_action_object_consistency.sql`, `20261018145306_preset_moderation.sql`, `20261018163931_preset_lock_policy.sql`, `20261018174711_agent_messages_admin_activity_index.sql`, `20261018174739_agent_events_admin_activity_index.sql`.

## Карта файлов и ответственности

### Бэкенд

| Файл | Изменение и ответственность |
| --- | --- |
| `src/mimic42/core/admin.py` | Новые публичные DTO, протокол `AdminRepository`, предметные ошибки и правила публичности пресетов. |
| `src/mimic42/core/runtime_status.py` | Новая чистая функция согласования сохранённого и текущего состояния; извлечение существующего правила без изменения поведения. |
| `src/mimic42/core/telegram_app_settings.py` | Новый поставщик эффективной общей пары; plaintext существует только на сервере и не входит в публичные DTO. |
| `src/mimic42/integrations/database_models.py` | ORM-модели `AdminUserModel`, `AdminAuditLogModel`, `PlatformTelegramSettingsModel`, `PromptPresetModel`. |
| `src/mimic42/integrations/database_admin.py` | Фасад `DatabaseAdminRepository`: роль, профили, пресеты, настройки, аудит; собственная AsyncSession на операцию. |
| `src/mimic42/integrations/database_admin_statistics.py` | SQL-агрегаты статистики и таблица эффективных состояний для групповых запросов; без HTTP и сериализации секретов. |
| `src/mimic42/api/admin.py` | Router, зависимости роли, request-модели, безопасные `422`, перевод предметных ошибок в HTTP. |
| `src/mimic42/api/app.py` | Инъекция репозитория и поставщика настроек, сборка и закрытие одного engine, подключение router и двух точек разрешения defaults. |
| `tests/integration/conftest.py` | Только именованная фикстура внешней транзакции для новых административных DB-тестов; без autouse. |
| `tests/api/admin_fakes.py` | Подделка репозитория с управляемой ролью и журналом вызовов, без сети. |

### Фронтенд

| Файл | Изменение и ответственность |
| --- | --- |
| `frontend/src/types/admin.ts` | Типы административных ответов и запросов, соответствующие DTO Python. |
| `frontend/src/lib/adminApi.ts` | Запросы через существующий `apiClient`, передача AbortSignal; никакого service key. |
| `frontend/src/lib/queryClient.ts` | Ключи текущих полномочий и административных данных, привязанные к UUID вошедшего пользователя. |
| `frontend/src/hooks/useAdminAccess.ts` | Текущий пользователь, `/me`, периодическая перепроверка и сброс административного кеша. |
| `frontend/src/hooks/useAdmin.ts` | Query-хуки и прямые async-действия пресетов с локальным pending; административные write-запросы не сохраняются в mutation cache. |
| `frontend/src/components/admin/AdminBoundary.tsx` | Не монтирует дочерние экраны до подтверждения роли; состояния загрузки, запрета и ошибки. |
| `frontend/src/components/admin/AdminNavigation.tsx` | Четыре ссылки подразделов, существующие токены и lucide-иконки. |
| `frontend/src/components/admin/AdminPagination.tsx` | Общая доступная постраничная навигация со сбросом страницы при смене поиска. |
| `frontend/src/components/admin/AdminUsers.tsx` | Поиск и список профилей, раскрытие постраничного списка мимиков выбранного пользователя. |
| `frontend/src/components/admin/AdminPresets.tsx` | Официальный редактор, порядок и видимость; read-only просмотр пользовательского пресета. |
| `frontend/src/components/admin/AdminTelegramSettings.tsx` | Форма полной новой пары; HASH только в локальном состоянии компонента. |
| `frontend/src/components/admin/AdminStatistics.tsx` | KPI, распределение состояний, графики активности, отдельные пожизненные токены. |
| `frontend/src/app/(dashboard)/admin/layout.tsx` | Общая граница и административная навигация. |
| `frontend/src/app/(dashboard)/admin/page.tsx` | Тонкий маршрут статистики. |
| `frontend/src/app/(dashboard)/admin/users/page.tsx` | Тонкий маршрут пользователей. |
| `frontend/src/app/(dashboard)/admin/presets/page.tsx` | Тонкий маршрут пресетов. |
| `frontend/src/app/(dashboard)/admin/telegram/page.tsx` | Тонкий маршрут Telegram. |
| `frontend/src/components/layout/Sidebar.tsx` | Условный пункт «Администрирование»; текущая навигация не переписывается. |
| `frontend/src/middleware.ts` | Только исключение точного `/admin` и его дочерних путей из проверки наличия собственного агента. |
| `frontend/src/hooks/usePromptPresets.ts` | Чтение скрытых собственных пресетов под RLS и ограниченный срок свежести. |
| `frontend/src/hooks/usePresetFavorites.ts`, `frontend/src/hooks/usePresetAuthors.ts` | Обновление избранного и авторов после модерации из другой вкладки/сессии. |
| `frontend/src/lib/presets/catalog.ts` | Признак скрытия и исключение неактивных строк из магазина. |
| `frontend/src/app/(dashboard)/presets/page.tsx` | Отметка скрытия в «Моих», сохранение существующих действий автора. |
| `frontend/src/components/agent/PresetPicker.tsx` | Сохраняет доступ автора к своему скрытому пресету; не показывает скрытые официальные. |

Новые примитивы `field`, `empty`, `table`, `pagination`, `toggle-group` и их зависимости устанавливает только shadcn CLI из настроенного `@shadcn`. Существующие `Button`, `Card`, `Input`, `Badge`, `Modal`, `Toast` сохраняют свои локальные API. Не заменять их актуальными шаблонами через `--overwrite` и не обновлять Recharts ради графиков.

## Общий контракт API

В `core/admin.py` закрепить DTO; типы времени сериализуются ISO 8601, UUID — строками. Списки используют `1 <= page <= 1_000_000`, `1 <= page_size <= 100`, по умолчанию 25; поиск `q` обрезается по краям и ограничен 200 символами. Ограничение page не даёт сконструировать гигантский OFFSET и превратить некорректный ввод в backend `503`.

```python
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from mimic42.core.agent_runtime import AgentRuntimeState


class AdminPage[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class AdminIdentity(BaseModel):
    user_id: UUID
    is_admin: bool


class AdminUserSummary(BaseModel):
    user_id: UUID
    email: str | None
    display_name: str | None
    created_at: datetime
    agents_total: int
    states: dict[AgentRuntimeState, int]


class AdminAgentSummary(BaseModel):
    agent_id: UUID
    name: str
    llm_model: str
    state: AgentRuntimeState


class AdminUserDetail(BaseModel):
    profile: AdminUserSummary
    agents: AdminPage[AdminAgentSummary]


class AdminPresetSummary(BaseModel):
    id: UUID
    owner_id: UUID | None
    owner_name: str | None
    title: str
    summary: str
    sort_order: int
    is_active: bool
    published_at: datetime | None
    updated_at: datetime


class AdminPresetDetail(AdminPresetSummary):
    body: str
    settings: dict[str, Any] | None


class PublicTelegramSettings(BaseModel):
    api_id: int | None
    has_api_hash: bool
    source: Literal["database", "environment", "unconfigured"]
    updated_at: datetime | None
    updated_by: UUID | None


class ActivityCounts(BaseModel):
    messages: int = 0
    actions: int = 0
    errors: int = 0


class DailyActivity(ActivityCounts):
    date: date


class AdminStatistics(BaseModel):
    users: int
    agents: int
    states: dict[AgentRuntimeState, int]
    input_tokens: int
    output_tokens: int
    period_days: Literal[7, 30]
    since: datetime
    until: datetime
    totals: ActivityCounts
    daily: list[DailyActivity]
```

Request-модели находятся в `api/admin.py`, `extra="forbid"`:

| Запрос | Поля |
| --- | --- |
| `POST /admin/presets` | `title` 1–200, `summary` 1–1000, `body` 1–20000, `settings` object/null, `sort_order` PostgreSQL `integer` (-2147483648..2147483647), по умолчанию 0; текстовые обязательные поля не могут состоять из пробелов. |
| `PATCH /admin/presets/{id}` | Непустое подмножество тех же полей; sort_order в диапазоне PostgreSQL `integer`. `null` разрешён только для `settings`; `owner_id`, `slug`, `published_at`, `is_active` запрещены. |
| `PATCH /admin/presets/{id}/visibility` | Только `is_active: bool`. |
| `PUT /admin/telegram-settings` | `api_id: int`, строго положительный и не выше PostgreSQL integer; `api_hash: SecretStr`, непустой после strip, не длиннее 256. |

`GET /me` лежит вне административного router. Все остальные пути из таблицы имеют префикс `/api/v1/admin`. Списки пресетов дополнительно принимают `kind=all|official|published`, по умолчанию `all`. Список агентов пользователя использует те же `page/page_size` в `/users/{user_id}`. `GET /statistics` принимает только `days=7|30`.

## Этап 1. Закрытая схема и безопасная DB-обвязка

**Files:** `supabase/migrations/20261018095739_admin_platform.sql`, `supabase/migrations/20261018101931_restrict_admin_service_role_grants.sql`, `supabase/migrations/20261018132159_admin_audit_action_object_consistency.sql`; `src/mimic42/integrations/database_models.py`; новые `tests/integration/conftest.py`, `tests/integration/test_admin_schema.py`.

- [x] **1.1. Добавить проверку схемы до её появления.** В `test_admin_schema.py` проверить `to_regclass`, RLS и отсутствие любых table/column privileges для `PUBLIC`, `anon` и `authenticated`, а также точный allowlist table/column privileges `service_role` для каждой из трёх таблиц. Для SQL-отказов использовать отдельные savepoint/сессии, а не несколько запросов в уже прерванной транзакции.

```python
import asyncpg
import pytest

from mimic42.testing.slots import plain_dsn


@pytest.mark.parametrize(
    "table_name",
    ["admin_users", "platform_telegram_settings", "admin_audit_log"],
)
async def test_admin_tables_are_closed(test_dsn: str, table_name: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        table = f"public.{table_name}"
        row = await connection.fetchrow(
            "select to_regclass($1) as relation, "
            "(select relrowsecurity from pg_class where oid = to_regclass($1)) as rls_enabled",
            table,
        )
        assert row is not None and row["relation"] is not None
        assert row["rls_enabled"] is True
        version = int(await connection.fetchval("select current_setting('server_version_num')"))
        privileges = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
        if version >= 170000:
            privileges += ("MAINTAIN",)
        for role in ("public", "anon", "authenticated"):
            for privilege in privileges:
                assert not await connection.fetchval(
                    "select has_table_privilege($1, $2, $3)", role, table, privilege
                )
        columns = await connection.fetch(
            "select column_name from information_schema.columns "
            "where table_schema = 'public' and table_name = $1",
            table_name,
        )
        for role in ("public", "anon", "authenticated"):
            for column in columns:
                for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
                    assert not await connection.fetchval(
                        "select has_column_privilege($1, $2, $3, $4)",
                        role, table, column["column_name"], privilege,
                    )
        allowed = {
            "admin_users": {"SELECT", "INSERT", "UPDATE", "DELETE"},
            "platform_telegram_settings": {"SELECT", "INSERT", "UPDATE"},
            "admin_audit_log": {"SELECT", "INSERT"},
        }[table_name]
        for privilege in privileges:
            assert await connection.fetchval(
                "select has_table_privilege('service_role', $1, $2)", table, privilege
            ) is (privilege in allowed)
        for column in columns:
            for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
                assert await connection.fetchval(
                    "select has_column_privilege('service_role', $1, $2, $3)",
                    table, column["column_name"], privilege,
                ) is (privilege in allowed)
    finally:
        await connection.close()
```

- [x] **1.2. Выполнить** `uv run pytest tests/integration/test_admin_schema.py -m db -W error -q`. До миграции ожидается FAIL на отсутствии таблиц, не на подключении к неправильной базе.
- [x] **1.3. Создать миграцию** командой `supabase migration new admin_platform`. Заполнить созданный CLI файл следующим SQL; не добавлять данные аккаунтов или значения credentials.

```sql
create table public.admin_users (
    user_id uuid primary key references public.profiles(id) on delete cascade,
    created_at timestamptz not null default now()
);

create table public.platform_telegram_settings (
    id smallint primary key default 1 check (id = 1),
    api_id integer not null check (api_id > 0),
    api_hash_ciphertext text not null check (btrim(api_hash_ciphertext) <> ''),
    updated_by uuid references public.profiles(id) on delete set null,
    updated_at timestamptz not null default now()
);

create table public.admin_audit_log (
    id uuid primary key default gen_random_uuid(),
    actor_user_id uuid not null,
    action text not null check (action in (
        'preset.created', 'preset.updated', 'preset.visibility_changed',
        'telegram.settings_updated'
    )),
    object_type text not null check (object_type in ('preset', 'telegram_settings')),
    object_id uuid,
    metadata jsonb not null default '{}'::jsonb check (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz not null default now(),
    constraint admin_audit_object_identity check (
        (object_type = 'preset' and object_id is not null)
        or (object_type = 'telegram_settings' and object_id is null)
    )
);

create index platform_telegram_settings_updated_by_idx
    on public.platform_telegram_settings(updated_by);
create index admin_audit_log_actor_created_idx
    on public.admin_audit_log(actor_user_id, created_at desc);

alter table public.admin_users enable row level security;
alter table public.platform_telegram_settings enable row level security;
alter table public.admin_audit_log enable row level security;

revoke all on public.admin_users, public.platform_telegram_settings,
    public.admin_audit_log from public, anon, authenticated;
grant select, insert, update, delete on public.admin_users to service_role;
grant select, insert, update on public.platform_telegram_settings to service_role;
grant select, insert on public.admin_audit_log to service_role;
```

UUID автора аудита намеренно сохраняется без FK: удаление профиля не стирает и не переписывает историю. Клиентские политики для этих таблиц отсутствуют. Сохранённая общая пара не создаётся миграцией, поэтому старый код продолжает работать с env. Supabase может выдавать новые public-таблицы с уже существующими default grants для `service_role`, поэтому их надо отозвать перед точечными grant. Первая миграция этого этапа уже применена в Dev до обнаружения default ACL; её не переписывать. Миграция `20261018101931_restrict_admin_service_role_grants.sql` повторно отзывает права только у `service_role` и задаёт точный allowlist. Ревью также выявило, что базовая проверка identity не связывает action с object_type; миграция `20261018132159_admin_audit_action_object_consistency.sql` закрепляет обе пары действий и объектов отдельным named CHECK constraint, не изменяя применённую миграцию.

- [x] **1.4. Добавить ORM-модели** с теми же колонками и типами; `PromptPresetModel` отображает существующую таблицу, включая `settings`, `owner_id`, `published_at`, `is_active`, `sort_order`. Не вызывать `Base.metadata.create_all()` вместо Supabase-миграций.
- [x] **1.5. Добавить именованную фикстуру для транзакционных тестов** в новом `tests/integration/conftest.py`:

```python
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def admin_db_factory(db_engine, test_slot) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async with db_engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="REPEATABLE READ")
        transaction = await connection.begin()
        try:
            yield async_sessionmaker(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
        finally:
            await transaction.rollback()
```

Она занимает существующий тестовый слот, но ничего не очищает и не меняет глобальную fixture `db_session_factory`. Все операции на её соединении последовательны. Тесты общей настройки, официальных пресетов и глобальных агрегатов используют именно её: внутренние commits репозитория завершают savepoint, а внешний rollback возвращает данные. Отдельная проверка фиксирует запись через session commit и убеждается со второго соединения, что row остался невидим, пока outer transaction не завершена. Персоны берутся из `test_slot`, не из `SLOTS[0]`; новые `auth.users` не создаются.

- [x] **1.6. Проверить адрес связанного Dev-проекта** в `supabase/.temp/project-ref`: только `ipqylrdmmjitemjrygej`. Первый dry-run/push добавил `admin_platform`; затем без переписывания применённых файлов созданы ограничение service_role grants и action/object consistency. После применения `migration list --linked` показывает все три. Schema tests и `supabase db advisors --type security --level warn` прошли. Связанный advisors mode сначала упал при входе временной роли CLI; повтор через `--db-url` после проверки `assert_test_project` обошёл именно этот путь подключения и завершился `No issues found`. Не использовать reset или repair.
- [x] **1.7. Коммит:** `feat(admin): add protected platform settings and audit schema`.

## Этап 2. Проверка роли и подключение подсистемы

**Files:** новые `src/mimic42/core/admin.py`, `src/mimic42/api/admin.py`, `src/mimic42/integrations/database_admin.py`, `tests/api/admin_fakes.py`, `tests/api/test_admin_access.py`; изменить `src/mimic42/api/app.py`, `tests/api/test_app_factories.py`.

- [x] **2.1. Закрепить DTO выше и протокол ниже в `core/admin.py`.** Мутации принимают `actor_user_id` только от серверной зависимости; request-модели API переводятся в эти типы после валидации. `AdminUnavailableError` и `AdminNotFoundError` — отдельные подклассы `Exception` без данных запроса в сообщении.

```python
from typing import Any, Literal, Protocol, TypedDict

from pydantic import BaseModel, SecretStr


class PresetCreateValues(TypedDict):
    title: str
    summary: str
    body: str
    settings: dict[str, Any] | None
    sort_order: int


class PresetPatchValues(TypedDict, total=False):
    title: str
    summary: str
    body: str
    settings: dict[str, Any] | None
    sort_order: int


class StoredTelegramSettings(BaseModel):
    api_id: int
    api_hash_ciphertext: SecretStr
    updated_at: datetime
    updated_by: UUID | None


class AdminRepository(Protocol):
    async def is_admin(self, user_id: UUID) -> bool: ...

    async def list_users(
        self, *, q: str, page: int, page_size: int,
        runtime_states: dict[UUID, AgentRuntimeState],
    ) -> AdminPage[AdminUserSummary]: ...

    async def get_user(
        self, user_id: UUID, *, page: int, page_size: int,
        runtime_states: dict[UUID, AgentRuntimeState],
    ) -> AdminUserDetail: ...

    async def list_presets(
        self, *, q: str, kind: Literal["all", "official", "published"],
        page: int, page_size: int,
    ) -> AdminPage[AdminPresetSummary]: ...

    async def get_preset(self, preset_id: UUID) -> AdminPresetDetail: ...

    async def create_official_preset(
        self, values: PresetCreateValues, *, actor_user_id: UUID,
    ) -> AdminPresetDetail: ...

    async def update_official_preset(
        self, preset_id: UUID, values: PresetPatchValues, *, actor_user_id: UUID,
    ) -> AdminPresetDetail: ...

    async def set_preset_visibility(
        self, preset_id: UUID, is_active: bool, *, actor_user_id: UUID,
    ) -> AdminPresetDetail: ...

    async def read_telegram_settings(self) -> StoredTelegramSettings | None: ...

    async def read_telegram_settings_status(self) -> PublicTelegramSettings | None: ...

    async def save_telegram_settings(
        self, *, api_id: int, api_hash_ciphertext: str, actor_user_id: UUID,
    ) -> PublicTelegramSettings: ...

    async def statistics(
        self, *, days: Literal[7, 30], now: datetime,
        runtime_states: dict[UUID, AgentRuntimeState],
    ) -> AdminStatistics: ...
```

`read_telegram_settings` — исключительно внутренний server-only метод для поставщика; HTTP GET использует `read_telegram_settings_status`, который не выбирает ciphertext. У сохранённой строки `source="database"`; поставщик дополняет статус режимами env/unconfigured при отсутствии строки. Фасад статистики делегирует реализацию `DatabaseAdminStatistics`, не копирует SQL в router.

- [x] **2.2. Написать проверки зависимости на тестовом маршруте**: без токена `401`; с обычным пользователем `403`; со снятой ролью следующий запрос `403`; при ошибке хранилища `503`. На этом этапе реальные предметные маршруты ещё не добавлены, поэтому тест регистрирует свой probe только в экземпляре приложения теста. Подделка `FakeAdminRepository` содержит `admin_ids: set[UUID]` и управляемый флаг `unavailable`; никакой реальной базы. Дополнительно проверить `/me` для обоих значений роли и FastAPI dependency override. В каждом API-этапе 4–7 эту матрицу повторить уже для его настоящих маршрутов.

```python
from typing import Annotated, TYPE_CHECKING, cast
from uuid import uuid4

from fastapi import Depends, Request
from httpx import ASGITransport, AsyncClient

from mimic42.api.admin import require_admin
from mimic42.api.app import create_app
from mimic42.config import Settings
from tests.api.admin_fakes import FakeAdminRepository
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier

if TYPE_CHECKING:
    from mimic42.core.admin import AdminRepository


async def test_admin_role_is_rechecked_for_each_request():
    user_id = uuid4()
    repository = FakeAdminRepository(admin_ids={user_id})
    app = create_app(
        settings=Settings(
            database_connection_string=None, mem0_api_key=None, braintrust_api_key=None,
        ),
        auth_verifier=FakeAuthVerifier(user_id),
        admin_repository=cast("AdminRepository", repository),
    )

    @app.get("/__test__/admin-access", dependencies=[Depends(require_admin)])
    async def admin_access_probe() -> dict[str, bool]:
        return {"allowed": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/__test__/admin-access", headers=AUTH_HEADERS)
        repository.admin_ids.clear()
        second = await client.get("/__test__/admin-access", headers=AUTH_HEADERS)
    assert first.status_code == 200
    assert second.status_code == 403
```

- [x] **2.3. Выполнить** `uv run pytest tests/api/test_admin_access.py -W error -q`. Команда была запущена до и после реализации. **Отклонение от TDD-плана:** начальный отказ произошёл из-за отсутствующих новых модулей/аргумента приложения, поэтому поведенческий red для этих утверждений не подтверждён; после реализации итоговый запуск целевой матрицы прошёл.
- [x] **2.4. Реализовать проверку** `select exists(...)` по PK роли без кеша и зависимость `require_admin`. `/me` использует только `require_user` и возвращает `AdminIdentity`; запрещено превращать ошибку базы в `is_admin=true` или выдавать наружу SQL/DSN. Административный router получает общую зависимость `Depends(require_admin)`; изменение текущей проверки JWT не требуется.

```python
async def require_admin(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(require_user)],
) -> CurrentUser:
    repository = getattr(request.app.state, "admin_repository", None)
    if repository is None:
        raise HTTPException(503, "Администрирование временно недоступно")
    try:
        allowed = await repository.is_admin(current_user.user_id)
    except AdminUnavailableError as exc:
        raise HTTPException(503, "Администрирование временно недоступно") from exc
    if not allowed:
        raise HTTPException(403, "Доступ разрешён только администраторам")
    return current_user
```

`Request`, `HTTPException`, `CurrentUser`, `require_user` импортируются из существующих FastAPI/auth; `AdminUnavailableError` — новая предметная ошибка в `core/admin.py`. Не возвращать `str(exc)` пользователю.

- [x] **2.5. Обновить сборку приложения.** Добавить keyword-only `admin_repository: AdminRepository | None = None`. Разделить причину открытия engine и причину сборки агентских сервисов:

```python
build_agent_services = bool(app_settings.database_connection_string) and (
    onboarding_service is None or agent_store is None
)
build_admin_repository = bool(app_settings.database_connection_string) and (
    admin_repository is None
)
build_database = build_agent_services or build_admin_repository
```

Engine/session factory создаются один раз при `build_database`; существующая сборка store/onboarding/manager, восстановление рантаймов и запуск warmup остаются под прежним `build_agent_services`, а не под новым расширенным условием. Иначе создание только админского репозитория неожиданно восстановит чужих агентов в тесте с инъецированными сервисами. Инъецированные объекты не заменяются; приложению принадлежит закрытие созданного здесь engine, а существующее завершение менеджера сохраняется. Без базы обычные fake-сценарии и `/health` работают, админка отвечает `503`.

- [x] **2.6. Добавить проверки lifespan:** все три сервиса инъецированы — engine не создаётся; инъецированы store/onboarding, но не admin repository — собирается только admin repository, без восстановления агентов или warmup; один созданный engine закрывается ровно один раз. Повторить `uv run pytest tests/api/test_admin_access.py tests/api/test_app_factories.py tests/api/test_auth_api.py -W error -q` — после review fixes 24 passed.
- [x] **2.7. Коммит:** `feat(admin): enforce database-backed administrator access`.

## Этап 3. Модерация на уровне базы

**Files:** `supabase/migrations/20261018145306_preset_moderation.sql`, `supabase/migrations/20261018163931_preset_lock_policy.sql`, `supabase/migrations/20261018174711_agent_messages_admin_activity_index.sql`, `supabase/migrations/20261018174739_agent_events_admin_activity_index.sql`; новый `tests/integration/test_preset_moderation.py`; изменить `tests/integration/test_prompt_presets.py`, чтобы persona-based DB-тесты арендовали `test_slot`.

- [x] **3.1. Написать DB-сценарии** с персоны текущего `test_slot`, с rollback тестовых данных: видимый опубликованный пресет, скрытый опубликованный, приватный, официальный. Все UUID тестовых пресетов генерируются отдельно; существующие записи персон не удаляются.
- [x] **3.2. Проверить:** чужой скрытый недоступен; автор видит его; автор не меняет `is_active`; повторная публикация не открывает каталог; добавление скрытого в избранное запрещено; скрытие замораживает старое избранное без потери `frozen_*`; unhide не оживляет снимок; автор скрытого не попадает в `preset_authors`, если других активных публикаций нет. В двухсоединительном сценарии конкурентного добавления избранного и скрытия не остаётся живая ссылка на скрытый пресет. Выполнить `uv run pytest tests/integration/test_preset_moderation.py tests/integration/test_prompt_presets.py -m db -W error -q`.
- [x] **3.3. Создать** `supabase migration new preset_moderation` и записать первоначальную модерацию (уже применённую миграцию не переписывать):

```sql
drop policy "Authenticated users can read catalog presets" on public.prompt_presets;
create policy "Authenticated users can read catalog presets"
    on public.prompt_presets for select to authenticated
    using (
        owner_id = (select auth.uid())
        or (is_active and (owner_id is null or published_at is not null))
    );

drop policy "Authenticated users can update own presets" on public.prompt_presets;
create policy "Authenticated users can update own and lock published presets"
    on public.prompt_presets
    for update to authenticated
    using (
        owner_id = (select auth.uid())
        or (
            owner_id is not null
            and is_active
            and published_at is not null
            and owner_id <> (select auth.uid())
        )
    )
    with check (owner_id = (select auth.uid()));

drop policy "Users can favorite published presets of others" on public.preset_favorites;
create policy "Users can favorite published presets of others"
    on public.preset_favorites for insert to authenticated
    with check (
        owner_id = (select auth.uid())
        and exists (
            select 1 from public.prompt_presets pp
            where pp.id = preset_id
              and pp.is_active
              and pp.published_at is not null
              and pp.owner_id <> (select auth.uid())
        )
    );

create trigger prompt_presets_freeze_on_hide
    before update of is_active on public.prompt_presets
    for each row
    when (old.is_active and not new.is_active and old.owner_id is not null)
    execute function public.freeze_preset_favorites();

create or replace function public.set_favorite_owner() returns trigger
language plpgsql security invoker set search_path = ''
as $$
begin
    new.owner_id = auth.uid();
    perform 1
    from public.prompt_presets pp
    where pp.id = new.preset_id
      and pp.is_active
      and pp.published_at is not null
      and pp.owner_id <> new.owner_id
    for share;
    if not found then
        raise exception using
            errcode = '42501',
            message = 'Пресет недоступен для добавления в избранное';
    end if;
    return new;
end;
$$;

create or replace view public.preset_authors as
select distinct pp.owner_id as id, pr.display_name
from public.prompt_presets pp
join public.profiles pr on pr.id = pp.owner_id
where pp.published_at is not null and pp.is_active;

revoke all on public.preset_authors from public, anon;
grant select on public.preset_authors to authenticated;

```

Представление авторов сознательно оставляет прежнюю узкую серверную проекцию только `id/display_name`; `security_invoker=true` здесь лишит магазин имён из-за RLS профилей. Не добавлять email. Column grant автора на `is_active` не ослаблять. Документация PostgreSQL подтверждает, что `SELECT ... FOR SHARE` проходит UPDATE `USING`-политику. В финальном source migration initial update policy уже включает row-lock predicate, поэтому в проде нет временного отказа избранного. В Dev предыдущие редакции уже применены; пользователь разрешил корректировать эти feature-branch файлы перед production, не переприменяя их в Dev.

```sql
drop policy if exists "Authenticated users can update own presets" on public.prompt_presets;
drop policy if exists "Authenticated users can update own and lock published presets"
    on public.prompt_presets;
create policy "Authenticated users can update own and lock published presets"
    on public.prompt_presets
    for update
    to authenticated
    using (
        owner_id = (select auth.uid())
        or (
            owner_id is not null
            and is_active
            and published_at is not null
            and owner_id <> (select auth.uid())
        )
    )
    with check (owner_id = (select auth.uid()));
```

Ограниченные column grants остаются прежними, `is_active` клиенту не выдан. `USING` разрешает RLS видеть активную чужую публикацию для получения row lock; `WITH CHECK` допускает сохранять изменения только владельцу. Интеграционный тест подтверждает, что чужой текст не меняется. Это сохраняет invoker-trigger без публичных SECURITY DEFINER helpers и без новых GRANT-ов клиенту. `FOR SHARE` и UPDATE сериализуются: favorite, начавшийся первым, замораживается последующим hide; если первым завершилось скрытие, favorite не найдёт активную строку.

Индексы на активных `agent_messages` и `agent_events` строить concurrently: обычный `CREATE INDEX` блокирует запись на время построения. Supabase CLI исполняет одиночный `CREATE INDEX CONCURRENTLY` вне транзакции (локальный образец — `20261001175020_media_messages_lookup_index.sql`), поэтому каждый индекс находится в отдельном однооператорном migration-файле:

```sql
-- 20261018174711_agent_messages_admin_activity_index.sql
create index concurrently if not exists agent_messages_admin_activity_date_idx
    on public.agent_messages(created_at)
    where direction in ('incoming', 'agent_response');

-- 20261018174739_agent_events_admin_activity_index.sql
create index concurrently if not exists agent_events_admin_activity_date_idx
    on public.agent_events(created_at)
    where event_type like 'tool.%' or status = 'failed';
```

В Dev индексы уже существуют после предыдущей редакции stage-3 миграции; отдельные файлы фиксируют migration history и пропускают перестройку через `IF NOT EXISTS`.

Если `CREATE INDEX CONCURRENTLY` завершится ошибкой, не повторять миграцию вслепую: PostgreSQL может оставить невалидный объект с тем же именем, который `IF NOT EXISTS` пропустит. Сначала проверь `pg_index.indisvalid` для точного индекса и таблицы; исправлять/удалять только подтверждённый невалидный объект этой миграции, затем перепроверить Dev и историю.

- [x] **3.4. Проверить Dev-адрес, dry-run и применить** stage-3 migration, lock-policy migration и обе concurrent index migrations. Dry-run каждого файла показывал ровно ожидаемые миграции; Dev пропустил существующие индексы; history list содержит семь feature-миграций в сумме (3 admin schema/ACL, 2 moderation, 2 indexes). Целевая команда `uv run pytest tests/integration/test_preset_moderation.py tests/integration/test_prompt_presets.py -m db -W error -q` — 21 passed; security advisor сообщил `No issues found`. Старые четыре официальных пресета остаются клиенту read-only.
- [x] **3.5. Коммит:** `feat(presets): enforce administrative hiding and favorite snapshots`.

## Этап 4. Административные операции пресетов и аудит

**Files:** `src/mimic42/core/admin.py`, `src/mimic42/api/admin.py`, `src/mimic42/integrations/database_admin.py`; новые `tests/api/test_admin_presets.py`, `tests/integration/test_admin_presets.py`.

- [x] **4.1. Написать проверки API:** `GET` списка не содержит тела промптов; detail возвращает тело только официального/опубликованного; приватный по UUID даёт `404`; изменение чужого пользовательского тела запрещено; неизвестное поле запроса, пустой PATCH, sort_order вне PostgreSQL integer, page вне 1..1_000_000 и ошибочные размеры страниц дают `422`; пределы текстов соблюдены.
- [x] **4.2. Написать DB-проверки:** создание официального генерирует уникальный `official_<uuidhex>`; sort-order PATCH сохраняет остальные поля; visibility затрагивает только указанный UUID; изменение официального и аудит фиксируются вместе. В тесте сбоя аудита временно через monkeypatch заставить приватный `_append_audit` репозитория выбросить `AdminUnavailableError`, после операции убедиться, что строка и избранное не изменились. Функция `_append_audit(session, actor_user_id, action, object_id, metadata)` ничего сама не коммитит.
- [x] **4.3. Выполнить две отдельные команды**, потому что `pyproject.toml` по умолчанию исключает `db`-тесты:

```bash
uv run pytest tests/api/test_admin_presets.py -m "not db" -W error -q
uv run pytest tests/integration/test_admin_presets.py -m db -W error -q
```
Итоговый результат: API — 19 passed, integration/DB — 5 passed. Ранний combined run без `-m db` выполнил только API-слой и deselected integration-тесты; он не считается проверкой DB.
- [x] **4.4. Реализовать репозиторий.** На чтении и на мутации использовать SQL-предикат `owner_id is null or published_at is not null`. На update предварительно заблокировать допустимую строку через `SELECT ... FOR UPDATE`; при отсутствии — `AdminNotFoundError`. Для редактирования официальных дополнительно `owner_id is null`. Это сериализует изменение с авторским снятием публикации, не открывая приватные строки.

```python
async def set_preset_visibility(self, preset_id: UUID, is_active: bool, *, actor_user_id: UUID):
    async with self._session_factory() as session, session.begin():
        preset = await session.scalar(
            select(PromptPresetModel)
            .where(
                PromptPresetModel.id == preset_id,
                or_(
                    PromptPresetModel.owner_id.is_(None),
                    PromptPresetModel.published_at.is_not(None),
                ),
            )
            .with_for_update()
        )
        if preset is None:
            raise AdminNotFoundError
        old_value = preset.is_active
        if old_value != is_active:
            preset.is_active = is_active
            await session.flush()
            await self._append_audit(
                session,
                actor_user_id=actor_user_id,
                action="preset.visibility_changed",
                object_id=preset_id,
                metadata={"before": old_value, "after": is_active},
            )
        await session.refresh(preset)
        result = self._preset_detail(preset)
    return result
```

`select/or_`, модель и предметная ошибка определены выше; `_preset_detail` формирует только `AdminPresetDetail`, а не сериализует ORM целиком. Для owner_name сделать отдельный ограниченный join/projection. Повторное выставление той же видимости — безопасный no-op без новой записи аудита. `preset.created/updated` записывают UUID и имена изменённых полей, но не их текстовые значения. SQLAlchemy-ошибки переводятся в безопасную `AdminUnavailableError` после rollback.

- [x] **4.5. Подключить маршруты из контракта.** `POST` возвращает `201` и detail, PATCH — detail. `settings` передаётся JSON-объектом/null без потери неизвестных сохранённых ключей. Все mutations получают автора из `require_admin`, а не из body. Роль продолжает проверяться при каждом запросе.
- [x] **4.6. Повторить API/DB-команды 4.3**, добавить двухсоединительный сценарий «автор снял публикацию до блокировки административной операции → `404`». Для race tests используются два соединения от `db_engine`; commits ограничены собственными UUID внутри тестового слота, cleanup удаляет конкретные audit/favorite/preset IDs и закрывает соединения даже при частичном старте. Общая Telegram-настройка и существующие официальные строки не меняются.
- [x] **4.7. Коммит:** `feat(admin): manage official presets and moderate published presets`.

## Этап 5. Telegram defaults: шифрование, безопасный API и новые подключения

**Files:** новый `src/mimic42/core/telegram_app_settings.py`; `src/mimic42/api/admin.py`, `src/mimic42/api/app.py`, `src/mimic42/integrations/database_admin.py`; новые `tests/core/test_telegram_app_settings.py`, `tests/api/test_admin_telegram.py`, `tests/integration/test_admin_telegram.py`; дополнить `tests/api/test_onboarding_api.py`.

- [x] **5.1. Написать проверки поставщика:** нет строки → env; строка есть → сохранённая пара; ошибка чтения/расшифровки → отказ без fallback; полная явно переданная пара не нуждается в чтении defaults; частичное переопределение сохраняет существующий контракт `_resolve_telegram_app`; после записи следующий вход получает новую пару без рестарта.
- [x] **5.2. Написать проверки API:** GET никогда не возвращает plaintext/ciphertext; без `SECRET_KEY` PUT даёт `503` и ничего не пишет; неверный `api_id` при валидном HASH даёт `422` без HASH в ответе; неверный JSON и лишние поля тоже не отражают body. Проверить `repr` DTO и captured logs.
- [x] **5.3. Написать DB-проверки на `admin_db_factory`:** HASH расшифровывается исходным тестовым ключом, upsert проверяет вставку и замену, строка id=1 единственна, пара и аудит атомарны. До теста не удалять реальную глобальную строку; её обновление существует только во внешней транзакции с rollback. Команды разделены: настройки проекта по умолчанию исключают `db`-тесты.

```bash
uv run pytest tests/core/test_telegram_app_settings.py tests/api/test_admin_telegram.py -m "not db" -W error -q
uv run pytest tests/integration/test_admin_telegram.py -m db -W error -q
```

- [x] **5.4. Реализовать server-only значение пары** как dataclass с `api_hash: SecretStr`, не используемую в HTTP-ответе. Класс `TelegramAppSettings` получает keyword-only `settings: Settings`, `repository: AdminRepository | None`, `cipher: FernetSecretCipher | None`. Его методы: `resolve(api_id: int | None, api_hash: str | None) -> tuple[int, str]`, `status() -> PublicTelegramSettings`, `save(*, api_id: int, api_hash: SecretStr, actor_user_id: UUID) -> PublicTelegramSettings`, все async. При отсутствии repository сохраняется env-only режим, а не попытка соединения. При настроенной базе ошибка её чтения не считается отсутствием строки.

```python
async def resolve(self, api_id: int | None, api_hash: str | None) -> tuple[int, str]:
    if api_id is not None and api_hash is not None:
        return api_id, api_hash
    defaults = await self._read_defaults()
    resolved_id = api_id if api_id is not None else defaults.api_id
    resolved_hash = SecretStr(api_hash) if api_hash is not None else defaults.api_hash
    if resolved_id is None or resolved_hash is None:
        raise TelegramAppUnavailableError("Telegram-приложение не настроено")
    return resolved_id, resolved_hash.get_secret_value()
```

`_read_defaults()` возвращает внутренний `TelegramAppDefaults(api_id: int | None, api_hash: SecretStr | None)`; при строке из базы расшифровывает её, иначе берёт env. `TelegramAppUnavailableError` определён в том же модуле. Не обновлять объекты `Settings` или глобальную пару в памяти.

- [x] **5.5. Реализовать PUT** через PostgreSQL upsert по singleton PK `id=1` в одной транзакции с `telegram.settings_updated`; хранить только ciphertext. `updated_at` выставлять явно в `ON CONFLICT DO UPDATE`, `updated_by` — UUID зависимости. Метаданные аудита: только `{"credentials_replaced": true}`. GET строить отдельным SELECT публичных колонок плюс признак наличия HASH, без расшифровки для отображения формы.
- [x] **5.6. Ограничить очистку ошибок административным router.** Для него использовать `APIRoute.get_route_handler()` и перехват `RequestValidationError`; не копировать пример документации, который логирует тело:

```python
class AdminRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request: Request) -> Response:
            try:
                response = await handler(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=422,
                    content={"detail": "Проверьте поля запроса"},
                    headers={"Cache-Control": "no-store"},
                )
            except StarletteHTTPException as exc:
                response = await http_exception_handler(request, exc)
            response.headers["Cache-Control"] = "no-store"
            return response

        return safe_handler
```

Использовать `APIRouter(route_class=AdminRoute, ...)`; дополнительно отдавать `Cache-Control: no-store` у `/me`. Не менять формат `422` остальных API. Ни captured exception body, ни `SecretStr.get_secret_value()` не уходят в лог.

- [x] **5.7. Заменить оба вызова `_resolve_telegram_app`** в `request_telegram_code` и прямом `create_agent` на async-поставщика; добавить в `create_app` keyword-only `telegram_app_settings: TelegramAppSettings | None = None` для unit-тестов. В `core/onboarding.py`, `telegram_sessions`, перепривязке и загрузчике рантайма сохранённые credentials не меняются. Проверено: начатая onboarding-сессия подтверждает код со старой парой, а новое создание использует обновлённую.
- [x] **5.8. Повторить точечные проверки** этапа плюс `tests/api/test_onboarding_api.py`, `tests/api/test_agents_api.py`; сравнить через fake factory полученные пары до/после смены, без реального подключения к Telegram. Результат: unit/API — 77 passed; integration DB вместе с тестами preset repository — 7 passed; Ruff, форматирование и ty прошли.

```bash
uv run pytest tests/core/test_telegram_app_settings.py tests/api/test_admin_telegram.py tests/api/test_admin_access.py tests/api/test_admin_presets.py tests/api/test_onboarding_api.py tests/api/test_agents_api.py -W error -q
uv run pytest tests/integration/test_admin_telegram.py tests/integration/test_admin_presets.py -m db -W error -q
```
- [x] **5.9. Коммит:** `feat(admin): update encrypted Telegram defaults without restarting agents`.

## Этап 6. Пользователи и эффективные состояния

**Files:** новый `src/mimic42/core/runtime_status.py`; `src/mimic42/api/app.py`, `src/mimic42/integrations/database_admin.py`, `src/mimic42/integrations/database_admin_statistics.py`; новые `tests/core/test_runtime_status.py`, `tests/api/test_admin_users.py`, `tests/integration/test_admin_users.py`.

- [x] **6.1. Сначала проверить извлекаемое правило:** сохранённые `starting/running/stopping` без runtime превращаются в `stopped`; `error/stopped` сохраняются; неизвестное для `AgentRuntimeState` значение `draft` также превращается в `stopped`, как в существующем `_agent_record`; существующий runtime имеет приоритет. Результат обычного `/agents` до/после извлечения не меняется.

```python
def effective_runtime_state(
    saved: AgentRuntimeState | str,
    actual: AgentRuntimeState | None,
) -> AgentRuntimeState:
    if actual is not None:
        return actual
    try:
        saved_state = AgentRuntimeState(saved)
    except ValueError:
        return AgentRuntimeState.STOPPED
    if saved_state in {
        AgentRuntimeState.STARTING,
        AgentRuntimeState.RUNNING,
        AgentRuntimeState.STOPPING,
    }:
        return AgentRuntimeState.STOPPED
    return saved_state
```

- [x] **6.2. Написать API/DB-проверки:** пустой профиль включён; поиск регистронезависим; `%` и `_` в q означают буквальные символы; страницы не теряют строки с одинаковой датой создания; неизвестный user_id — `404`; ответ не содержит `soul_prompt/settings/session`; модель берётся из `settings.llm_model` или реального `DEFAULT_LLM_MODEL`, а не из устаревшего `openrouter/free`.
- [x] **6.3. Выполнить точечные проверки** отдельными командами, поскольку `pyproject.toml` по умолчанию исключает `db`-тесты:

```bash
uv run pytest tests/core/test_runtime_status.py tests/api/test_admin_users.py tests/api/test_admin_access.py tests/api/test_admin_presets.py tests/api/test_admin_telegram.py tests/api/test_agents_api.py tests/api/test_onboarding_api.py -W error -q
uv run pytest tests/integration/test_admin_users.py tests/integration/test_admin_presets.py tests/integration/test_admin_telegram.py -m db -W error -q
```

Результат: unit/API — 82 passed; integration DB — 8 passed.
- [x] **6.4. Реализовать групповое согласование состояний в SQL.** Router получает один snapshot `manager.list_agents()` и передаёт только UUID/state репозиторию. Не читать всех агентов/настройки в Python ради подсчётов. В `database_admin_statistics.py` выделено построение CTE эффективных агентов; параметры — два равных по длине массива UUID/state. Пустые массивы корректно дают пустую runtime-таблицу.

```sql
with runtime as (
    select * from unnest(cast(:runtime_ids as uuid[]), cast(:runtime_states as text[]))
        as r(agent_id, state)
), effective_agents as (
    select a.id, a.owner_id, a.name, a.settings, a.created_at,
        coalesce(r.state, case
            when a.status in ('draft', 'starting', 'running', 'stopping') then 'stopped'
            else a.status::text
        end) as state
    from public.agents a
    left join runtime r on r.agent_id = a.id
)
select owner_id, state, count(*) as count
from effective_agents
group by owner_id, state;
```

Для списка сначала выбирать нужную страницу профилей и считать агентов только этих owner_ids, затем объединять агрегаты с профилями, включая нули. Профили сортировать `created_at desc, id desc`, агентов — так же. Не JOIN-ить сообщения/события к профилям. `.ilike(..., escape=...)` либо `icontains(q, autoescape=True)` должны экранировать wildcard; SQL-параметры не интерполируются.

- [x] **6.5. Подключить** `GET /users` и `GET /users/{user_id}` с явными DTO и общей проверкой роли. Не давать ссылки на чужой `/agent/{id}` как будто администратор может им управлять. Обычный `/agents` использует то же чистое правило эффективного состояния.
- [x] **6.6. Коммит:** `feat(admin): list users with runtime-aware agent summaries`.

## Этап 7. Серверные агрегаты статистики

**Files:** `src/mimic42/core/admin.py`, `src/mimic42/integrations/database_admin_statistics.py`, `src/mimic42/integrations/database_admin.py`, `src/mimic42/api/admin.py`; новые `tests/core/test_admin_statistics.py`, `tests/api/test_admin_statistics.py`, `tests/integration/test_admin_statistics.py`.

- [x] **7.1. Проверить чистое вычисление UTC-окна** с инъекцией `now`, включая входной datetime с другим часовым поясом. Начало — полночь UTC 6/29 дней назад, верхняя граница — переданный `now`, полузакрытый диапазон `[since, until)`. DTO и UI называют текущий день неполным.

```python
from datetime import UTC, datetime, timedelta


def statistics_window(days: int, now: datetime) -> tuple[datetime, datetime]:
    if now.tzinfo is None:
        raise ValueError("Статистике требуется время с часовым поясом")
    utc_now = now.astimezone(UTC)
    start = utc_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start - timedelta(days=days - 1), utc_now


def test_statistics_window_uses_calendar_days_in_utc():
    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    start, end = statistics_window(7, now)
    assert start == datetime(2026, 10, 12, tzinfo=UTC)
    assert end == now
```

- [x] **7.2. Написать DB-тест на базовый snapshot и дельту.** Общая Dev-база не пуста: получить статистику в одной `REPEATABLE READ` транзакции до создания собственных фикстур, затем после. Добавить два агента, 2 входящих, 1 agent_response, 1 tool_call-сообщение, успешный tool-event, неуспешный tool-event и отдельный model.failed; ожидаемая дельта — messages=3, actions=2, errors=2. Дневные числа в сумме равны totals; счётчик токенов 100/30 не удваивается от JOIN; переключение 7→30 не меняет токены. Все записи фикстур откатываются внешней транзакцией.
- [x] **7.3. Выполнить проверки** отдельными командами, потому что `pyproject.toml` по умолчанию исключает `db`-тесты:

```bash
uv run pytest tests/core/test_admin_statistics.py tests/api/test_admin_statistics.py -W error -q
uv run pytest tests/integration/test_admin_statistics.py -m db -W error -q
```

Результат: core/API — 9 passed, DB integration — 1 passed.
- [x] **7.4. Реализовать независимые агрегаты:** профили count, эффективные состояния из CTE этапа 6, `coalesce(sum(input_tokens),0)` и output отдельно, дневные counts сообщений и событий. Один SELECT с независимыми агрегатами и day rows обеспечивает согласованный snapshot; `AsyncSession` параллельно не используется. Строковые данные сообщений, событий, настроек и сессий не передаются в ответ.

```sql
select (created_at at time zone 'UTC')::date as date, count(*) as messages
from public.agent_messages
where created_at >= :since and created_at < :until
  and direction in ('incoming', 'agent_response')
group by 1 order by 1;

select (created_at at time zone 'UTC')::date as date,
    count(*) filter (where event_type like 'tool.%') as actions,
    count(*) filter (where status = 'failed') as errors
from public.agent_events
where created_at >= :since and created_at < :until
  and (event_type like 'tool.%' or status = 'failed')
group by 1 order by 1;
```

Заполнить 7/30 календарных дней нулями в Python; totals вычислить суммой этих же рядов, исключив расхождение формул. Каст даты только в SELECT/GROUP BY, диапазон фильтруется непосредственно по indexed `created_at`. Ограничить выборку `until`, не включать будущие строки.

- [x] **7.5. Добавить API-маршрут**, `days` вне 7/30 даёт `422`, ошибка SQL не превращается в успешный ответ с нулями. Проверить удаление своего fixture-агента внутри откатываемой транзакции: счётчики уменьшаются согласно каскадам. На данных Dev выполнен `EXPLAIN` без `ANALYZE` и без выборки payload/content: временные агрегаты используют `agent_messages_admin_activity_date_idx` (Index Only Scan) и `agent_events_admin_activity_date_idx` (Index Scan).
- [x] **7.6. Повторить проверки 7.3. Коммит:** `feat(admin): aggregate platform activity and lifetime token usage`.

## Этап 8. Клиентский транспорт, роль и безопасный кеш

**Files:** новые `frontend/src/types/admin.ts`, `frontend/src/lib/adminApi.ts`, `frontend/src/hooks/useAdminAccess.ts`, `frontend/src/hooks/useAdmin.ts`; изменить `frontend/src/lib/queryClient.ts`, `frontend/src/app/providers.tsx`; новые `frontend/src/__tests__/admin-access.test.tsx`, `frontend/src/__tests__/admin-api.test.ts`.

- [x] **8.1. Перенести DTO в TypeScript** без переименования полей; `AdminPage<T>` и `AdminStatistics` совпадают с Python. У `PublicTelegramSettings` нет `api_hash`/ciphertext. Клиентский `SaveTelegramSettings` существует только как аргумент прямого вызова формы.
- [x] **8.2. Написать проверки:** общий Axios прикладывает существующий JWT; read-запрос получает AbortSignal; административные query не запускаются до роли; `403` не повторяется retry; после отзыва роли/выхода старые users/preset detail исчезают. Ключи двух UUID не совпадают. Для HTTP используется adapter существующего `apiClient`, не отдельный unauthenticated клиент.
- [x] **8.3. Выполнить** из `frontend/`: `bun test src/__tests__/admin-api.test.ts src/__tests__/admin-access.test.tsx`.
- [x] **8.4. Добавить транспорт и query-ключи.** Все read helpers принимают `signal?: AbortSignal`, передают `signal` в Axios и возвращают только `r.data`. Реализованы `me`, `users`, `user`, `presets`, `preset`, `createPreset`, `updatePreset`, `setPresetVisibility`, `telegramSettings`, `saveTelegramSettings`, `statistics`. Административные writes — прямые async-вызовы, без `useMutation`; тело и HASH не попадают в mutation cache.

```typescript
const adminKeys = {
  all: ['admin'] as const,
  identity: (userId: string) => ['identity', userId] as const,
  scope: (userId: string) => ['admin', userId] as const,
  users: (userId: string, q: string, page: number) =>
    ['admin', userId, 'users', { q, page }] as const,
  user: (userId: string, targetId: string, page: number) =>
    ['admin', userId, 'user', targetId, page] as const,
  presets: (userId: string, q: string, kind: string, page: number) =>
    ['admin', userId, 'presets', { q, kind, page }] as const,
  preset: (userId: string, presetId: string) =>
    ['admin', userId, 'preset', presetId] as const,
  telegram: (userId: string) => ['admin', userId, 'telegram'] as const,
  statistics: (userId: string, days: 7 | 30) =>
    ['admin', userId, 'statistics', days] as const,
};
```

Добавить как `queryKeys.admin`, не дублировать отдельный набор в компонентах. `useAdminAccess` узнаёт текущего пользователя через существующий Supabase auth, слушает `onAuthStateChange` и вызывает `/me` с `staleTime: 0`, `refetchInterval: 30_000`, refetch при focus/reconnect. Обычная ошибка роли не блокирует Sidebar собственных агентов; административная граница не показывает защищённое содержимое на ошибке перепроверки.

- [x] **8.5. При отзыве/выходе сначала закрыть UI и запретить новые запросы**, затем отменить и удалить административные queries. Отменённые read-запросы потребляют signal. Глобальный `AdminAccessProvider` слушает Supabase auth events, удаляет данные прежнего UUID и не даёт старой identity/cache открывать административные экраны. Поздние callbacks write-запросов не меняют QueryClient или identity; отправленную серверную операцию отменённой не считаем.

```typescript
async function clearAdminData(client: QueryClient): Promise<void> {
  await client.cancelQueries({ queryKey: queryKeys.admin.all });
  client.removeQueries({ queryKey: queryKeys.admin.all });
}
```

При `403` любого административного запроса или мутации обновить identity до `is_admin:false` и выполнить тот же сброс. При выходе/смене UUID очищать и прежний identity; не очищать только `['admin', newUserId]`, оставляя данные старого. Helper использует существующий `QueryClient` и `queryKeys`, располагается в `hooks/useAdminAccess.ts` и переиспользуется hooks, не копируется по компонентам.

- [x] **8.6. Для read-запросов выставить `enabled` только при подтверждённой роли**, без retry на `401/403`, максимум один retry сетевой/`503` ошибки. Async-действия проверяют роль перед вызовом, не используют мутационный кеш. Пресетные действия инвалидируют `queryKeys.admin.scope(userId)` и `queryKeys.presets.all` только пока вызывающий пользователь не сменился; смена роли сбрасывает admin queries. HASH не используется в query keys, mutation variables, local/sessionStorage, console или devtools.
- [x] **8.7. Повторить команду 8.3. Результат:** 8 passed; `bun run typecheck` прошёл. Коммит: `feat(admin): add identity-scoped client queries and access revocation`.

## Этап 9. Оболочка, примитивы и вход без собственного мимика

**Files:** новые `frontend/src/components/admin/AdminBoundary.tsx`, `frontend/src/components/admin/AdminNavigation.tsx`, `frontend/src/components/admin/AdminPagination.tsx`, `frontend/src/app/(dashboard)/admin/layout.tsx`; изменить `frontend/src/components/layout/Sidebar.tsx`, `frontend/src/middleware.ts`; новые `frontend/src/__tests__/admin-boundary.test.tsx`, `frontend/src/__tests__/admin-navigation.test.tsx`, `frontend/src/__tests__/admin-middleware.test.ts`. Содержательные page-маршруты создаются вместе со своими экранами в этапах 10–13, без промежуточных заглушек и импортов ещё не существующих компонентов.

- [x] **9.1. До UI-правок загрузить craft-floor по Impeccable** и проверить наличие brief для `/admin`. Brief отсутствовал; сохранён `.impeccable/surfaces/frontend-src-app-dashboard-admin-layout-tsx.md`: Operate, текущее оформление, четыре подраздела, без нового визуального мира. `DESIGN.md`, `PRODUCT.md` и Three.js-декор не менялись.
- [x] **9.2. Просмотреть установленные компоненты** и выполнить dry-run `bunx --bun shadcn@latest add @shadcn/field @shadcn/empty @shadcn/table @shadcn/pagination @shadcn/toggle-group --dry-run`. Добавлены только отсутствующие примитивы и их Label/Separator/Toggle зависимости; при установке Pagination отказано в перезаписи существующего `button.tsx`. Для компонентов добавлен официальный `radix-ui`, импорт `cn` направлен в существующий `@/lib/utils`, несовместимые Tailwind 4 классы заменены на Tailwind 3.4; API локальной кнопки не менялся.
- [x] **9.3. Написать проверки границы и middleware:** children не монтируются при loading/denied/error; доступ к `/admin` не зависит от наличия собственного агента, но остаётся за Supabase auth и `AdminBoundary`; обычный пользователь получает отказ через границу; `/administrator` не считается дочерним `/admin`; обычный `/dashboard` сохраняет прежний redirect.

```typescript
const isAdminPath = pathname === '/admin' || pathname.startsWith('/admin/');

if (!isAdminPath && !pathname.startsWith('/onboarding') && !isPublicPath) {
  const { data: agents, error: agentsError } = await supabase
    .from('agents')
    .select('id')
    .eq('owner_id', user.id)
    .limit(1);
  if (!agentsError && (!agents || agents.length === 0)) {
    return NextResponse.redirect(new URL('/onboarding', origin));
  }
}
```

Это исключение только из проверки наличия агента, не из аутентификации. Административная роль остаётся ответственностью API и `AdminBoundary`.

- [x] **9.4. Выполнить** `bun test src/__tests__/admin-boundary.test.tsx src/__tests__/admin-navigation.test.tsx src/__tests__/admin-middleware.test.ts`: 12 passed. Совместно с клиентскими регрессионными тестами этапа 8: 20 passed; `bun run typecheck` прошёл.
- [x] **9.5. Реализовать границу:** loading → `Skeleton`; ошибка → `Alert` с «Повторить»; denied → «Нет доступа» и ссылка к собственным агентам; allowed → дочерние страницы. AdminNavigation — ссылки на `/admin`, `/admin/users`, `/admin/presets`, `/admin/telegram` с `aria-current="page"`; для `/admin` используется exact-match. Маршруты сохраняются как deep links.
- [x] **9.6. Реализовать AdminPagination** поверх установленной Pagination: русские подписи и aria-label, текущая страница/total, недоступные переходы disabled и не попадают в tab-порядок. Смена поиска создаёт отдельный query key без сохранения предыдущих результатов. Sidebar показывает один пункт только после успешного `/me`, без дублирующей JWT-проверки.
- [x] **9.7. Повторить команду 9.4.** `impeccable detect --json` по изменённым интерфейсным целям вернул пустой список. Коммит: `feat(admin): add protected dashboard navigation and responsive shell`. Визуальная проверка полного `/admin` отложена до этапов с содержимым страниц: этот этап намеренно не добавляет заглушки.

## Этап 10. Экран пользователей

**Files:** `frontend/src/components/admin/AdminUsers.tsx`, `frontend/src/app/(dashboard)/admin/users/page.tsx`; новый `frontend/src/__tests__/admin-users.test.tsx`.

- [x] **10.1. Написать компонентные проверки:** профиль без агента, пустое имя/email, поиск со сбросом страницы, ошибка с повтором, открытие деталей, отдельная пагинация агентов. Проверены отсутствие start/stop/delete-кнопок, чужих настроек и ссылки на управление агентом.
- [x] **10.2. Выполнить** `bun test src/__tests__/admin-users.test.tsx`: 4 passed.
- [x] **10.3. Реализовать список** через `useAdmin` и Table: пользователь, email, дата регистрации, мимики и распределение состояний; строки имеют явную кнопку «Мимики». Таблица скроллится только в своём контейнере, длинные email и имена переносятся. Поиск ограничен 200 символами, debounce — 300 мс; q/page читаются из URL и сохраняются при поиске и пагинации.
- [x] **10.4. Детали пользователя показывать в существующем Modal**: профиль, отдельная пагинация мимиков, name/model/state и `AgentStatusBadge`. Вложенного modal нет. Для отсутствующих имени/email — «Без имени»/«Не указан». Пустой профиль и обе ошибки имеют отдельные состояния; ошибка не показывается как нулевой список.

```tsx
<TableCell>
  <Button variant="ghost" size="sm" onClick={() => setSelectedUser(row.user_id)}>
    <Bot data-icon="inline-start" />
    Мимики ({row.agents_total})
  </Button>
</TableCell>
```

- [x] **10.5. Повторить команду 10.2.** Тест экрана пользователей — 4 passed; общие проверки этапов 8–10 — 24 passed, `bun run typecheck` прошёл. `impeccable detect --json` по экрану вернул пустой список. Коммит: `feat(admin): show searchable users and agent state details`.

## Этап 11. Пресеты в админке и согласование пользовательского каталога

**Files:** `frontend/src/components/admin/AdminPresets.tsx`, `frontend/src/app/(dashboard)/admin/presets/page.tsx`; изменить `frontend/src/hooks/usePromptPresets.ts`, `frontend/src/hooks/usePresetFavorites.ts`, `frontend/src/hooks/usePresetAuthors.ts`, `frontend/src/lib/presets/catalog.ts`, `frontend/src/app/(dashboard)/presets/page.tsx`, `frontend/src/components/agent/PresetPicker.tsx`; новые `frontend/src/__tests__/admin-presets.test.tsx`, дополнить `frontend/src/__tests__/preset-catalog-logic.test.ts`, `frontend/src/__tests__/preset-picker.test.tsx`, `frontend/src/__tests__/prompt-presets.test.ts`.

- [x] **11.1. Написать проверки:** официальный открывается в `PresetEditorDialog`; пользовательский — только в read-only просмотре; скрытие ожидает сервер, блокирует повтор и инвалидирует оба набора кешей; ошибка оставляет старый статус. Протухшая ссылка на пресет показывает «Пресет больше недоступен» и не подставляет старое тело.
- [x] **11.2. Проверить пользовательские сценарии:** автор видит скрытый пресет в «Моих» с меткой; магазин его не показывает; автор может применить свой скрытый; неактивный официальный отсутствует в picker; снимок избранного сохраняется; правка автора не отправляет поле активности. По тестам этапа — 34 passed; вместе с проверками редактора/мутаций — 47 passed.
- [x] **11.3. Исправить чтение каталога**: убран `.eq('is_active', true)` из `fetchPromptPresets`, так как RLS возвращает доступный каталог плюс скрытые собственные строки. В `CatalogEntry` добавлен `isActive`; store фильтрует активность, mine — владельца, а официальный picker исключает неактивные строки. Для каталога, избранного и авторов заданы staleTime 30 с, refetch 60 с, обновление при фокусе и reconnect.

```typescript
const store = presets.filter((preset) =>
  preset.is_active && (
    preset.owner_id === null ||
    (preset.published_at !== null && preset.owner_id !== userId)
  )
);
const mine = presets.filter((preset) =>
  preset.owner_id !== null && preset.owner_id === userId
);
```

Для каталога, избранного и авторов установить `staleTime: 30_000`, `refetchInterval: 60_000`, `refetchOnWindowFocus: 'always'`, `refetchOnReconnect: true`. После административной мутации инвалидировать весь `queryKeys.presets.all`, чтобы обновились три проекции. Существующие snapshot-правила применения не переписывать.

- [x] **11.4. Реализовать админский список** с q/kind/page; body/settings загружаются только через detail. Официальные пресеты создаются и редактируются существующим `PresetEditorDialog`; порядок меняется отдельным целочисленным PATCH `{sort_order}` с проверкой границ PostgreSQL integer.
- [x] **11.5. Видимость менять отдельным действием с иконкой и доступным названием** «Скрыть пресет»/«Вернуть в каталог». Перед скрытием существующий `ConfirmDialog` поясняет заморозку избранного. Пользовательские пресеты доступны только для просмотра, body выводится plain text.
- [x] **11.6. Повторить команду 11.2.** 47 тестов прошли, `bun run typecheck` прошёл, Impeccable detector по изменённым UI-целям вернул пустой список. Коммит: `feat(admin): add preset moderation UI and refresh owner catalogs`.

## Этап 12. Форма общей Telegram-пары

**Files:** `frontend/src/components/admin/AdminTelegramSettings.tsx`, `frontend/src/app/(dashboard)/admin/telegram/page.tsx`; новый `frontend/src/__tests__/admin-telegram-settings.test.tsx`.

- [x] **12.1. Написать проверки формы:** API ID из GET; HASH пуст независимо от `has_api_hash`; ввод новой пары обязателен; повторное сохранение недоступно; успешная операция очищает HASH; ошибка сохраняет API ID, но очищает HASH; `403` закрывает экран. HASH отсутствует в QueryClient и MutationCache после запроса.
- [x] **12.2. Выполнить** `bun test src/__tests__/admin-telegram-settings.test.tsx`: 5 passed.
- [x] **12.3. Построить форму** на FieldGroup/Field/FieldLabel, существующих Input и Button. API ID использует `inputMode="numeric"` и строгую проверку целого 1–2147483647. HASH — `type="password"`, `autoComplete="new-password"`; сохранение отправляет пару прямым `adminApi.saveTelegramSettings`, без `useMutation`. Во время сохранения Button отключает повтор.

```tsx
<Field>
  <FieldLabel htmlFor="platform-api-hash">API HASH</FieldLabel>
  <Input
    id="platform-api-hash"
    type="password"
    autoComplete="new-password"
    value={apiHash}
    onChange={(event) => setApiHash(event.target.value)}
    disabled={saving}
  />
  <FieldDescription>
    Введи HASH новой пары. Сохранённое значение не показывается.
  </FieldDescription>
</Field>
```

- [x] **12.4. В обработчике submit** HASH копируется только в аргумент прямого API-вызова и очищается в `finally`. Ошибка получает безопасный общий текст. После успеха запускается инвалидирование публичного query и показывается штатный Toast; повторный GET не задерживает очистку секретного поля. Сохранённая HASH не маскируется фиктивным значением. Под формой есть пояснение о применении пары только к новым подключениям; источник отображается как «Окружение сервера»/«Настройка платформы»/«Не настроено».
- [x] **12.5. Повторить команду 12.2.** 5 passed, `bun run typecheck` прошёл, Impeccable detector вернул пустой список. Коммит: `feat(admin): add write-only Telegram credentials form`.

## Этап 13. Экран общей статистики

**Files:** `frontend/src/components/admin/AdminStatistics.tsx`, `frontend/src/app/(dashboard)/admin/page.tsx`; новый `frontend/src/__tests__/admin-statistics.test.tsx`.

- [x] **13.1. Написать проверки:** переключение 7/30 меняет ключ и запрос; у токенов надпись «За всё время»; UTC указан; нули появляются только при успешных нулевых данных; ошибка не маскируется пустым графиком; незавершённый текущий день не называется полным. Точечный тест-сьют написан.
- [x] **13.2. Построить интерфейс** на нынешних Card/Badge и установленном Recharts 2, ориентируясь на `components/agent/TabAnalytics.tsx`. Пользователи и распределение мимиков — текущие; сообщения/действия/ошибки — выбранный период; токены — отдельная подписанная группа. Чужие сообщения и трейсы не выводятся.
- [x] **13.3. Переключатель периода** — ToggleGroup с single-value; пустое значение при повторном нажатии игнорируется:

```tsx
<ToggleGroup
  type="single"
  value={String(days)}
  onValueChange={(value) => {
    if (value === '7' || value === '30') setDays(Number(value) as 7 | 30);
  }}
  aria-label="Период статистики"
>
  <ToggleGroupItem value="7">7 дней</ToggleGroupItem>
  <ToggleGroupItem value="30">30 дней</ToggleGroupItem>
</ToggleGroup>
```

Легенда, доступная текстовая сводка и раскрываемая таблица позволяют понять графики без различения цветов. ResponsiveContainer имеет явно заданную высоту родителя и `min-w-0`. Цвета — семантические CSS-токены, без новых шрифтов и анимации, задерживающей показ данных. Запрос обновляется раз в минуту в активной вкладке.

- [x] **13.4. Повторить команду 13.1.** 4 теста прошли; `bun run typecheck` прошёл, Impeccable detector вернул пустой список. Коммит: `feat(admin): show platform metrics and UTC activity charts`.

## Этап 14. Сквозные сценарии и визуальная проверка

**Files:** новый `tests/e2e/test_admin.py`; изменить `src/mimic42/testing/server.py`, `tests/e2e/conftest.py` только для ограниченной тестовой настройки роли; новый `tests/testing/test_admin_support.py`; служебные снимки `.impeccable/review/`.

- [x] **14.1. До браузерной автоматизации загрузить** `agent-browser`, а перед написанием Playwright-тестов — `playwright-best-practices-skill-main`. Использованы существующие pytest-фикстуры `servers/persona_page/auth_states/slot_info`; второго frontend runner и пользовательского личного браузера нет.
- [x] **14.2. Добавить только в тестовый entrypoint** `GET/PUT /__test__/admin-role`: PUT принимает `{slot, owner_id, enabled}`; GET отдельно считывает прежнюю роль. Оба требуют `X-Mimic42-Test-Slot-Holder`, проверяют точное членство owner_id в персонах и удерживают живую аренду через `FOR UPDATE` на время транзакции. Dev-guard проверяет endpoint проекта (включая username pooler), а не подстроку в пароле. Fixture получает исходное состояние до записи и восстанавливает его в `finally`, даже если ответ на установку потерян.
- [x] **14.3. Проверить поддержку тестовых маршрутов unit-тестами** `uv run pytest tests/testing/test_slots_guard.py tests/testing/test_admin_support.py -W error -q`: 12 passed; проверены прямой Dev/pooler, prod ref в пароле, чужая персона, неактивная аренда, read/write роли, точечный teardown и отсутствие test routes в production app. Глобальные роли/settings не очищаются.
- [x] **14.4. Написать сквозные проверки:** 3 сценария покрывают гостевой redirect, отказ обычной персоне без агентов, доступ выданной персоне без агентов, уникальный официальный fixture-пресет, порядок, hide/unhide, отзыв роли и API `403`; после отзыва также открываются обычный каталог и онбординг. Пресет удаляется только по захваченному UUID и с проверкой синтетического title.
- [x] **14.5. Общую Telegram-настройку в shared Dev браузером не сохранять.** GET/PUT формы проверяются только route-mocking; в Dev, проде и общих настройках пара не менялась. Скриншот общей статистики также получает синтетические данные через route mock и не содержит агрегаты общей Dev-базы.
- [x] **14.6. Выполнить только новый браузерный сценарий:** `uv run pytest tests/e2e/test_admin.py -m e2e -W error -q` — 3 passed после финальных изменений. Перед запуском порты свободны, конкурирующих `next dev`/`next build` не было; E2E использовал существующие `E2E_API_PORT/E2E_APP_PORT` и проверил аренду слота.
- [x] **14.7. Снять и открыть desktop 1440 и mobile 390** для четырёх подразделов, загрузки/ошибки, длинных данных и прокручиваемых графиков. Снимки ограничены реальным viewport; прокручиваемые dashboard-контейнеры сняты отдельными кадрами. Telegram HASH пуст, статистика синтетическая. Исправлены два дефекта, обнаруженные QA: JSON `null` вместо SQL `NULL` для nullable JSONB-настроек и задерживающая появление графиков анимация. Impeccable detector на изменённых UI-targets вернул `[]`.
- [x] **14.8. Коммиты:** `test(admin): cover access, moderation, and dashboard workflows` и follow-up `fix(testing): restrict admin fixtures to active dev leases`.

## Этап 15. Документация эксплуатации и передача на локальную проверку

**Files:** `README.md` — существующий раздел настройки/эксплуатации; этот план — фактические migration paths и отметки.

- [ ] **15.1. Описать назначение/снятие роли в базе**, отдельно от миграций. Пример команды параметризован подтверждённым UUID аккаунта; не назначать себя или первую персону автоматически. Для проверки сначала SELECT UUID/email нужного профиля, затем одна запись в `admin_users`; для снятия — один UUID. Не публиковать email/UUID реального пользователя в документации.
- [ ] **15.2. Описать приоритет credentials:** сохранённая пара → env при отсутствии строки; hash не читается через UI; нужна доступность `SECRET_KEY`; существующие сессии не мигрируют. Откат приложения не должен удалять таблицы или журнал; возврат credentials — явное административное сохранение прежней пары, если она есть у владельца, а не очистка всех настроек.
- [ ] **15.3. Передать пользователю локальный адрес `/admin` и способ назначения его тестового аккаунта.** Запросить подтверждение работы приложения до PR. Пока его нет, не открывать PR, не пушить реализацию ради проверки CI и не ставить issue «Сделано».
- [ ] **15.4. Коммит:** `docs(admin): document access grants and Telegram settings lifecycle`.

## После подтверждения пользователем: проверки, PR и выпуск

Это отдельный гейт, не часть текущего запроса написать план.

- [ ] Выполнить предусмотренные проектом локальные проверки до push; команды не соединять в одну длинную shell-цепочку:

```bash
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -m "not db and not e2e and not real_tg and not real_llm" -W error -q
```

Из `frontend/`:

```bash
bun install --frozen-lockfile
bunx next lint
bun run typecheck
bun test
```

- [ ] Проверить `supabase migration list --linked`: все семь feature-миграций (3 admin schema/ACL, 2 moderation, 2 concurrent indexes) уже в Dev, иначе `migrations-drift` в CI упадёт. При обнаружении чужих миграций не использовать repair/include-all без выяснения причины.
- [ ] Проверить весь итоговый diff и соответствие спецификации без запуска тестов во время самого code review. Проверки уже выполнены предыдущим шагом. Не включать в diff `.env`, browser storage state, реальные credentials и артефакты с персональными данными.
- [ ] После исправления всех локально обнаруживаемых проблем один раз push, затем PR с `Closes #127`. Проверить `gh pr checks`; следить за существующими `backend`, `frontend`, `backend-db`, `e2e`, `migrations-drift`. Не запускать конкурирующие внешние проверки и не обходить concurrency/тестовые слоты. После создания PR перевести item проекта в «На ревью», не закрывать issue вручную раньше слияния.
- [ ] Перед слиянием учесть фактическую автоматизацию: `.github/workflows/deploy.yml` на push в main собирает образы и разворачивает их на VPS, но **не применяет SQL-миграции**. Изменение прав каталога и новые таблицы должны попасть в production до использования нового приложения.
- [ ] Только при отдельном разрешении на выпуск проверить production target, вывести dry-run ровно семи новых миграций, применить их через Supabase CLI к production, затем дать состояться деплою. Не перелинковывать локальный Dev-проект на production ради удобства. При отсутствии разрешения явно передать этот обязательный шаг владельцу и не заявлять, что выпуск завершён.
- [ ] После выпуска проверить отсутствие миграционного хвоста, вход обычного пользователя, отказ `/admin` без роли, доступ назначенного администратора и отсутствие secrets в ответах. Роль в production назначается вручную по подтверждённому аккаунту, не переносится из Dev. Общую пару production не менять ради проверки.

## Матрица покрытия спецификации

| Требование | Этапы |
| --- | --- |
| Ручное назначение, отказ самоназначения, отзыв на следующем запросе | 1, 2, 8, 9, 14, 15 |
| Пользователи без мимиков, поиск, пагинация, реальные состояния | 6, 10, 14 |
| Официальные пресеты, скрытие опубликованных, приватность черновиков | 3, 4, 11, 14 |
| Заморозка избранного, сохранение авторских прав и обновление кешей | 3, 4, 8, 11 |
| Шифрование пары, write-only HASH, безопасные ошибки и аудит | 1, 4, 5, 12 |
| Новые defaults без рестарта; старые сессии не меняются | 5, 14, 15 |
| UTC-графики, пожизненные токены, отсутствие JOIN-дублирования | 7, 13 |
| Адаптивный UI, загрузка/пустота/ошибка, работа без собственного агента | 9–14 |
| Изоляция shared Dev, отсутствие изменений production при разработке | 1, 5, 14, гейт выпуска |
| Подтверждение пользователем до PR, CI и отдельные production-миграции | 15, гейт выпуска |

## Документация для выполнения

Изучена при подготовке; при выполнении сверять используемые методы с текущими версиями, не переносить случайно примеры новых major-версий в существующий стек.

- [FastAPI: APIRouter и общие зависимости](https://fastapi.tiangolo.com/tutorial/bigger-applications/).
- [FastAPI: route_class и RequestValidationError](https://fastapi.tiangolo.com/how-to/custom-request-and-route/).
- [SQLAlchemy 2: внешняя транзакция и create_savepoint](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites).
- [SQLAlchemy 2: AsyncSession, не разделяемая между конкурентными задачами](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html).
- [Supabase: RLS и безопасность метаданных роли](https://supabase.com/docs/guides/database/postgres/row-level-security).
- [Supabase: явные grants и Data API](https://supabase.com/docs/guides/api/securing-your-api).
- [TanStack Query 5: staleTime, refetchInterval и gcTime](https://tanstack.com/query/latest/docs/framework/react/guides/important-defaults).
- [shadcn Field](https://ui.shadcn.com/docs/components/radix/field), [Empty](https://ui.shadcn.com/docs/components/radix/empty), [Table](https://ui.shadcn.com/docs/components/radix/table), [Pagination](https://ui.shadcn.com/docs/components/radix/pagination), [ToggleGroup](https://ui.shadcn.com/docs/components/radix/toggle-group).
- Локальные `supabase db push --help`, `supabase db advisors --help`, `supabase migration new --help`; версия CLI проверена: 2.100.1.
