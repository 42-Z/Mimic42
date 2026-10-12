# Каталог пресетов (issue #67) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Вкладка «Пресеты» в дашборде: витрина (магазин), свои пресеты с черновиками и избранное, которое попадает в меню выбора у мимиков; свои пресеты создаются, выкладываются, снимаются и удаляются.

**Architecture:** Всё живёт в `prompt_presets`: добавляются `owner_id` и `published_at`; официальные четыре строки остаются read-only для клиентов (политики + security-definer триггеры-ограждения). Избранное — отдельная таблица `preset_favorites` со снимками: снятие с витрины и удаление замораживают чужие избранные триггером. Фронтенд читает и пишет напрямую в Supabase под RLS (как `usePromptPresets` сейчас), React не меняет бэкенд.

**Tech Stack:** Supabase (Postgres 15 + RLS + security-definer триггеры, Supabase CLI), Next.js 14 App Router, TanStack Query v5, TypeScript, `bun test` + Testing Library, pytest + asyncpg (integration), Playwright через pytest (e2e).

**Spec:** `docs/superpowers/specs/2026-10-11-preset-catalog-design.md`

## Global Constraints

- Ветка `feat/preset-catalog` уже создана, спека закоммичена. Все задачи — в неё.
- Бэкенд (`src/mimic42/**`) не трогаем: правки только в `supabase/migrations/` и `frontend/`.
- Миграции применяются `supabase db push` — до тестовой (Dev) базы; проект слинкован. Прод не трогается.
- Тексты интерфейса — на русском. Комментарии — doc-комментарии на русском, без «заголовочных».
- Фронт-команды из `frontend/`: `bun test`, `bun run typecheck`, `bunx next lint`, `bun run generate:types`.
- Python-команды — `uv run`. Интеграционные тесты — `uv run pytest tests/integration/test_prompt_presets.py` (маркер `db`, требует тестовую базу).
- Не редактируй `frontend/src/types/supabase.ts` руками — только `bun run generate:types`.
- Коммиты по Conventional Commits, коммит после каждой задачи.
- Официальные пресеты нельзя ломать: после каждой миграции четыре официальных slug-а (`rage_comments`, `sasavot_fan`, `magnum_normie`, `battalion`) должны читаться, но не писаться клиентом.

---

### Task 1: Миграция — пользовательские пресеты в `prompt_presets`

**Files:**
- Create: `supabase/migrations/20261011120000_user_prompt_presets.sql`
- Modify: `tests/integration/test_prompt_presets.py` (добавить хелперы и тесты в конец, старые тесты не трогать)

**Interfaces:**
- Produces: колонки `owner_id uuid references public.profiles(id) on delete cascade`, `published_at timestamptz`; политика select заменена на трёхчастную; insert/update/delete-политики; security-definer триггер-ограждение `guard_user_prompt_presets` (владелец, слаг `u_<id>`, `published_at = null`, `is_active = true` на insert; официальные строки и `owner_id`/`slug` неприкосновенны на update/delete).

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/integration/test_prompt_presets.py` (импорты `UUID, uuid4` добавить к существующим):

```python
from uuid import UUID, uuid4  # добавить к существующим импортам


async def _create_profile(
    connection: asyncpg.Connection, email: str, display_name: str | None = None
) -> UUID:
    """Профиль напрямую ролью postgres: RLS профилей ограждает только клиентов."""
    user_id = uuid4()
    await connection.execute(
        "insert into public.profiles (id, email, display_name) values ($1, $2, $3)",
        user_id,
        email,
        display_name,
    )
    return user_id


async def _act_as_user(connection: asyncpg.Connection, user_id: UUID) -> None:
    """Роль authenticated + клеймы пользователя — как их видит PostgREST."""
    await connection.execute("set local role authenticated")
    await connection.execute(
        "select set_config('request.jwt.claims', $1, true)",
        f'{{"sub":"{user_id}","role":"authenticated"}}',
    )
    await connection.execute(
        "select set_config('request.jwt.claim.sub', $1, true)", str(user_id)
    )


# RLS-отказ (42501) и raise в триггере (P0001) для клиента выглядят одинаково.
DENIED = (asyncpg.RaiseError, asyncpg.InsufficientPrivilegeError)


async def test_owner_creates_draft_and_reads_it(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        owner = await _create_profile(connection, "author@example.com", "Автор")
        async with connection.transaction():
            await _act_as_user(connection, owner)
            preset_id = await connection.fetchval(
                "insert into public.prompt_presets (title, summary, body) "
                "values ('Мой пресет', 'мой характер', 'текст характера') "
                "returning id"
            )
            row = await connection.fetchrow(
                "select owner_id, published_at, slug, is_active "
                "from public.prompt_presets where id = $1",
                preset_id,
            )
            assert row["owner_id"] == owner
            assert row["published_at"] is None
            assert row["is_active"] is True
            assert row["slug"].startswith("u_")
    finally:
        await connection.close()


async def test_official_rows_are_untouchable(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        owner = await _create_profile(connection, "guard@example.com")
        async with connection.transaction():
            await _act_as_user(connection, owner)
            with pytest.raises(DENIED):
                await connection.execute(
                    "update public.prompt_presets set title = 'взломано' "
                    "where slug = 'rage_comments'"
                )
            with pytest.raises(DENIED):
                await connection.execute(
                    "delete from public.prompt_presets where slug = 'rage_comments'"
                )
            with pytest.raises(DENIED):
                await connection.execute(
                    "update public.prompt_presets set slug = 'my_own' "
                    "where slug = 'rage_comments'"
                )
    finally:
        await connection.close()


async def test_draft_is_hidden_from_others(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        author = await _create_profile(connection, "hidden@example.com")
        reader = await _create_profile(connection, "reader@example.com")
        async with connection.transaction():
            await _act_as_user(connection, author)
            await connection.execute(
                "insert into public.prompt_presets (title, summary, body) "
                "values ('Секретный', 'черновик', 'текст')"
            )
        async with connection.transaction():
            await _act_as_user(connection, reader)
            count = await connection.fetchval(
                "select count(*) from public.prompt_presets where title = 'Секретный'"
            )
            assert count == 0
    finally:
        await connection.close()


async def test_publish_makes_preset_visible_and_editable(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        author = await _create_profile(connection, "pub@example.com")
        reader = await _create_profile(connection, "pub-reader@example.com")
        async with connection.transaction():
            await _act_as_user(connection, author)
            preset_id = await connection.fetchval(
                "insert into public.prompt_presets (title, summary, body) "
                "values ('Витринный', 'для всех', 'старый текст') returning id"
            )
            await connection.execute(
                "update public.prompt_presets set published_at = now() where id = $1",
                preset_id,
            )
        async with connection.transaction():
            await _act_as_user(connection, reader)
            body = await connection.fetchval(
                "select body from public.prompt_presets where id = $1", preset_id
            )
            assert body == "старый текст"
            count = await connection.fetchval(
                "select count(*) from public.prompt_presets "
                "where owner_id is null and published_at is not null"
            )
            # Официальные строки выложенными считаться не должны.
            assert count == 1
        async with connection.transaction():
            await _act_as_user(connection, author)
            await connection.execute(
                "update public.prompt_presets set body = 'новый текст' where id = $1",
                preset_id,
            )
        async with connection.transaction():
            await _act_as_user(connection, reader)
            body = await connection.fetchval(
                "select body from public.prompt_presets where id = $1", preset_id
            )
            assert body == "новый текст"
    finally:
        await connection.close()


async def test_owner_cannot_reassign_owner_or_slug(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        owner = await _create_profile(connection, "reassign@example.com")
        async with connection.transaction():
            await _act_as_user(connection, owner)
            preset_id = await connection.fetchval(
                "insert into public.prompt_presets (title, summary, body) "
                "values ('Переезд', 'трой', 'текст') returning id"
            )
            # owner_id и slug не выданы в grant — column privilege, 42501.
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(
                    "update public.prompt_presets set owner_id = gen_random_uuid() where id = $1",
                    preset_id,
                )
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(
                    "update public.prompt_presets set slug = 'hand_made' where id = $1",
                    preset_id,
                )
    finally:
        await connection.close()
```

- [ ] **Step 2: Запустить тесты и убедиться, что новые падают**

Run: `uv run pytest tests/integration/test_prompt_presets.py -v`
Expected: старые 4 теста PASS; новые — FAIL (`UndefinedColumnError: column "owner_id" does not exist` или RLS-отказ на insert).

- [ ] **Step 3: Написать миграцию**

Создать `supabase/migrations/20261011120000_user_prompt_presets.sql`:

```sql
-- Issue #67: prompt_presets становится единым каталогом. Официальные строки
-- (owner_id is null) остаются read-only для клиентов; пользовательские строки
-- создаются как черновики и выкладываются публикацией published_at.

alter table public.prompt_presets
    add column owner_id uuid references public.profiles(id) on delete cascade,
    add column published_at timestamptz;

create index prompt_presets_published_idx
    on public.prompt_presets (published_at)
    where published_at is not null;

-- Чтение уже выдано; запись раздаём поколоночно, чтобы клиент не мог трогать
-- slug, is_active и owner_id. slug и owner_id ставит триггер.
grant insert (title, summary, body, settings) on public.prompt_presets to authenticated;
grant update (title, summary, body, settings, published_at) on public.prompt_presets to authenticated;
grant delete on public.prompt_presets to authenticated;

-- Старая политика «только is_active» открыла бы все пользовательские черновики
-- всем — заменяем на трёхчастную.
drop policy "Authenticated users can read active prompt presets" on public.prompt_presets;

create policy "Authenticated users can read catalog presets"
    on public.prompt_presets
    for select
    to authenticated
    using (
        owner_id = auth.uid()
        or published_at is not null
        or (owner_id is null and is_active)
    );

create policy "Authenticated users can create own draft presets"
    on public.prompt_presets
    for insert
    to authenticated
    with check (owner_id = auth.uid() and published_at is null);

create policy "Authenticated users can update own presets"
    on public.prompt_presets
    for update
    to authenticated
    using (owner_id = auth.uid())
    with check (owner_id = auth.uid());

create policy "Authenticated users can delete own presets"
    on public.prompt_presets
    for delete
    to authenticated
    using (owner_id = auth.uid());

-- Ограждение клиентских сессий: сервисная запись и миграции ходят без
-- JWT-клеймов и проходят беспрепятственно.
create or replace function public.guard_user_prompt_presets() returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if auth.uid() is null then
        return coalesce(new, old);
    end if;

    if tg_op = 'INSERT' then
        new.owner_id = auth.uid();
        new.published_at = null;
        new.is_active = true;
        new.slug = 'u_' || new.id::text;
        return new;
    end if;

    if old.owner_id is null then
        raise exception 'Официальные пресеты изменять нельзя';
    end if;

    if tg_op = 'UPDATE' then
        if new.owner_id <> old.owner_id then
            raise exception 'Владельца пресета менять нельзя';
        end if;
        if new.slug <> old.slug then
            raise exception 'Слаг пресета менять нельзя';
        end if;
        return new;
    end if;

    return old;
end;
$$;

create trigger prompt_presets_guard_insert
    before insert on public.prompt_presets
    for each row execute function public.guard_user_prompt_presets();

create trigger prompt_presets_guard_update
    before update on public.prompt_presets
    for each row execute function public.guard_user_prompt_presets();

create trigger prompt_presets_guard_delete
    before delete on public.prompt_presets
    for each row execute function public.guard_user_prompt_presets();
```

- [ ] **Step 4: Применить миграцию к тестовой базе**

Run: `supabase db push`
Expected: CLI печатает `20261011120000_user_prompt_presets.sql` и `Finished supabase db push.`

- [ ] **Step 5: Запустить тесты и убедиться, что всё зелёное**

Run: `uv run pytest tests/integration/test_prompt_presets.py -v`
Expected: все тесты PASS (старые 4 + новые 5).

- [ ] **Step 6: Коммит**

```bash
git add supabase/migrations/20261011120000_user_prompt_presets.sql tests/integration/test_prompt_presets.py
git commit -m "feat(db): user presets in prompt_presets (issue 67)"
```

---

### Task 2: Миграция — таблица `preset_favorites`

**Files:**
- Create: `supabase/migrations/20261011120100_preset_favorites.sql`
- Modify: `tests/integration/test_prompt_presets.py` (добавить тесты в конец)

**Interfaces:**
- Produces: таблица `preset_favorites` (owner_id, preset_id, frozen_title/summary/body/settings, frozen_at), unique `(owner_id, preset_id)`, RLS: select/delete — свои, insert — только на чужой выложенный пресет; триггер `preset_favorites_set_owner` проставляет `owner_id = auth.uid()` на insert.

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/integration/test_prompt_presets.py`:

```python
async def _publish_preset(
    connection: asyncpg.Connection,
    owner: UUID,
    title: str = "Избранный",
    body: str = "текст чужого пресета",
) -> UUID:
    """Черновик + публикация от лица владельца; возвращает id пресета."""
    async with connection.transaction():
        await _act_as_user(connection, owner)
        preset_id = await connection.fetchval(
            "insert into public.prompt_presets (title, summary, body) "
            "values ($1, 'характер для витрины', $2) returning id",
            title,
            body,
        )
        await connection.execute(
            "update public.prompt_presets set published_at = now() where id = $1",
            preset_id,
        )
    return preset_id


async def test_user_can_favorite_published_foreign_preset(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        author = await _create_profile(connection, "fav-author@example.com")
        reader = await _create_profile(connection, "fav-reader@example.com")
        outsider = await _create_profile(connection, "fav-outsider@example.com")
        preset_id = await _publish_preset(connection, author)

        async with connection.transaction():
            await _act_as_user(connection, reader)
            favorite_id = await connection.fetchval(
                "insert into public.preset_favorites (preset_id) values ($1) returning id",
                preset_id,
            )
            row = await connection.fetchrow(
                "select owner_id, preset_id, frozen_at from public.preset_favorites where id = $1",
                favorite_id,
            )
            assert row["owner_id"] == reader
            assert row["preset_id"] == preset_id
            assert row["frozen_at"] is None
            # Своё избранное видно, чужое — нет.
            assert await connection.fetchval("select count(*) from public.preset_favorites") == 1
        async with connection.transaction():
            await _act_as_user(connection, outsider)
            assert await connection.fetchval("select count(*) from public.preset_favorites") == 0
    finally:
        await connection.close()


async def test_favorite_is_forbidden_for_official_own_and_unpublished(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        author = await _create_profile(connection, "no-fav-author@example.com")
        reader = await _create_profile(connection, "no-fav-reader@example.com")
        # Официальный пресет ищем по слагу.
        official_id = UUID(
            await connection.fetchval(
                "select id from public.prompt_presets where slug = 'rage_comments'"
            )
        )
        own_preset_id = await _publish_preset(connection, reader, title="Своя витрина")

        async with connection.transaction():
            await _act_as_user(connection, reader)
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(
                    "insert into public.preset_favorites (preset_id) values ($1)", official_id
                )
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(
                    "insert into public.preset_favorites (preset_id) values ($1)", own_preset_id
                )
        # Чужой черновик: RLS не даёт его ни увидеть, ни избрать.
        async with connection.transaction():
            await _act_as_user(connection, author)
            draft_id = await connection.fetchval(
                "insert into public.prompt_presets (title, summary, body) "
                "values ('Тайный', 'черновик', 'текст') returning id"
            )
        async with connection.transaction():
            await _act_as_user(connection, reader)
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(
                    "insert into public.preset_favorites (preset_id) values ($1)", draft_id
                )
    finally:
        await connection.close()


async def test_favorite_is_unique_per_preset(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        author = await _create_profile(connection, "uniq-author@example.com")
        reader = await _create_profile(connection, "uniq-reader@example.com")
        preset_id = await _publish_preset(connection, author)
        async with connection.transaction():
            await _act_as_user(connection, reader)
            await connection.execute(
                "insert into public.preset_favorites (preset_id) values ($1)", preset_id
            )
            with pytest.raises(asyncpg.UniqueViolationError):
                await connection.execute(
                    "insert into public.preset_favorites (preset_id) values ($1)", preset_id
                )
    finally:
        await connection.close()


async def test_user_can_remove_own_favorite(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        author = await _create_profile(connection, "rm-author@example.com")
        reader = await _create_profile(connection, "rm-reader@example.com")
        preset_id = await _publish_preset(connection, author)
        async with connection.transaction():
            await _act_as_user(connection, reader)
            favorite_id = await connection.fetchval(
                "insert into public.preset_favorites (preset_id) values ($1) returning id",
                preset_id,
            )
            await connection.execute(
                "delete from public.preset_favorites where id = $1", favorite_id
            )
            assert await connection.fetchval("select count(*) from public.preset_favorites") == 0
    finally:
        await connection.close()
```

- [ ] **Step 2: Запустить тесты и убедиться, что новые падают**

Run: `uv run pytest tests/integration/test_prompt_presets.py -v`
Expected: тесты Task 1 PASS; новые — FAIL (`UndefinedTableError: relation "preset_favorites" does not exist`).

- [ ] **Step 3: Написать миграцию**

Создать `supabase/migrations/20261011120100_preset_favorites.sql`:

```sql
-- Избранное пресетов. Пока пресет на витрине, избранное смотрит на живую
-- строку (снимки пустые). Снятие с витрины и удаление пресета замораживают
-- избранное триггером из следующей миграции; замороженная копия остаётся
-- только для применения.

create table public.preset_favorites (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references public.profiles(id) on delete cascade,
    preset_id uuid references public.prompt_presets(id) on delete cascade,
    frozen_title text,
    frozen_summary text,
    frozen_body text not null,
    frozen_settings jsonb
        check (frozen_settings is null or jsonb_typeof(frozen_settings) = 'object'),
    frozen_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (owner_id, preset_id),
    constraint preset_favorites_have_source_or_snapshot
        check (preset_id is not null or frozen_at is not null)
);

create trigger preset_favorites_set_updated_at
    before update on public.preset_favorites
    for each row execute function public.set_updated_at();

alter table public.preset_favorites enable row level security;

-- owner_id ставит триггер, поэтому грант только на preset_id.
grant select, delete on public.preset_favorites to authenticated;
grant insert (preset_id) on public.preset_favorites to authenticated;

create or replace function public.set_favorite_owner() returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    new.owner_id = auth.uid();
    return new;
end;
$$;

create trigger preset_favorites_set_owner
    before insert on public.preset_favorites
    for each row execute function public.set_favorite_owner();

create policy "Users can read own favorites"
    on public.preset_favorites
    for select
    to authenticated
    using (owner_id = auth.uid());

-- В избранное кладут только чужой выложенный пресет: official (owner_id null)
-- и свои отсекаются одним условием.
create policy "Users can favorite published presets of others"
    on public.preset_favorites
    for insert
    to authenticated
    with check (
        owner_id = auth.uid()
        and exists (
            select 1 from public.prompt_presets pp
            where pp.id = preset_id
              and pp.published_at is not null
              and pp.owner_id <> auth.uid()
        )
    );

create policy "Users can remove own favorites"
    on public.preset_favorites
    for delete
    to authenticated
    using (owner_id = auth.uid());
```

Политики `update` нет: заморозку делает только триггер с правами владельца таблицы.

- [ ] **Step 4: Применить миграцию к тестовой базе**

Run: `supabase db push`
Expected: `Finished supabase db push.`

- [ ] **Step 5: Запустить тесты**

Run: `uv run pytest tests/integration/test_prompt_presets.py -v`
Expected: все тесты PASS.

- [ ] **Step 6: Коммит**

```bash
git add supabase/migrations/20261011120100_preset_favorites.sql tests/integration/test_prompt_presets.py
git commit -m "feat(db): preset favorites with snapshot columns"
```

---

### Task 3: Миграция — заморозка избранного и имена авторов

**Files:**
- Create: `supabase/migrations/20261011120200_freeze_favorites_and_authors.sql`
- Modify: `tests/integration/test_prompt_presets.py` (добавить тесты в конец)

**Interfaces:**
- Produces: security-definer триггер `freeze_preset_favorites` на update (снятие) и delete пресета; представление `preset_authors` (только `id` и `display_name` авторов выложенных пресетов).

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/integration/test_prompt_presets.py` (импорт `json` уже есть в файле):

```python
async def test_unpublish_freezes_favorites(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        author = await _create_profile(connection, "freeze-a@example.com")
        reader = await _create_profile(connection, "freeze-b@example.com")
        preset_id = await _publish_preset(
            connection, author, title="Заморозка", body="текст на витрине"
        )
        async with connection.transaction():
            await _act_as_user(connection, reader)
            await connection.execute(
                "insert into public.preset_favorites (preset_id) values ($1)", preset_id
            )
        async with connection.transaction():
            await _act_as_user(connection, author)
            await connection.execute(
                "update public.prompt_presets set published_at = null where id = $1",
                preset_id,
            )
        async with connection.transaction():
            await _act_as_user(connection, reader)
            row = await connection.fetchrow(
                "select preset_id, frozen_title, frozen_body, frozen_at "
                "from public.preset_favorites"
            )
            assert row["preset_id"] is None
            assert row["frozen_title"] == "Заморозка"
            assert row["frozen_body"] == "текст на витрине"
            assert row["frozen_at"] is not None
    finally:
        await connection.close()


async def test_delete_freezes_favorites(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        author = await _create_profile(connection, "del-a@example.com")
        reader = await _create_profile(connection, "del-b@example.com")
        preset_id = await _publish_preset(
            connection, author, title="Удаляемый", body="пропадёт с витрины"
        )
        async with connection.transaction():
            await _act_as_user(connection, reader)
            await connection.execute(
                "insert into public.preset_favorites (preset_id) values ($1)", preset_id
            )
        async with connection.transaction():
            await _act_as_user(connection, author)
            await connection.execute(
                "delete from public.prompt_presets where id = $1", preset_id
            )
        # Строка пресета удалена, избранное осталось замороженной копией.
        assert await connection.fetchval(
            "select count(*) from public.prompt_presets where id = $1", preset_id
        ) == 0
        async with connection.transaction():
            await _act_as_user(connection, reader)
            row = await connection.fetchrow(
                "select preset_id, frozen_body, frozen_at from public.preset_favorites"
            )
            assert row["preset_id"] is None
            assert row["frozen_body"] == "пропадёт с витрины"
            assert row["frozen_at"] is not None
    finally:
        await connection.close()


async def test_republish_keeps_old_copy_frozen(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        author = await _create_profile(connection, "repub-a@example.com")
        reader = await _create_profile(connection, "repub-b@example.com")
        preset_id = await _publish_preset(connection, author, title="Возвращение")
        async with connection.transaction():
            await _act_as_user(connection, reader)
            await connection.execute(
                "insert into public.preset_favorites (preset_id) values ($1)", preset_id
            )
        async with connection.transaction():
            await _act_as_user(connection, author)
            await connection.execute(
                "update public.prompt_presets set published_at = null where id = $1",
                preset_id,
            )
            await connection.execute(
                "update public.prompt_presets set published_at = now() where id = $1",
                preset_id,
            )
        async with connection.transaction():
            await _act_as_user(connection, reader)
            # Старая копия остаётся замороженной, повторное сохранение даёт
            # вторую запись — уникальность (owner_id, preset_id) не мешает.
            assert await connection.fetchval(
                "select count(*) from public.preset_favorites where frozen_at is not null"
            ) == 1
            await connection.execute(
                "insert into public.preset_favorites (preset_id) values ($1)", preset_id
            )
            assert await connection.fetchval("select count(*) from public.preset_favorites") == 2
    finally:
        await connection.close()


async def test_preset_authors_view(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        author = await _create_profile(connection, "view-a@example.com", "Витринный автор")
        # Черновик до публикации — автора в виде нет.
        async with connection.transaction():
            await _act_as_user(connection, author)
            draft_id = await connection.fetchval(
                "insert into public.prompt_presets (title, summary, body) "
                "values ('Черновик автора', 'х', 'текст') returning id"
            )
        names = await connection.fetch(
            "select display_name from public.preset_authors where id = $1", author
        )
        assert names == []

        await _publish_preset(connection, author, title="Публичный")
        names = await connection.fetch(
            "select display_name from public.preset_authors where id = $1", author
        )
        assert [row["display_name"] for row in names] == ["Витринный автор"]

        # Почта наружу не идёт: в виде только id и display_name.
        columns = await connection.fetch(
            "select column_name from information_schema.columns "
            "where table_schema = 'public' and table_name = 'preset_authors'"
        )
        assert {row["column_name"] for row in columns} == {"id", "display_name"}

        # Уборка за тестом: строка нужна только до конца проверки.
        await connection.execute(
            "delete from public.prompt_presets where id = $1", draft_id
        )
    finally:
        await connection.close()
```

- [ ] **Step 2: Запустить тесты и убедиться, что новые падают**

Run: `uv run pytest tests/integration/test_prompt_presets.py -v`
Expected: тесты Tasks 1–2 PASS; новые — FAIL (заморозки не происходит: `frozen_at` остаётся `None`, а `test_preset_authors_view` — `UndefinedTableError`).

- [ ] **Step 3: Написать миграцию**

Создать `supabase/migrations/20261011120200_freeze_favorites_and_authors.sql`:

```sql
-- Снятие с витрины и удаление пресета не отбирают уже сохранённое: в
-- избранном остаётся замороженная копия на момент снятия, её можно только
-- применять. Повторная выкладка оживляет только новые записи.

create or replace function public.freeze_preset_favorites() returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if tg_op = 'UPDATE' then
        update public.preset_favorites fav
        set preset_id = null,
            frozen_title = pp.title,
            frozen_summary = pp.summary,
            frozen_body = pp.body,
            frozen_settings = pp.settings,
            frozen_at = now()
        from public.prompt_presets pp
        where fav.preset_id = pp.id
          and pp.id = old.id;
        return new;
    end if;

    -- DELETE: снимок перед удалением строки, ссылки отвязываются до каскада.
    update public.preset_favorites fav
    set preset_id = null,
        frozen_title = old.title,
        frozen_summary = old.summary,
        frozen_body = old.body,
        frozen_settings = old.settings,
        frozen_at = now()
    where fav.preset_id = old.id;

    return old;
end;
$$;

create trigger prompt_presets_freeze_on_unpublish
    before update of published_at on public.prompt_presets
    for each row
    when (old.published_at is not null and new.published_at is null)
    execute function public.freeze_preset_favorites();

create trigger prompt_presets_freeze_on_delete
    before delete on public.prompt_presets
    for each row
    execute function public.freeze_preset_favorites();

-- Имена авторов витрины. Вид исполняется с правами владельца (не
-- security_invoker), поэтому RLS профилей не применяется; наружу идут только
-- display_name авторов выложенных пресетов — без email.
create view public.preset_authors as
select distinct pp.owner_id as id, pr.display_name
from public.prompt_presets pp
join public.profiles pr on pr.id = pp.owner_id
where pp.published_at is not null;

grant select on public.preset_authors to authenticated;
```

- [ ] **Step 4: Применить миграцию к тестовой базе**

Run: `supabase db push`
Expected: `Finished supabase db push.`

- [ ] **Step 5: Запустить тесты**

Run: `uv run pytest tests/integration/test_prompt_presets.py -v`
Expected: все тесты PASS (4 старых + 5 + 4 + 4).

- [ ] **Step 6: Коммит**

```bash
git add supabase/migrations/20261011120200_freeze_favorites_and_authors.sql tests/integration/test_prompt_presets.py
git commit -m "feat(db): freeze favorites on unpublish/delete, authors view"
```

---

### Task 4: Типы и ключи кеша на фронте

**Files:**
- Modify: `frontend/src/types/index.ts:444-456` (PromptPresetRow) + добавить PresetFavoriteRow
- Modify: `frontend/src/lib/queryClient.ts:60-64` (queryKeys.presets)
- Regen: `frontend/src/types/supabase.ts` (командой, руками не править)

**Interfaces:**
- Produces: `PromptPresetRow.owner_id: string | null`, `PromptPresetRow.published_at: string | null`, тип `PresetFavoriteRow`, `queryKeys.presets.favorites()`.

- [ ] **Step 1: Перегенерировать типы Supabase**

Run: `cd frontend && bun run generate:types && bun run typecheck`
Expected: в `frontend/src/types/supabase.ts` появились `preset_favorites` и `preset_authors`; в `prompt_presets` — `owner_id`, `published_at`; typecheck пока может падать (старые объекты `PromptPresetRow` без новых полей) — это нормально, поля добавляются на Step 2.

- [ ] **Step 2: Обновить ручные типы**

В `frontend/src/types/index.ts` заменить секцию `Prompt presets`:

```ts
// ── Prompt presets ────────────────────────────────────────────────────────────
export interface PromptPresetRow {
  id: string;
  slug: string;
  title: string;
  summary: string;
  body: string;
  settings: Record<string, unknown> | null;
  sort_order: number;
  is_active: boolean;
  owner_id: string | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

// Строка избранного: пока preset_id задан — живая ссылка на витринный пресет,
// после снятия/удаления — замороженная копия (preset_id null).
export interface PresetFavoriteRow {
  id: string;
  preset_id: string | null;
  frozen_title: string | null;
  frozen_summary: string | null;
  frozen_body: string;
  frozen_settings: Record<string, unknown> | null;
  frozen_at: string | null;
  created_at: string;
  updated_at: string;
}
```

И в `frontend/src/lib/queryClient.ts` расширить секцию `presets`:

```ts
  // Prompt presets
  presets: {
    all: ['presets'] as const,
    list: () => [...queryKeys.presets.all, 'list'] as const,
    favorites: () => [...queryKeys.presets.all, 'favorites'] as const,
  },
```

- [ ] **Step 3: Проверить фронт**

Run: `cd frontend && bun run typecheck && bun test`
Expected: typecheck и тесты без ошибок (существующие фикстуры `PromptPresetRow` в тестах без новых полей typecheck проходит, так как поля опциональны? — нет: поля обязательные. Поправь фикстуру `ROW` в `frontend/src/__tests__/prompt-presets.test.ts`, добавив `owner_id: null, published_at: null`).

- [ ] **Step 4: Коммит**

```bash
git add frontend/src/types/index.ts frontend/src/lib/queryClient.ts frontend/src/types/supabase.ts frontend/src/__tests__/prompt-presets.test.ts
git commit -m "feat(frontend): types and query keys for preset catalog"
```

---

### Task 5: Хуки избранного и мутаций

**Files:**
- Create: `frontend/src/hooks/usePresetFavorites.ts`
- Create: `frontend/src/hooks/usePresetMutations.ts`
- Test: `frontend/src/__tests__/preset-mutations.test.ts`

**Interfaces:**
- Consumes: `PresetFavoriteRow`, `queryKeys.presets.favorites()`.
- Produces: `fetchPresetFavorites(client)`, `usePresetFavorites()`; чистые функции-мутации (client первым аргументом — для тестируемости) и обёртки `useCreatePreset`, `useUpdatePreset`, `usePublishPreset`, `useUnpublishPreset`, `useDeletePreset`, `useFavoritePreset`, `useUnfavoritePreset`; тип `PresetDraft { title, summary, body, settings }`.

- [ ] **Step 1: Написать падающие тесты**

Создать `frontend/src/__tests__/preset-mutations.test.ts`:

```ts
import { describe, expect, test } from 'bun:test';
import {
  createPreset,
  deletePreset,
  favoritePreset,
  publishPreset,
  unfavoritePreset,
  unfavoriteByPreset,
  unpublishPreset,
  updatePreset,
  type PresetDraft,
} from '@/hooks/usePresetMutations';
import { fetchPresetFavorites } from '@/hooks/usePresetFavorites';
import type { SupabaseBrowserClient } from '@/lib/supabase/client';

type MutationCalls = {
  table?: string;
  op?: 'insert' | 'update' | 'delete';
  values?: unknown;
  set?: unknown;
  eq?: [string, unknown];
};

function fakeMutationClient(
  result: { data: unknown; error: { message: string } | null },
) {
  const calls: MutationCalls = {};
  const client = {
    from(table: string) {
      calls.table = table;
      return {
        insert(values: unknown) {
          calls.op = 'insert';
          calls.values = values;
          return Promise.resolve(result);
        },
        update(values: unknown) {
          calls.op = 'update';
          calls.set = values;
          return {
            eq(column: string, value: unknown) {
              calls.eq = [column, value];
              return Promise.resolve(result);
            },
          };
        },
        delete() {
          calls.op = 'delete';
          return {
            eq(column: string, value: unknown) {
              calls.eq = [column, value];
              return Promise.resolve(result);
            },
          };
        },
      };
    },
  };
  return { client: client as unknown as SupabaseBrowserClient, calls };
}

const DRAFT: PresetDraft = {
  title: 'Мой пресет',
  summary: 'мой характер',
  body: 'текст',
  settings: { enabled_tools: ['send_text_message'] },
};

describe('preset mutations', () => {
  test('создание пишет черновик без owner_id и published_at', async () => {
    const { client, calls } = fakeMutationClient({ data: null, error: null });

    await createPreset(client, DRAFT);

    expect(calls.table).toBe('prompt_presets');
    expect(calls.op).toBe('insert');
    expect(calls.values).toEqual({
      title: 'Мой пресет',
      summary: 'мой характер',
      body: 'текст',
      settings: { enabled_tools: ['send_text_message'] },
    });
  });

  test('правка целится по id', async () => {
    const { client, calls } = fakeMutationClient({ data: null, error: null });

    await updatePreset(client, 'preset-1', DRAFT);

    expect(calls.op).toBe('update');
    expect(calls.set).toEqual({
      title: DRAFT.title,
      summary: DRAFT.summary,
      body: DRAFT.body,
      settings: DRAFT.settings,
    });
    expect(calls.eq).toEqual(['id', 'preset-1']);
  });

  test('выкладка ставит published_at, снятие обнуляет', async () => {
    const { client, calls } = fakeMutationClient({ data: null, error: null });

    await publishPreset(client, 'preset-1');
    expect(calls.set).toHaveProperty('published_at');
    expect((calls.set as { published_at: string }).published_at).toBeTruthy();

    await unpublishPreset(client, 'preset-1');
    expect(calls.set).toEqual({ published_at: null });
  });

  test('удаление целится по id', async () => {
    const { client, calls } = fakeMutationClient({ data: null, error: null });

    await deletePreset(client, 'preset-1');

    expect(calls.op).toBe('delete');
    expect(calls.eq).toEqual(['id', 'preset-1']);
  });

  test('избранное вставляет только preset_id, владелец — на триггере', async () => {
    const { client, calls } = fakeMutationClient({ data: null, error: null });

    await favoritePreset(client, 'preset-1');

    expect(calls.table).toBe('preset_favorites');
    expect(calls.op).toBe('insert');
    expect(calls.values).toEqual({ preset_id: 'preset-1' });
  });

  test('удаление из избранного идёт по id строки избранного', async () => {
    const { client, calls } = fakeMutationClient({ data: null, error: null });

    await unfavoritePreset(client, 'fav-1');

    expect(calls.table).toBe('preset_favorites');
    expect(calls.eq).toEqual(['id', 'fav-1']);
  });

  test('убрать живое избранное можно по пресету', async () => {
    const { client, calls } = fakeMutationClient({ data: null, error: null });

    await unfavoriteByPreset(client, 'preset-1');

    expect(calls.table).toBe('preset_favorites');
    expect(calls.eq).toEqual(['preset_id', 'preset-1']);
  });

  test('ошибка мутации пробрасывается', async () => {
    const { client } = fakeMutationClient({ data: null, error: { message: 'permission denied' } });
    await expect(createPreset(client, DRAFT)).rejects.toThrow('permission denied');
  });
});

describe('fetchPresetFavorites', () => {
  test('читает preset_favorites по created_at', async () => {
    const calls: { table?: string; orderColumn?: string } = {};
    const client = {
      from(table: string) {
        calls.table = table;
        return {
          select() {
            return {
              order(column: string) {
                calls.orderColumn = column;
                return Promise.resolve({ data: [], error: null });
              },
            };
          },
        };
      },
    } as unknown as SupabaseBrowserClient;

    await fetchPresetFavorites(client);

    expect(calls.table).toBe('preset_favorites');
    expect(calls.orderColumn).toBe('created_at');
  });
});
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd frontend && bun test src/__tests__/preset-mutations.test.ts`
Expected: FAIL — модуль `@/hooks/usePresetMutations` не существует.

- [ ] **Step 3: Написать хуки**

Создать `frontend/src/hooks/usePresetFavorites.ts`:

```ts
'use client';

import { useQuery } from '@tanstack/react-query';
import { getSupabaseClient, type SupabaseBrowserClient } from '@/lib/supabase/client';
import { queryKeys } from '@/lib/queryClient';
import type { PresetFavoriteRow } from '@/types';

/**
 * Читает избранное пресетов напрямую из Supabase под RLS. Живые записи
 * соединяются с пресетами на клиенте по preset_id.
 */
export async function fetchPresetFavorites(
  client: SupabaseBrowserClient,
): Promise<PresetFavoriteRow[]> {
  const { data, error } = await client
    .from('preset_favorites')
    .select('*')
    .order('created_at');

  if (error) throw new Error(error.message);
  return (data ?? []) as PresetFavoriteRow[];
}

export function usePresetFavorites() {
  return useQuery({
    queryKey: queryKeys.presets.favorites(),
    queryFn: () => fetchPresetFavorites(getSupabaseClient()),
  });
}
```

Создать `frontend/src/hooks/usePresetMutations.ts`:

```ts
'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { getSupabaseClient, type SupabaseBrowserClient } from '@/lib/supabase/client';
import { queryKeys } from '@/lib/queryClient';

/** Черновик пресета: название, описание, промпт и патч настроек. */
export interface PresetDraft {
  title: string;
  summary: string;
  body: string;
  settings: Record<string, unknown> | null;
}

export async function createPreset(client: SupabaseBrowserClient, draft: PresetDraft) {
  const { error } = await client.from('prompt_presets').insert({
    title: draft.title,
    summary: draft.summary,
    body: draft.body,
    settings: draft.settings,
  });
  if (error) throw new Error(error.message);
}

export async function updatePreset(
  client: SupabaseBrowserClient,
  id: string,
  draft: PresetDraft,
) {
  const { error } = await client
    .from('prompt_presets')
    .update({
      title: draft.title,
      summary: draft.summary,
      body: draft.body,
      settings: draft.settings,
    })
    .eq('id', id);
  if (error) throw new Error(error.message);
}

export async function publishPreset(client: SupabaseBrowserClient, id: string) {
  const { error } = await client
    .from('prompt_presets')
    .update({ published_at: new Date().toISOString() })
    .eq('id', id);
  if (error) throw new Error(error.message);
}

export async function unpublishPreset(client: SupabaseBrowserClient, id: string) {
  const { error } = await client
    .from('prompt_presets')
    .update({ published_at: null })
    .eq('id', id);
  if (error) throw new Error(error.message);
}

export async function deletePreset(client: SupabaseBrowserClient, id: string) {
  const { error } = await client.from('prompt_presets').delete().eq('id', id);
  if (error) throw new Error(error.message);
}

export async function favoritePreset(client: SupabaseBrowserClient, presetId: string) {
  const { error } = await client.from('preset_favorites').insert({ preset_id: presetId });
  if (error) throw new Error(error.message);
}

export async function unfavoritePreset(client: SupabaseBrowserClient, favoriteId: string) {
  const { error } = await client
    .from('preset_favorites')
    .delete()
    .eq('id', favoriteId);
  if (error) throw new Error(error.message);
}

export async function unfavoriteByPreset(client: SupabaseBrowserClient, presetId: string) {
  const { error } = await client
    .from('preset_favorites')
    .delete()
    .eq('preset_id', presetId);
  if (error) throw new Error(error.message);
}

// Все мутации инвалидируют весь каталог: пресеты и избранное меняются вместе.
function useInvalidatePresets() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: queryKeys.presets.all });
  };
}

export function useCreatePreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (draft: PresetDraft) => createPreset(getSupabaseClient(), draft),
    onSettled: invalidate,
  });
}

export function useUpdatePreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: ({ id, draft }: { id: string; draft: PresetDraft }) =>
      updatePreset(getSupabaseClient(), id, draft),
    onSettled: invalidate,
  });
}

export function usePublishPreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (id: string) => publishPreset(getSupabaseClient(), id),
    onSettled: invalidate,
  });
}

export function useUnpublishPreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (id: string) => unpublishPreset(getSupabaseClient(), id),
    onSettled: invalidate,
  });
}

export function useDeletePreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (id: string) => deletePreset(getSupabaseClient(), id),
    onSettled: invalidate,
  });
}

export function useFavoritePreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (presetId: string) => favoritePreset(getSupabaseClient(), presetId),
    onSettled: invalidate,
  });
}

export function useUnfavoritePreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (favoriteId: string) => unfavoritePreset(getSupabaseClient(), favoriteId),
    onSettled: invalidate,
  });
}

export function useUnfavoriteByPreset() {
  const invalidate = useInvalidatePresets();
  return useMutation({
    mutationFn: (presetId: string) => unfavoriteByPreset(getSupabaseClient(), presetId),
    onSettled: invalidate,
  });
}
```

- [ ] **Step 4: Запустить тесты**

Run: `cd frontend && bun test src/__tests__/preset-mutations.test.ts && bun run typecheck`
Expected: PASS, typecheck без ошибок.

- [ ] **Step 5: Коммит**

```bash
git add frontend/src/hooks/usePresetFavorites.ts frontend/src/hooks/usePresetMutations.ts frontend/src/__tests__/preset-mutations.test.ts
git commit -m "feat(frontend): favorites hook and preset mutations"
```

---

### Task 6: Редактор пресета `PresetEditorDialog`

**Files:**
- Create: `frontend/src/components/presets/PresetEditorDialog.tsx`
- Test: `frontend/src/__tests__/preset-editor.test.tsx`

**Interfaces:**
- Consumes: `Modal`, `Button`, `Input`, `ToolsSettings`, `readEnabledTools`, `mergeEnabledTools`, `PresetDraft`.
- Produces: `PresetEditorDialog({ isOpen, onClose, initial, onSave })`, где `initial?: { id, title, summary, body, settings } | null` (есть — редактирование), `onSave: (draft: PresetDraft) => Promise<void>` (страница отдаёт `mutateAsync`). `data-testid="preset-editor"`, поля с `get_by_label`: «Название», «Короткое описание», «Промпт»; кнопка `data-testid="preset-editor-save"`.

- [ ] **Step 1: Написать падающие тесты**

Создать `frontend/src/__tests__/preset-editor.test.tsx`:

```tsx
import { describe, expect, mock, test } from 'bun:test';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { PresetEditorDialog } from '@/components/presets/PresetEditorDialog';

function renderEditor(
  overrides: Partial<Parameters<typeof PresetEditorDialog>[0]> = {},
) {
  const onSave = mock((_draft: unknown) => Promise.resolve());
  const props = {
    isOpen: true,
    onClose: () => {},
    onSave,
    ...overrides,
  };
  render(<PresetEditorDialog {...props} />);
  return { onSave };
}

describe('PresetEditorDialog', () => {
  test('создание: пустая форма, сохранение отдаёт черновик', async () => {
    const { onSave } = renderEditor();

    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'Олд' } });
    fireEvent.change(screen.getByLabelText('Короткое описание'), {
      target: { value: 'как в 2007' },
    });
    fireEvent.change(screen.getByLabelText('Промпт'), { target: { value: 'Ты олд...' } });

    fireEvent.click(screen.getByTestId('preset-editor-save'));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0]).toEqual({
      title: 'Олд',
      summary: 'как в 2007',
      body: 'Ты олд...',
      settings: null,
    });
  });

  test('пустой промпт не сохраняется', () => {
    renderEditor();
    expect(screen.getByTestId('preset-editor-save')).toBeDisabled();
  });

  test('редактирование: поля из initial, настройки идут насквозь', async () => {
    const { onSave } = renderEditor({
      initial: {
        id: 'preset-1',
        title: 'Старое',
        summary: 'старое описание',
        body: 'старый текст',
        settings: { enabled_tools: ['view_image'], alien: 1 },
      },
    });

    expect(screen.getByLabelText('Название')).toHaveProperty('value', 'Старое');
    expect(screen.getByTestId('tools-settings')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('preset-editor-save'));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0]).toEqual({
      title: 'Старое',
      summary: 'старое описание',
      body: 'старый текст',
      settings: { enabled_tools: ['view_image'], alien: 1 },
    });
  });

  test('ошибка сохранения остаётся на экране', async () => {
    const onSave = mock(() => Promise.reject(new Error('permission denied')));
    renderEditor({ onSave });
    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'Олд' } });
    fireEvent.change(screen.getByLabelText('Промпт'), { target: { value: 'Ты олд...' } });
    fireEvent.click(screen.getByTestId('preset-editor-save'));

    await waitFor(() =>
      expect(screen.getByTestId('preset-editor-error')).toHaveTextContent('permission denied'),
    );
  });
});
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd frontend && bun test src/__tests__/preset-editor.test.tsx`
Expected: FAIL — модуль не существует.

- [ ] **Step 3: Написать компонент**

Создать `frontend/src/components/presets/PresetEditorDialog.tsx`:

```tsx
'use client';

import { useEffect, useState } from 'react';
import { Modal } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ToolsSettings } from '@/components/agent/ToolsSettings';
import { readEnabledTools, mergeEnabledTools } from '@/lib/tools/agentTools';
import type { PresetDraft } from '@/hooks/usePresetMutations';

/** Существующий пресет для редактирования. */
export interface PresetEditorInitial {
  id: string;
  title: string;
  summary: string;
  body: string;
  settings: Record<string, unknown> | null;
}

/**
 * Создание и правка своего пресета. Сохранение отдаётся странице через
 * `onSave` (внутри — `mutateAsync`), компонент только валидирует и ждёт.
 */
export function PresetEditorDialog({
  isOpen,
  onClose,
  initial,
  onSave,
}: {
  isOpen: boolean;
  onClose: () => void;
  initial?: PresetEditorInitial | null;
  onSave: (draft: PresetDraft) => Promise<void>;
}) {
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [body, setBody] = useState('');
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      setTitle(initial?.title ?? '');
      setSummary(initial?.summary ?? '');
      setBody(initial?.body ?? '');
      setSettings(initial?.settings ?? null);
      setError(null);
      setSaving(false);
    }
  }, [isOpen, initial]);

  const enabledTools = readEnabledTools(settings);
  const canSave = title.trim().length > 0 && body.trim().length > 0;

  const handleSave = async () => {
    if (!canSave || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSave({
        title: title.trim(),
        summary: summary.trim(),
        body: body,
        settings: settings,
      });
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось сохранить пресет');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={initial ? 'Правка пресета' : 'Новый пресет'} size="lg">
      <form
        className="space-y-4"
        data-testid="preset-editor"
        onSubmit={(event) => {
          event.preventDefault();
          void handleSave();
        }}
      >
        <div className="space-y-1">
          <label htmlFor="preset-editor-title" className="font-mono text-xs text-muted-foreground">
            Название
          </label>
          <Input
            id="preset-editor-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Как назовёшь характер"
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="preset-editor-summary" className="font-mono text-xs text-muted-foreground">
            Короткое описание
          </label>
          <Input
            id="preset-editor-summary"
            value={summary}
            onChange={(event) => setSummary(event.target.value)}
            placeholder="Одной строкой — что делает Мимик"
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="preset-editor-body" className="font-mono text-xs text-muted-foreground">
            Промпт
          </label>
          <textarea
            id="preset-editor-body"
            value={body}
            onChange={(event) => setBody(event.target.value)}
            rows={8}
            placeholder="Характер для SOUL.md — как в настройках мимика"
            className="w-full rounded-sm border border-border bg-background/60 p-3 font-mono text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
        <div className="space-y-1">
          <p className="font-mono text-xs text-muted-foreground">Настройки инструментов</p>
          <ToolsSettings
            value={enabledTools}
            onChange={(next) => setSettings(mergeEnabledTools(settings ?? {}, next))}
          />
        </div>

        {error && (
          <p role="alert" data-testid="preset-editor-error" className="font-mono text-xs text-crimson-400">
            {error}
          </p>
        )}

        <div className="flex items-center justify-end gap-3">
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" size="sm" disabled={!canSave || saving} data-testid="preset-editor-save">
            {saving ? 'Сохраняю…' : initial ? 'Сохранить' : 'Создать'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
```

- [ ] **Step 4: Запустить тесты**

Run: `cd frontend && bun test src/__tests__/preset-editor.test.tsx && bun run typecheck`
Expected: PASS, typecheck без ошибок.

- [ ] **Step 5: Коммит**

```bash
git add frontend/src/components/presets/PresetEditorDialog.tsx frontend/src/__tests__/preset-editor.test.tsx
git commit -m "feat(frontend): preset editor dialog"
```

---

### Task 7: Меню мимика — секции официальных, своих и избранного

**Files:**
- Modify: `frontend/src/components/agent/PresetPicker.tsx`
- Test: `frontend/src/__tests__/preset-picker.test.tsx` (обновить фикстуры и добавить тесты секций)

**Interfaces:**
- Consumes: `PromptPresetRow` (+ `owner_id`, `published_at`), `PresetFavoriteRow`, `usePresetFavorites`, `readEnabledTools`.
- Produces: диалог показывает три секции — «Официальные», «Мои», «Избранное»; живое избранное читает текущую версию пресета, замороженное — `frozen_*`; выбор и применение по прежнему отдают `AppliedPromptPreset`.

- [ ] **Step 1: Обновить падающие тесты**

В `frontend/src/__tests__/preset-picker.test.tsx`:
1. В существующую фикстуру `PRESETS` и `renderDialog` добавить `favorites: []` (новое обязательное свойство диалога) и поля `owner_id: null, published_at: null` в строки.
2. Добавить тесты:

```tsx
import type { PresetFavoriteRow } from '@/types';

const FAVORITE: PresetFavoriteRow = {
  id: 'fav-1',
  preset_id: 'pub-id',
  frozen_title: null,
  frozen_summary: null,
  frozen_body: '',
  frozen_settings: null,
  frozen_at: null,
  created_at: '2026-10-11T00:00:00Z',
  updated_at: '2026-10-11T00:00:00Z',
};

const FROZEN: PresetFavoriteRow = {
  id: 'fav-2',
  preset_id: null,
  frozen_title: 'Замороженный',
  frozen_summary: 'копия',
  frozen_body: 'текст копии',
  frozen_settings: null,
  frozen_at: '2026-10-11T01:00:00Z',
  created_at: '2026-10-11T00:00:00Z',
  updated_at: '2026-10-11T00:00:00Z',
};
```

```tsx
test('секции: официальные, свои и избранное', () => {
  renderDialog({
    presets: [
      { ...PRESETS[0], owner_id: null, published_at: null },
      { ...PRESETS[1], owner_id: 'me', published_at: '2026-10-11T00:00:00Z' },
    ],
    favorites: [FAVORITE, FROZEN],
  });
  expect(screen.getByText('Официальные')).toBeInTheDocument();
  expect(screen.getByText('Мои')).toBeInTheDocument();
  expect(screen.getByText('Избранное')).toBeInTheDocument();
});

test('живое избранное показывает текущую версию пресета', () => {
  renderDialog({
    presets: [{ ...PRESETS[0], id: 'pub-id', owner_id: 'other', published_at: '2026-10-11T00:00:00Z', body: 'живой текст' }],
    favorites: [FAVORITE],
  });
  fireEvent.click(screen.getByRole('option', { name: /живой текст/ }));
  expect(screen.getByTestId('preset-body')).toHaveTextContent('живой текст');
});

test('замороженное избранное показывает снимок, а не живую строку', () => {
  renderDialog({
    presets: [{ ...PRESETS[0], id: 'dead-id', owner_id: 'other', published_at: '2026-10-11T00:00:00Z', body: 'живой текст' }],
    favorites: [{ ...FROZEN, frozen_body: 'снимок текста' }],
  });
  fireEvent.click(screen.getByRole('option', { name: /Замороженный/ }));
  expect(screen.getByTestId('preset-body')).toHaveTextContent('снимок текста');
});

test('пустые секции не рендерятся', () => {
  renderDialog({ presets: [{ ...PRESETS[0], owner_id: null, published_at: null }], favorites: [] });
  expect(screen.getByText('Официальные')).toBeInTheDocument();
  expect(screen.queryByText('Мои')).not.toBeInTheDocument();
  expect(screen.queryByText('Избранное')).not.toBeInTheDocument();
});
```

(Точные имена строк `PRESETS` подстрой под текущую фикстуру файла — суть: в секцию «Мои» должна попасть строка с `owner_id` пользователя, в «Официальные» — с `owner_id: null`.)

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd frontend && bun test src/__tests__/preset-picker.test.tsx`
Expected: FAIL — у диалога нет свойства `favorites` и секций.

- [ ] **Step 3: Реализовать секции**

В `frontend/src/components/agent/PresetPicker.tsx`:

1. Импорты дополнить:

```tsx
import { usePresetFavorites } from '@/hooks/usePresetFavorites';
import type { PresetFavoriteRow } from '@/types';
```

2. В `PresetPicker` добавить избранные данные и передать их вниз:

```tsx
const { data: favorites, isLoading: favoritesLoading } = usePresetFavorites();
```

В `PresetPickerDialog` пропсы дополнить:

```tsx
favorites: PresetFavoriteRow[];
favoritesLoading?: boolean;
```

3. В `PresetPickerDialog` заменить плоский список на единый список записей с секциями. Внутри диалога перед рендером:

```tsx
// Единый список выбора: официальные (owner_id null), свои и избранное.
// Живое избранное (preset_id задан) показывает текущую версию пресета,
// замороженное — снимок из favorite.
const userId = ... // см. ниже
```

Чтобы отличить «свои» от чужих витринных, диалогу нужен id пользователя. Получение `auth.getUser()` — асинхронное; проще в `PresetPicker` один раз получить id и передать пропсом:

```tsx
const [userId, setUserId] = useState<string | null>(null);
useEffect(() => {
  let cancelled = false;
  getSupabaseClient().auth.getUser().then(({ data }) => {
    if (!cancelled) setUserId(data.user?.id ?? null);
  });
  return () => {
    cancelled = true;
  };
}, []);
```

Импорт: `import { getSupabaseClient } from '@/lib/supabase/client';` и `useEffect` из react.

В диалоге собираем записи:

```tsx
interface PickerEntry {
  key: string;
  title: string;
  summary: string;
  body: string;
  settings: Record<string, unknown> | null;
  section: 'official' | 'mine' | 'favorites';
}

const sections = useMemo(() => {
  const liveById = new Map(presets.map((preset) => [preset.id, preset]));
  const official: PickerEntry[] = [];
  const mine: PickerEntry[] = [];
  for (const preset of presets) {
    if (preset.owner_id !== null && preset.owner_id !== userId) continue; // чужой витринный — без избранного в меню не попадает
    const entry: PickerEntry = {
      key: `preset:${preset.id}`,
      title: preset.title,
      summary: preset.summary,
      body: preset.body,
      settings: preset.settings,
      section: preset.owner_id === null ? 'official' : 'mine',
    };
    if (preset.owner_id === null) official.push(entry);
    else mine.push(entry);
  }
  mine.sort((a, b) => a.key.localeCompare(b.key));
  const favorites: PickerEntry[] = favoritesList.map((favorite) => {
    const source = favorite.preset_id ? liveById.get(favorite.preset_id) : undefined;
    return {
      key: `fav:${favorite.id}`,
      title: source?.title ?? favorite.frozen_title ?? 'Без названия',
      summary: source?.summary ?? favorite.frozen_summary ?? '',
      body: source ? source.body : favorite.frozen_body,
      settings: source ? source.settings : favorite.frozen_settings,
      section: 'favorites' as const,
    };
  });
  const visible = { official, mine, favorites };
  return visible;
}, [presets, favoritesList]);
```

(`favoritesList` — пропс `favorites`; переименование локальное.)

4. Рендер списка — три блока-секции в том же `listbox`; заголовок секции — `<p className="...">`, опции — как раньше, но `role="option"` и выбор по `entry.key`. Состояние выбора заменить `selectedSlug: string | null` → `selectedKey: string | null`; `selected` — `sections.official.concat(sections.mine, sections.favorites).find((e) => e.key === selectedKey) ?? ...` — первая запись официальных, затем своих, затем избранных.

```tsx
const flat = [...sections.official, ...sections.mine, ...sections.favorites];
const selected = flat.find((entry) => entry.key === selectedKey) ?? flat[0] ?? null;
```

5. Заголовок секции и опции:

```tsx
{(
  [
    ['Официальные', sections.official],
    ['Мои', sections.mine],
    ['Избранное', sections.favorites],
  ] as const
).map(([label, entries]) =>
  entries.length === 0 ? null : (
    <div key={label} data-testid={`picker-section-${label}`}>
      <p className="px-3 pb-1 pt-2 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      {entries.map((entry) => (
        <button
          key={entry.key}
          type="button"
          role="option"
          aria-selected={selected?.key === entry.key}
          onClick={() => handleSelect(entry.key)}
          className={cn(/* как раньше */)}
        >
          <span className="block font-mono text-xs text-foreground">{entry.title}</span>
          <span className="block font-mono text-[11px] text-muted-foreground">{entry.summary}</span>
        </button>
      ))}
    </div>
  ),
)}
```

`handleSelect` принимает `entry.key`. `handleApply` берёт поля из `selected`.

6. Пустое состояние: `flat.length === 0` → строка «Пресетов пока нет» (как раньше). Пока `favoritesLoading` — можно просто не показывать секцию (favorites ещё грузятся) — скелетон не обязателен: основной список официальных грузится тем же `isLoading`.

- [ ] **Step 4: Запустить тесты**

Run: `cd frontend && bun test src/__tests__/preset-picker.test.tsx && bun run typecheck`
Expected: PASS (все старые тесты диалога с обновлёнными пропсами + новые секционные).

- [ ] **Step 5: Коммит**

```bash
git add frontend/src/components/agent/PresetPicker.tsx frontend/src/__tests__/preset-picker.test.tsx
git commit -m "feat(frontend): preset picker sections with favorites"
```

---

### Task 8: Страница каталога `/presets` и пункт меню

**Files:**
- Create: `frontend/src/app/(dashboard)/presets/page.tsx`
- Create: `frontend/src/lib/presets/catalog.ts` (чистая логика витрины)
- Create: `frontend/src/hooks/usePresetAuthors.ts`
- Modify: `frontend/src/components/layout/Sidebar.tsx:29-31` (mainNav)
- Test: `frontend/src/__tests__/preset-catalog-logic.test.ts`

**Interfaces:**
- Consumes: `usePromptPresets`, `usePresetFavorites`, `usePresetAuthors`, все мутации из Task 5, `PresetEditorDialog`, `readEnabledTools`.
- Produces: страница с тремя вкладками (Магазин / Мои / Избранное), поиск в магазине, карточки с действиями; чистые функции `buildCatalogEntries` и `filterCatalog` для тестов; пункт «Пресеты» в сайдбаре.

- [ ] **Step 1: Написать падающие тесты чистой логики**

Создать `frontend/src/__tests__/preset-catalog-logic.test.ts`:

```ts
import { describe, expect, test } from 'bun:test';
import { buildCatalogEntries, filterCatalog } from '@/lib/presets/catalog';
import type { PromptPresetRow } from '@/types';

const OFFICIAL: PromptPresetRow = {
  id: 'a', slug: 'rage_comments', title: 'Рейджбейт в комментариях', summary: 'спорит',
  body: 'т', settings: null, sort_order: 1, is_active: true,
  owner_id: null, published_at: null, created_at: '2026-09-20T00:00:00Z', updated_at: '2026-09-20T00:00:00Z',
};
const MINE_DRAFT: PromptPresetRow = {
  ...OFFICIAL, id: 'b', slug: 'u_b', title: 'Мой черновик', summary: 'черновик',
  owner_id: 'me', published_at: null, sort_order: 0,
};
const MINE_PUBLISHED: PromptPresetRow = {
  ...OFFICIAL, id: 'c', slug: 'u_c', title: 'Мой в магазине', summary: 'выложен',
  owner_id: 'me', published_at: '2026-10-11T00:00:00Z', sort_order: 0,
};
const FOREIGN_PUBLISHED: PromptPresetRow = {
  ...OFFICIAL, id: 'd', slug: 'u_d', title: 'Чужой выложенный', summary: 'магазин',
  owner_id: 'other', published_at: '2026-10-11T00:00:00Z', sort_order: 0,
};

describe('buildCatalogEntries', () => {
  test('магазин: официальные плюс чужие выложенные, без своих черновиков', () => {
    const entries = buildCatalogEntries(
      [OFFICIAL, MINE_DRAFT, MINE_PUBLISHED, FOREIGN_PUBLISHED],
      'me',
      new Map([['other', 'Сосед']]),
    );
    const store = entries.store;
    expect(store.map((entry) => entry.id)).toEqual(['a', 'd']);
    expect(store[1].authorName).toBe('Сосед');
    expect(store[0].isOfficial).toBe(true);
    expect(store[1].isOfficial).toBe(false);
  });

  test('мои: черновики и выложенные', () => {
    const entries = buildCatalogEntries(
      [OFFICIAL, MINE_DRAFT, MINE_PUBLISHED, FOREIGN_PUBLISHED],
      'me',
      new Map(),
    );
    expect(entries.mine.map((entry) => entry.id)).toEqual(['b', 'c']);
  });
});

describe('filterCatalog', () => {
  test('ищет по названию и описанию без учёта регистра', () => {
    const entries = buildCatalogEntries([OFFICIAL, FOREIGN_PUBLISHED], 'me', new Map());
    expect(filterCatalog(entries.store, 'рейдж')).toEqual([entries.store[0]]);
    expect(filterCatalog(entries.store, 'МАГАЗИН')).toEqual([entries.store[1]]);
    expect(filterCatalog(entries.store, '')).toEqual(entries.store);
  });
});
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd frontend && bun test src/__tests__/preset-catalog-logic.test.ts`
Expected: FAIL — модуль не существует.

- [ ] **Step 3: Написать чистую логику и хук авторов**

Создать `frontend/src/lib/presets/catalog.ts`:

```ts
import type { PromptPresetRow, PresetFavoriteRow } from '@/types';

/** Карточка каталога: витрина или «мои». */
export interface CatalogEntry {
  id: string;
  title: string;
  summary: string;
  body: string;
  settings: Record<string, unknown> | null;
  authorId: string | null;
  authorName: string | null;
  published: boolean;
  isOfficial: boolean;
}

export interface CatalogEntries {
  store: CatalogEntry[];
  mine: CatalogEntry[];
}

/**
 * Магазин — официальные активные плюс чужие выложенные; «Мои» — свои
 * черновики и выложенные. Официальные впереди, дальше по времени создания.
 */
export function buildCatalogEntries(
  presets: PromptPresetRow[],
  userId: string | null,
  authorNames: Map<string, string | null>,
): CatalogEntries {
  const entry = (preset: PromptPresetRow): CatalogEntry => ({
    id: preset.id,
    title: preset.title,
    summary: preset.summary,
    body: preset.body,
    settings: preset.settings,
    authorId: preset.owner_id,
    authorName: preset.owner_id
      ? preset.owner_id === userId
        ? null
        : authorNames.get(preset.owner_id) ?? null
      : null,
    published: preset.published_at !== null,
    isOfficial: preset.owner_id === null,
  });

  const store = presets
    .filter((preset) => preset.owner_id === null || (preset.published_at !== null && preset.owner_id !== userId))
    .map(entry)
    .sort((a, b) => {
      if (a.isOfficial !== b.isOfficial) return a.isOfficial ? -1 : 1;
      return a.title.localeCompare(b.title, 'ru');
    });

  const mine = presets
    .filter((preset) => preset.owner_id !== null && preset.owner_id === userId)
    .map(entry)
    .sort((a, b) => a.title.localeCompare(b.title, 'ru'));

  return { store, mine };
}

/** Карточки избранного для страницы: живые и замороженные. */
export interface FavoriteEntry {
  favoriteId: string;
  title: string;
  summary: string;
  body: string;
  frozen: boolean;
}

export function buildFavoriteEntries(
  favorites: PresetFavoriteRow[],
  presets: PromptPresetRow[],
): FavoriteEntry[] {
  const liveById = new Map(presets.map((preset) => [preset.id, preset]));
  return favorites
    .map((favorite) => {
      const source = favorite.preset_id ? liveById.get(favorite.preset_id) : undefined;
      return {
        favoriteId: favorite.id,
        title: source?.title ?? favorite.frozen_title ?? 'Без названия',
        summary: source?.summary ?? favorite.frozen_summary ?? '',
        body: source ? source.body : favorite.frozen_body,
        frozen: !source,
      };
    })
    .sort((a, b) => a.title.localeCompare(b.title, 'ru'));
}

/** Поиск по названию и описанию без учёта регистра. */
export function filterCatalog(entries: CatalogEntry[], query: string): CatalogEntry[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return entries;
  return entries.filter(
    (entry) =>
      entry.title.toLowerCase().includes(needle) ||
      entry.summary.toLowerCase().includes(needle),
  );
}
```

Создать `frontend/src/hooks/usePresetAuthors.ts`:

```ts
'use client';

import { useQuery } from '@tanstack/react-query';
import { getSupabaseClient, type SupabaseBrowserClient } from '@/lib/supabase/client';
import { queryKeys } from '@/lib/queryClient';

export interface PresetAuthor {
  id: string;
  display_name: string | null;
}

/**
 * Авторы выложенных пресетов из представления preset_authors: только
 * display_name, без почты.
 */
export async function fetchPresetAuthors(
  client: SupabaseBrowserClient,
): Promise<PresetAuthor[]> {
  const { data, error } = await client.from('preset_authors').select('*');
  if (error) throw new Error(error.message);
  return (data ?? []) as PresetAuthor[];
}

export function usePresetAuthors() {
  return useQuery({
    queryKey: queryKeys.presets.authors(),
    queryFn: () => fetchPresetAuthors(getSupabaseClient()),
  });
}
```

И добавить в `queryClient.ts` в `presets`:

```ts
    authors: () => [...queryKeys.presets.all, 'authors'] as const,
```

- [ ] **Step 4: Логика зелёная, страница — Step 5**

Run: `cd frontend && bun test src/__tests__/preset-catalog-logic.test.ts`
Expected: PASS.

- [ ] **Step 5: Написать страницу**

Создать `frontend/src/app/(dashboard)/presets/page.tsx`:

```tsx
'use client';

import { useEffect, useMemo, useState } from 'react';
import { Library, Plus, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/card';
import { PresetEditorDialog } from '@/components/presets/PresetEditorDialog';
import {
  buildCatalogEntries,
  buildFavoriteEntries,
  filterCatalog,
  type CatalogEntry,
} from '@/lib/presets/catalog';
import { readEnabledTools } from '@/lib/tools/agentTools';
import { queryKeys } from '@/lib/queryClient';
import { useQueryClient } from '@tanstack/react-query';
import {
  useCreatePreset,
  useDeletePreset,
  useFavoritePreset,
  usePublishPreset,
  useUnfavoriteByPreset,
  useUnpublishPreset,
  useUpdatePreset,
} from '@/hooks/usePresetMutations';
import { usePresetFavorites } from '@/hooks/usePresetFavorites';
import { usePresetAuthors } from '@/hooks/usePresetAuthors';
import { usePromptPresets } from '@/hooks/usePromptPresets';
import { getSupabaseClient } from '@/lib/supabase/client';
import type { PresetDraft } from '@/hooks/usePresetMutations';
import { cn } from '@/lib/utils';

type TabKey = 'store' | 'mine' | 'favorites';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'store', label: 'Магазин' },
  { key: 'mine', label: 'Мои' },
  { key: 'favorites', label: 'Избранное' },
];

export default function PresetsPage() {
  const qc = useQueryClient();
  const { data: presets, isLoading, isError } = usePromptPresets();
  const { data: favorites } = usePresetFavorites();
  const { data: authors } = usePresetAuthors();

  const [tab, setTab] = useState<TabKey>('store');
  const [search, setSearch] = useState('');
  const [userId, setUserId] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<CatalogEntry | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSupabaseClient().auth.getUser().then(({ data }) => {
      if (!cancelled) setUserId(data.user?.id ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const create = useCreatePreset();
  const update = useUpdatePreset();
  const publish = usePublishPreset();
  const unpublish = useUnpublishPreset();
  const remove = useDeletePreset();
  const favorite = useFavoritePreset();
  const unfavoriteByPreset = useUnfavoriteByPreset();

  const authorNames = useMemo(
    () => new Map((authors ?? []).map((author) => [author.id, author.display_name])),
    [authors],
  );

  const entries = useMemo(
    () => buildCatalogEntries(presets ?? [], userId, authorNames),
    [presets, userId, authorNames],
  );
  const favoriteEntries = useMemo(
    () => buildFavoriteEntries(favorites ?? [], presets ?? []),
    [favorites, presets],
  );

  // Карта preset_id → id избранного: убирать живое избранное можно по пресету.
  const favoriteIdByPreset = useMemo(
    () => new Map((favorites ?? []).filter((f) => f.preset_id).map((f) => [f.preset_id, f.id])),
    [favorites],
  );

  const storeVisible = filterCatalog(entries.store, search);

  const handleSave = async (draft: PresetDraft) => {
    if (editing) {
      await update.mutateAsync({ id: editing.id, draft });
      setEditing(null);
    } else {
      await create.mutateAsync(draft);
    }
  };

  const openEditor = (entry: CatalogEntry | null) => {
    setEditing(entry);
    setEditorOpen(true);
  };

  const busy = create.isPending || update.isPending;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Library className="h-5 w-5 text-primary" aria-hidden="true" />
          <h1 className="text-xl font-semibold text-foreground">Пресеты</h1>
        </div>
        <Button size="sm" onClick={() => openEditor(null)} data-testid="open-preset-editor">
          <Plus className="mr-1 h-4 w-4" aria-hidden="true" />
          Создать пресет
        </Button>
      </header>

      <nav className="flex gap-1 border-b border-border" aria-label="Разделы каталога">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setTab(item.key)}
            data-testid={`presets-tab-${item.key}`}
            aria-current={tab === item.key}
            className={cn(
              'rounded-t-sm px-4 py-2 font-mono text-xs transition-colors duration-150',
              tab === item.key
                ? 'border-b-2 border-primary text-primary'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {tab === 'store' && (
        <div className="space-y-4">
          <div className="relative max-w-sm">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Поиск по названию и описанию"
              data-testid="presets-store-search"
              className="pl-9"
            />
          </div>
          <StoreList
            entries={storeVisible}
            isLoading={isLoading}
            isError={isError}
            favoriteIdByPreset={favoriteIdByPreset}
            onFavorite={(id) => favorite.mutate(id)}
            onUnfavorite={(presetId) => unfavoriteByPreset.mutate(presetId)}
          />
        </div>
      )}

      {tab === 'mine' && (
        <MineList
          entries={entries.mine}
          isLoading={isLoading}
          isError={isError}
          confirmDeleteId={confirmDeleteId}
          busy={busy}
          onEdit={openEditor}
          onPublish={(id) => publish.mutate(id)}
          onUnpublish={(id) => unpublish.mutate(id)}
          onDelete={(id) => {
            if (confirmDeleteId === id) {
              remove.mutate(id);
              setConfirmDeleteId(null);
            } else {
              setConfirmDeleteId(id);
            }
          }}
        />
      )}

      {tab === 'favorites' && <FavoritesList entries={favoriteEntries} />}

      <PresetEditorDialog
        isOpen={editorOpen}
        onClose={() => {
          setEditorOpen(false);
          setEditing(null);
        }}
        initial={
          editing
            ? {
                id: editing.id,
                title: editing.title,
                summary: editing.summary,
                body: editing.body,
                settings: editing.settings,
              }
            : null
        }
        onSave={handleSave}
      />
    </div>
  );
}
```

Плюс подкомпоненты `StoreList`, `MineList`, `FavoritesList` в том же файле (ниже главной функции). `StoreList` — карточки с названием, описанием, автором («Без имени» при пустом), меткой инструментов (`Настроит инструменты: N из M` через `readEnabledTools`), кнопкой «В избранное»/«В избранном» (`data-testid="preset-favorite"`/`"preset-unfavorite"`), для официальных без кнопки избранного. `MineList` — карточки с меткой «Черновик»/«В магазине» и кнопками `data-testid="preset-edit"`, `"preset-publish"`, `"preset-unpublish"`, `"preset-delete"` (двухступенчатое подтверждение: подпись меняется на «Точно удалить?»). `FavoritesList` — карточки с меткой «Копия» у замороженных. Состояния: скелетоны при `isLoading`, ошибка с повтором (`role="alert"`), пустые вкладки: «Своих пресетов пока нет», «В избранном пока ничего нет», в магазине — «Ничего не найдено» при непустом поиске, «Пресетов пока нет» при пустом.

Реализация подкомпонентов (в том же файле ниже `PresetPage`):

```tsx
function ToolBadge({ settings }: { settings: Record<string, unknown> | null }) {
  const enabled = readEnabledTools(settings);
  if (enabled === null) return null;
  return (
    <p className="font-mono text-[11px] text-muted-foreground">
      Настроит инструменты: {enabled.length} из {TOOL_INFO.length}
    </p>
  );
}

function StoreList({
  entries,
  isLoading,
  isError,
  favoriteIdByPreset,
  onFavorite,
  onUnfavorite,
}: {
  entries: CatalogEntry[];
  isLoading: boolean;
  isError: boolean;
  favoriteIdByPreset: Map<string, string>;
  onFavorite: (presetId: string) => void;
  onUnfavorite: (presetId: string) => void;
}) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }
  if (isError) {
    return <p role="alert" className="font-mono text-xs text-crimson-400">Не удалось загрузить каталог</p>;
  }
  if (entries.length === 0) {
    return <p className="font-mono text-xs text-muted-foreground">Пресетов пока нет</p>;
  }
  return (
    <div className="grid gap-3">
      {entries.map((entry) => {
        const favoriteId = favoriteIdByPreset.get(entry.id);
        return (
          <article
            key={entry.id}
            data-testid={`preset-card-${entry.id}`}
            className="rounded-sm border border-border p-4"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-mono text-sm text-foreground">{entry.title}</h2>
              <span className="font-mono text-[11px] text-muted-foreground">
                {entry.isOfficial ? 'Официальный' : entry.authorName ?? 'Без имени'}
              </span>
            </div>
            <p className="mt-1 font-mono text-xs text-muted-foreground">{entry.summary}</p>
            <ToolBadge settings={entry.settings} />
            {!entry.isOfficial && (
              <div className="mt-3">
                {favoriteId ? (
                  <Button variant="ghost" size="sm" onClick={() => onUnfavorite(entry.id)} data-testid="preset-unfavorite">
                    В избранном
                  </Button>
                ) : (
                  <Button variant="ghost" size="sm" onClick={() => onFavorite(entry.id)} data-testid="preset-favorite">
                    В избранное
                  </Button>
                )}
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}

function MineList({
  entries,
  isLoading,
  isError,
  confirmDeleteId,
  busy,
  onEdit,
  onPublish,
  onUnpublish,
  onDelete,
}: {
  entries: CatalogEntry[];
  isLoading: boolean;
  isError: boolean;
  confirmDeleteId: string | null;
  busy: boolean;
  onEdit: (entry: CatalogEntry) => void;
  onPublish: (id: string) => void;
  onUnpublish: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }
  if (isError) {
    return <p role="alert" className="font-mono text-xs text-crimson-400">Не удалось загрузить свои пресеты</p>;
  }
  if (entries.length === 0) {
    return <p className="font-mono text-xs text-muted-foreground">Своих пресетов пока нет</p>;
  }
  return (
    <div className="grid gap-3">
      {entries.map((entry) => (
        <article
          key={entry.id}
          data-testid={`preset-card-${entry.id}`}
          className="rounded-sm border border-border p-4"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-mono text-sm text-foreground">{entry.title}</h2>
            <span className="font-mono text-[11px] text-muted-foreground">
              {entry.published ? 'В магазине' : 'Черновик'}
            </span>
          </div>
          <p className="mt-1 font-mono text-xs text-muted-foreground">{entry.summary}</p>
          <ToolBadge settings={entry.settings} />
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="ghost" size="sm" onClick={() => onEdit(entry)} data-testid="preset-edit">
              Редактировать
            </Button>
            {entry.published ? (
              <Button variant="ghost" size="sm" onClick={() => onUnpublish(entry.id)} data-testid="preset-unpublish">
                Снять с витрины
              </Button>
            ) : (
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => onPublish(entry.id)} data-testid="preset-publish">
                Выложить
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDelete(entry.id)}
              data-testid="preset-delete"
              className="text-crimson-400 hover:text-crimson-300"
            >
              {confirmDeleteId === entry.id ? 'Точно удалить?' : 'Удалить'}
            </Button>
          </div>
        </article>
      ))}
    </div>
  );
}

function FavoritesList({ entries }: { entries: FavoriteEntry[] }) {
  if (entries.length === 0) {
    return <p className="font-mono text-xs text-muted-foreground">В избранном пока ничего нет</p>;
  }
  return (
    <div className="grid gap-3">
      {entries.map((entry) => (
        <article
          key={entry.favoriteId}
          data-testid={`preset-card-${entry.favoriteId}`}
          className="rounded-sm border border-border p-4"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-mono text-sm text-foreground">{entry.title}</h2>
            {entry.frozen && (
              <span data-testid="favorite-frozen" className="font-mono text-[11px] text-amber-400">
                Копия
              </span>
            )}
          </div>
          <p className="mt-1 font-mono text-xs text-muted-foreground">{entry.summary}</p>
        </article>
      ))}
    </div>
  );
}
```

К импортам страницы добавить `TOOL_INFO` и `FavoriteEntry`:

```tsx
import { TOOL_INFO } from '@/lib/tools/toolInfo';
import type { FavoriteEntry } from '@/lib/presets/catalog';
```

`unfavorite` в списке избранного не показываем: убирать из избранного можно и из магазина (кнопка «В избранном»), а в e2e шаг уборки для живой записи тоже идёт через вкладку «Избранное» — тогда `FavoritesList` получает пропсы `onUnfavorite`/`favoriteIdByPreset` и кнопку `data-testid="preset-unfavorite"` в карточке (скрывайте для замороженных копий? нет: замороженную копию тоже можно убрать — кнопка есть всегда, действует по `entry.favoriteId`):

```tsx
function FavoritesList({
  entries,
  onUnfavorite,
}: {
  entries: FavoriteEntry[];
  onUnfavorite: (favoriteId: string) => void;
}) {
  ...
  {entries.map((entry) => (
    <article ...>
      ...
      <div className="mt-3">
        <Button variant="ghost" size="sm" onClick={() => onUnfavorite(entry.favoriteId)} data-testid="preset-unfavorite">
          Убрать из избранного
        </Button>
      </div>
    </article>
  ))}
}
```

И в странице: `{tab === 'favorites' && <FavoritesList entries={favoriteEntries} onUnfavorite={(id) => unfavoritePreset.mutate(id)} />}`, добавив `useUnfavoritePreset` к импортам мутаций и `const unfavorite = useUnfavoritePreset();`. Тогда в e2e уборка читателя кликает `preset-unfavorite` на карточке вкладки «Избранное» — как в сценарии Task 9.

- [ ] **Step 6: Пункт в сайдбаре**

В `frontend/src/components/layout/Sidebar.tsx`:

```tsx
import {
  LayoutDashboard,
  Bot,
  Library,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Plus,
  Zap,
  X,
} from 'lucide-react';

const mainNav: NavItem[] = [
  { href: '/dashboard', label: 'Главная', icon: LayoutDashboard, exact: true },
  { href: '/presets', label: 'Пресеты', icon: Library, exact: true },
];
```

- [ ] **Step 7: Проверить фронт**

Run: `cd frontend && bun test && bun run typecheck && bunx next lint`
Expected: всё зелёное.

- [ ] **Step 8: Коммит**

```bash
git add frontend/src/app/(dashboard)/presets/page.tsx frontend/src/lib/presets/catalog.ts frontend/src/hooks/usePresetAuthors.ts frontend/src/components/layout/Sidebar.tsx frontend/src/__tests__/preset-catalog-logic.test.ts frontend/src/lib/queryClient.ts
git commit -m "feat(frontend): preset catalog page and sidebar entry"
```

---

### Task 9: E2E — витрина, избранное и заморозка в браузере

**Files:**
- Create: `tests/e2e/test_preset_catalog.py`

**Interfaces:**
- Consumes: `persona_page` (персоны `full` — автор, `flow` — читатель), слот учёток.
- Produces: сценарий «создать → выложить → сохранить в избранное → применить у мимика → снять → копия остаётся».

- [ ] **Step 1: Написать e2e-сценарий**

Создать `tests/e2e/test_preset_catalog.py`:

```python
"""Каталог пресетов в браузере (issue #67)."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

TITLE = "Ламповый олд"
SUMMARY = "говорит как с туса 2007"
PROMPT = "Ты ламповый олд интернета и помнишь, как звучали модемы."


class TestPresetCatalog:
    def test_create_publish_favorite_and_freeze(
        self, persona_page: Callable[..., Page], users: dict
    ) -> None:
        author = persona_page("full")
        reader = persona_page("flow")

        # Автор создаёт пресет.
        author.goto("/presets")
        author.get_by_test_id("open-preset-editor").click()
        editor = author.get_by_role("dialog")
        editor.get_by_label("Название").fill(TITLE)
        editor.get_by_label("Короткое описание").fill(SUMMARY)
        editor.get_by_label("Промпт").fill(PROMPT)
        editor.get_by_test_id("preset-editor-save").click()
        expect(editor).to_be_hidden()
        mine_card = author.get_by_test_id(re.compile("preset-card-")).filter(has_text=TITLE)
        expect(mine_card.get_by_text("Черновик")).to_be_visible()

        # Выкладка: карточка переезжает в «Магазин».
        mine_card.get_by_test_id("preset-publish").click()
        author.get_by_test_id("presets-tab-store").click()
        store_card = author.get_by_test_id(re.compile("preset-card-")).filter(has_text=TITLE)
        expect(store_card.get_by_text("В магазине")).to_be_visible()

        # Читатель видит пресет в магазине и сохраняет в избранное.
        reader.goto("/presets")
        reader.get_by_test_id("presets-store-search").fill(TITLE)
        foreign_card = reader.get_by_test_id(re.compile("preset-card-")).filter(has_text=TITLE)
        expect(foreign_card).to_be_visible()
        foreign_card.get_by_test_id("preset-favorite").click()

        # Избранное попадает в меню у мимика.
        reader.get_by_test_id("presets-tab-favorites").click()
        expect(reader.get_by_text(TITLE)).to_be_visible()
        reader.goto("/dashboard")
        reader.get_by_test_id("open-presets").click()
        option = reader.get_by_role("option", name=re.compile(TITLE))
        option.click()
        expect(reader.get_by_test_id("preset-body")).to_contain_text(PROMPT)
        reader.get_by_role("button", name="Отмена").click()

        # Автор снимает с витрины — у читателя остаётся замороженная копия.
        author.goto("/presets")
        author.get_by_test_id("presets-tab-mine").click()
        mine_card = author.get_by_test_id(re.compile("preset-card-")).filter(has_text=TITLE)
        mine_card.get_by_test_id("preset-unpublish").click()

        reader.goto("/presets")
        reader.get_by_test_id("presets-tab-favorites").click()
        expect(reader.get_by_text("Копия")).to_be_visible()

        # Уборка: читатель снимает избранное, автор удаляет пресет.
        favorite_card = reader.get_by_test_id(re.compile("preset-card-")).filter(has_text=TITLE)
        favorite_card.get_by_test_id("preset-unfavorite").click()
        author.goto("/presets")
        author.get_by_test_id("presets-tab-mine").click()
        mine_card = author.get_by_test_id(re.compile("preset-card-")).filter(has_text=TITLE)
        mine_card.get_by_test_id("preset-delete").click()
        mine_card.get_by_test_id("preset-delete").click()
        expect(author.get_by_test_id(re.compile("preset-card-")).filter(has_text=TITLE)).to_have_count(0)
```

Метки карточек (Черновик/В магазине/Копия) должны иметь точные тексты из Task 8 — сверяй и правь тест, если формулировки отличаются; главное — фиксированные `data-testid` совпадают.

- [ ] **Step 2: Проверить, что сценарий падает/проходит ожидаемо**

Run: `uv run pytest tests/e2e/test_preset_catalog.py -m e2e -v`
Expected: сценарий зелёный на готовом коде Tasks 1–8; падение на этом шаге — повод чинить код Tasks 5–8, а не тест.

- [ ] **Step 3: Коммит**

```bash
git add tests/e2e/test_preset_catalog.py
git commit -m "test(e2e): preset catalog journey"
```

---

### Task 10: Полный pre-PR прогон и передача пользователю

**Files:** без правок.

- [ ] **Step 1: Полный набор бэкенда**

Run: `uv sync --locked --all-groups && uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -m "not db and not e2e and not real_tg and not real_llm" -W error -q`
Expected: всё зелёное.

- [ ] **Step 2: Полный набор фронтенда**

Run (из `frontend/`): `bun install --frozen-lockfile && bunx next lint && bun run typecheck && bun test`
Expected: всё зелёное.

- [ ] **Step 3: DB-тесты**

Run: `uv run pytest -m db -W error -q`
Expected: всё зелёное (тестовая база поднята).

- [ ] **Step 4: Остановка для пользователя**

Не открывать PR: сначала пользователь проверяет приложение локально (создать/выложить/снять пресет, избранное у мимика) и подтверждает, что работает. После подтверждения — `git push` и `gh pr create` с описанием по Conventional Commits, затем следить за `gh pr checks`.

---

## Self-review чеклист (уже пройден при составлении)

- Спека покрыта: витрина (Tasks 1, 3, 8), свои/черновики (Tasks 1, 6, 8), избранное и заморозка (Tasks 2, 3, 5, 7, 8, 9), меню мимика (Task 7), инструменты (Task 6), имена авторов (Task 3, 8).
- Официальные пресеты защищены политиками и триггером (Task 1), покрыты тестами.
- Конфликт «ошибка политики vs raise триггера» в тестах снят через кортеж `DENIED` только там, где источник неясен; где источник ясен (грант колонки) — точный тип.
- e2e чистит за собой: unfavorite + delete, чтобы общий слот не замусоривался.
