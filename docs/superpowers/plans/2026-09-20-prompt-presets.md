# Prompt Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать пользователю применять готовые пресеты промптов к SOUL.md агента — на вкладке «Настройки» и на шаге «Характер» в онбординге.

**Architecture:** Пресеты лежат в новой таблице Supabase `public.prompt_presets`, засеянной миграцией, и читаются фронтом напрямую под RLS — ровно как `useAgentDetails` читает `agents`. Применение пресета кладёт текст в состояние формы; сохранение остаётся на существующих кнопках. Python-часть не меняется вообще.

**Tech Stack:** Supabase (Postgres + RLS, Supabase CLI), Next.js 14 + React 18, TanStack Query v5, TypeScript, `bun test` + Testing Library, pytest + asyncpg (integration), Playwright через pytest (e2e).

**Spec:** `docs/superpowers/specs/2026-09-20-prompt-presets-design.md`

## Global Constraints

- Тексты пресетов берутся **дословно** из спеки, раздел «Тексты пресетов». Не редактировать, не сокращать, не добавлять своих ограничений.
- Слаги ровно эти: `rage_comments`, `sasavot_fan`, `magnum_normie`, `battalion`.
- Бэкенд (`src/mimic42/**`) не трогаем. Новых эндпоинтов FastAPI нет.
- Применение пресета не пишет в базу само по себе и не перезапускает агента.
- Пользователь не может создавать и редактировать пресеты: политик `insert`/`update`/`delete` нет.
- Все пользовательские строки — на русском, как в остальном интерфейсе.
- Команды фронта запускаются из `frontend/`: `bun test`, `bun run typecheck`, `bun run lint`.
- Python-команды — через `uv run`. Интеграционные тесты: `uv run pytest -m db`.

---

### Task 1: Таблица `prompt_presets` с сидом

**Files:**
- Create: `supabase/migrations/20260920085947_add_prompt_presets.sql`
- Create: `tests/integration/test_prompt_presets.py`
- Modify: `frontend/src/types/supabase.ts` (перегенерируется командой, руками не править)

**Interfaces:**
- Consumes: ничего.
- Produces: таблица `public.prompt_presets` с колонками `id uuid`, `slug text`, `title text`, `summary text`, `body text`, `sort_order integer`, `is_active boolean`, `created_at timestamptz`, `updated_at timestamptz`. Четыре активные строки со слагами `rage_comments` (sort_order 1), `sasavot_fan` (2), `magnum_normie` (3), `battalion` (4). В `frontend/src/types/supabase.ts` появляется `Database['public']['Tables']['prompt_presets']`.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/integration/test_prompt_presets.py`:

```python
"""Справочник пресетов: сид на месте, читать можно, писать нельзя."""

from __future__ import annotations

import asyncpg
import pytest

from mimic42.testing.slots import plain_dsn

EXPECTED_SLUGS = {"rage_comments", "sasavot_fan", "magnum_normie", "battalion"}


async def test_presets_are_seeded(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        rows = await connection.fetch(
            "select slug, title, summary, body, sort_order "
            "from public.prompt_presets where is_active order by sort_order"
        )
    finally:
        await connection.close()

    assert {row["slug"] for row in rows} == EXPECTED_SLUGS
    assert [row["sort_order"] for row in rows] == [1, 2, 3, 4]
    for row in rows:
        assert row["title"].strip()
        assert row["summary"].strip()
        # Тексты пресетов длинные: короткая строка означает обрезанный сид.
        assert len(row["body"]) > 300


async def test_authenticated_reads_but_cannot_write(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        async with connection.transaction():
            await connection.execute("set local role authenticated")

            assert await connection.fetchval("select count(*) from public.prompt_presets") == 4

            # Политики insert нет — RLS отвечает 42501.
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with connection.transaction():
                    await connection.execute(
                        "insert into public.prompt_presets (slug, title, summary, body) "
                        "values ('mine', 'Мой', 'мой пресет', 'текст')"
                    )
    finally:
        await connection.close()
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `uv run pytest tests/integration/test_prompt_presets.py -v`
Expected: FAIL — `asyncpg.exceptions.UndefinedTableError: relation "public.prompt_presets" does not exist`

- [ ] **Step 3: Написать миграцию**

Создать `supabase/migrations/20260920085947_add_prompt_presets.sql`:

```sql
-- Справочник пресетов промптов. Курируется нами: пользователь читает и
-- применяет, но не создаёт — поэтому политик записи нет вообще.
create table public.prompt_presets (
    id uuid primary key default gen_random_uuid(),
    slug text not null unique,
    title text not null,
    summary text not null,
    body text not null,
    sort_order integer not null default 0,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint prompt_presets_slug_not_blank check (btrim(slug) <> ''),
    constraint prompt_presets_title_not_blank check (btrim(title) <> ''),
    constraint prompt_presets_summary_not_blank check (btrim(summary) <> ''),
    constraint prompt_presets_body_not_blank check (btrim(body) <> '')
);

create trigger prompt_presets_set_updated_at
    before update on public.prompt_presets
    for each row execute function public.set_updated_at();

create index prompt_presets_active_order_idx
    on public.prompt_presets (sort_order)
    where is_active;

alter table public.prompt_presets enable row level security;

grant select on public.prompt_presets to authenticated;

create policy prompt_presets_select_active on public.prompt_presets
    for select to authenticated
    using (is_active);

insert into public.prompt_presets (slug, title, summary, body, sort_order) values
(
    'rage_comments',
    'Рейджбейт в комментариях',
    'спорит под постами и в обсуждениях, никогда не соглашается',
    $preset$ВСТАВИТЬ СЮДА ТЕКСТ ИЗ СПЕКИ, РАЗДЕЛ «Тексты пресетов», БЛОК 1 `rage_comments`$preset$,
    1
),
(
    'sasavot_fan',
    'Фанат сасыча',
    'пацанский олд, смотрит Сасавота с первого стрима',
    $preset$ВСТАВИТЬ СЮДА ТЕКСТ ИЗ СПЕКИ, РАЗДЕЛ «Тексты пресетов», БЛОК 2 `sasavot_fan`$preset$,
    2
),
(
    'magnum_normie',
    'Нормис, которому зашёл Magnum',
    'обычный парень из чатов, ненавязчиво продвигает альбом Magnum',
    $preset$ВСТАВИТЬ СЮДА ТЕКСТ ИЗ СПЕКИ, РАЗДЕЛ «Тексты пресетов», БЛОК 3 `magnum_normie`$preset$,
    3
),
(
    'battalion',
    'Батальоновец',
    'боец 1 Батальона 42-пропаганды, выполняет приказы из батальонного чата',
    $preset$ВСТАВИТЬ СЮДА ТЕКСТ ИЗ СПЕКИ, РАЗДЕЛ «Тексты пресетов», БЛОК 4 `battalion`$preset$,
    4
);
```

Четыре строки `ВСТАВИТЬ СЮДА ...` — это единственное, что нужно заполнить: открой
`docs/superpowers/specs/2026-09-20-prompt-presets-design.md`, найди раздел «Тексты
пресетов» и скопируй содержимое соответствующего блока в тройных кавычках целиком,
от первой строки до последней, без изменений. Долларовые кавычки `$preset$` выбраны
именно чтобы кавычки и апострофы внутри текста не требовали экранирования.

- [ ] **Step 4: Применить миграцию к тестовой базе**

Run: `supabase db push`
Expected: CLI печатает имя новой миграции и `Finished supabase db push.`

Проект уже слинкован (`supabase/.temp/project-ref` → `ipqylrdmmjitemjrygej`). Если CLI
просит логин — `supabase login`. Продовую базу в этой задаче не трогаем.

- [ ] **Step 5: Запустить тест и убедиться, что он проходит**

Run: `uv run pytest tests/integration/test_prompt_presets.py -v`
Expected: PASS, 2 passed

- [ ] **Step 6: Перегенерировать типы Supabase для фронта**

Run: `cd frontend && bun run generate:types && bun run typecheck`
Expected: в `frontend/src/types/supabase.ts` появился блок `prompt_presets`; typecheck без ошибок

- [ ] **Step 7: Коммит**

```bash
git add supabase/migrations/20260920085947_add_prompt_presets.sql tests/integration/test_prompt_presets.py frontend/src/types/supabase.ts
git commit -m "feat(db): prompt presets table with seeded presets"
```

---

### Task 2: Чтение пресетов на фронте

**Files:**
- Create: `frontend/src/hooks/usePromptPresets.ts`
- Create: `frontend/src/__tests__/prompt-presets.test.ts`
- Modify: `frontend/src/types/index.ts` (добавить интерфейс в конец файла)
- Modify: `frontend/src/lib/queryClient.ts` (новая секция в `queryKeys`)

**Interfaces:**
- Consumes: таблица `public.prompt_presets` из Task 1.
- Produces:
  - `export interface PromptPresetRow` в `@/types` с полями `id: string`, `slug: string`, `title: string`, `summary: string`, `body: string`, `sort_order: number`, `is_active: boolean`, `created_at: string`, `updated_at: string`
  - `export async function fetchPromptPresets(client: SupabaseBrowserClient): Promise<PromptPresetRow[]>`
  - `export function usePromptPresets()` — возвращает `UseQueryResult<PromptPresetRow[]>`
  - `queryKeys.presets.list()`

- [ ] **Step 1: Написать падающий тест**

Создать `frontend/src/__tests__/prompt-presets.test.ts`:

```ts
import { describe, expect, test } from 'bun:test';
import { fetchPromptPresets } from '@/hooks/usePromptPresets';
import type { SupabaseBrowserClient } from '@/lib/supabase/client';
import type { PromptPresetRow } from '@/types';

interface FakeCalls {
  table?: string;
  eqColumn?: string;
  eqValue?: unknown;
  orderColumn?: string;
}

function fakeClient(result: { data: unknown; error: { message: string } | null }) {
  const calls: FakeCalls = {};
  const client = {
    from(table: string) {
      calls.table = table;
      return {
        select() {
          return {
            eq(column: string, value: unknown) {
              calls.eqColumn = column;
              calls.eqValue = value;
              return {
                order(orderColumn: string) {
                  calls.orderColumn = orderColumn;
                  return Promise.resolve(result);
                },
              };
            },
          };
        },
      };
    },
  };
  return { client: client as unknown as SupabaseBrowserClient, calls };
}

const ROW: PromptPresetRow = {
  id: '11111111-1111-1111-1111-111111111111',
  slug: 'rage_comments',
  title: 'Рейджбейт в комментариях',
  summary: 'спорит под постами',
  body: 'текст пресета',
  sort_order: 1,
  is_active: true,
  created_at: '2026-09-20T00:00:00Z',
  updated_at: '2026-09-20T00:00:00Z',
};

describe('fetchPromptPresets', () => {
  test('берёт только активные пресеты в порядке sort_order', async () => {
    const { client, calls } = fakeClient({ data: [ROW], error: null });

    const presets = await fetchPromptPresets(client);

    expect(presets).toEqual([ROW]);
    expect(calls.table).toBe('prompt_presets');
    expect(calls.eqColumn).toBe('is_active');
    expect(calls.eqValue).toBe(true);
    expect(calls.orderColumn).toBe('sort_order');
  });

  test('пустой ответ превращается в пустой список', async () => {
    const { client } = fakeClient({ data: null, error: null });
    expect(await fetchPromptPresets(client)).toEqual([]);
  });

  test('ошибка запроса пробрасывается, а не маскируется пустым списком', async () => {
    const { client } = fakeClient({ data: null, error: { message: 'permission denied' } });
    await expect(fetchPromptPresets(client)).rejects.toThrow('permission denied');
  });
});
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd frontend && bun test src/__tests__/prompt-presets.test.ts`
Expected: FAIL — модуль `@/hooks/usePromptPresets` не найден

- [ ] **Step 3: Добавить тип строки**

В конец `frontend/src/types/index.ts`:

```ts
// ── Prompt presets ────────────────────────────────────────────────────────────
export interface PromptPresetRow {
  id: string;
  slug: string;
  title: string;
  summary: string;
  body: string;
  sort_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}
```

- [ ] **Step 4: Добавить ключ кэша**

В `frontend/src/lib/queryClient.ts`, внутрь объекта `queryKeys`, сразу после секции `profile`:

```ts
  // Prompt presets
  presets: {
    all: ['presets'] as const,
    list: () => [...queryKeys.presets.all, 'list'] as const,
  },
```

- [ ] **Step 5: Написать хук**

Создать `frontend/src/hooks/usePromptPresets.ts`:

```ts
'use client';

import { useQuery } from '@tanstack/react-query';
import { getSupabaseClient, type SupabaseBrowserClient } from '@/lib/supabase/client';
import { queryKeys } from '@/lib/queryClient';
import type { PromptPresetRow } from '@/types';

/**
 * Читает справочник пресетов напрямую из Supabase под RLS — как useAgentDetails
 * читает agents. Вынесено из хука отдельной функцией, чтобы фильтр и порядок
 * можно было проверить тестом без react-query.
 */
export async function fetchPromptPresets(
  client: SupabaseBrowserClient,
): Promise<PromptPresetRow[]> {
  const { data, error } = await client
    .from('prompt_presets')
    .select('*')
    .eq('is_active', true)
    .order('sort_order');

  if (error) throw new Error(error.message);
  return (data ?? []) as PromptPresetRow[];
}

export function usePromptPresets() {
  return useQuery({
    queryKey: queryKeys.presets.list(),
    // Справочник правится миграцией, в рамках сессии он неизменен.
    staleTime: Infinity,
    queryFn: () => fetchPromptPresets(getSupabaseClient()),
  });
}
```

- [ ] **Step 6: Запустить тесты и проверки**

Run: `cd frontend && bun test src/__tests__/prompt-presets.test.ts && bun run typecheck && bun run lint`
Expected: 3 pass, typecheck и lint без ошибок

- [ ] **Step 7: Коммит**

```bash
git add frontend/src/hooks/usePromptPresets.ts frontend/src/__tests__/prompt-presets.test.ts frontend/src/types/index.ts frontend/src/lib/queryClient.ts
git commit -m "feat(frontend): prompt presets query hook"
```

---

### Task 3: Компонент выбора пресета

**Files:**
- Create: `frontend/src/components/agent/PresetPicker.tsx`
- Create: `frontend/src/__tests__/preset-picker.test.tsx`

**Interfaces:**
- Consumes: `usePromptPresets()` и `PromptPresetRow` из Task 2; `Modal` из `@/components/ui/modal`; `Button` из `@/components/ui/button`; `Skeleton` из `@/components/ui/card`.
- Produces:
  - `export function PresetPicker({ currentValue, onApply }: { currentValue: string; onApply: (body: string) => void })` — кнопка + модалка, сам ходит за данными
  - `export function PresetPickerDialog(props)` — чистый компонент без запросов, props: `isOpen: boolean`, `onClose: () => void`, `presets: PromptPresetRow[]`, `isLoading: boolean`, `isError: boolean`, `currentValue: string`, `onApply: (body: string) => void`

**Почему подтверждение внутри модалки, а не `ConfirmDialog`:** `Modal` рендерится инлайном, без портала, и жёстко проставляет `id="modal-title"`. Вложенный `ConfirmDialog` дал бы два `role="dialog"`, дублирующиеся id и две конкурирующие ловушки фокуса. Поэтому подтверждение — вторая стадия той же кнопки в подвале модалки.

- [ ] **Step 1: Написать падающий тест**

Создать `frontend/src/__tests__/preset-picker.test.tsx`:

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
    sort_order: 2,
    is_active: true,
    created_at: '2026-09-20T00:00:00Z',
    updated_at: '2026-09-20T00:00:00Z',
  },
];

function renderDialog(overrides: Partial<ComponentProps<typeof PresetPickerDialog>> = {}) {
  const onApply = mock((_body: string) => {});
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

  test('выбор другого пресета показывает его тело', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole('option', { name: /Фанат сасыча/ }));
    expect(screen.getByTestId('preset-body').textContent).toBe('ТЕЛО ФАНАТА');
  });

  test('пустое поле — применение сразу отдаёт текст наверх', async () => {
    const user = userEvent.setup();
    const { onApply } = renderDialog({ currentValue: '   ' });
    await user.click(screen.getByRole('button', { name: 'Применить пресет' }));
    expect(onApply).toHaveBeenCalledWith('ТЕЛО РЕЙДЖБЕЙТА');
  });

  test('непустое поле — первый клик только предупреждает, второй применяет', async () => {
    const user = userEvent.setup();
    const { onApply } = renderDialog({ currentValue: 'мой старый характер' });

    await user.click(screen.getByRole('button', { name: 'Применить пресет' }));
    expect(onApply).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toContain('будет заменён');

    await user.click(screen.getByRole('button', { name: 'Всё равно заменить' }));
    expect(onApply).toHaveBeenCalledWith('ТЕЛО РЕЙДЖБЕЙТА');
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

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd frontend && bun test src/__tests__/preset-picker.test.tsx`
Expected: FAIL — модуль `@/components/agent/PresetPicker` не найден

- [ ] **Step 3: Написать компонент**

Создать `frontend/src/components/agent/PresetPicker.tsx`:

```tsx
'use client';

import { useState } from 'react';
import { Sparkles } from 'lucide-react';
import { Modal } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/card';
import { usePromptPresets } from '@/hooks/usePromptPresets';
import { cn } from '@/lib/utils';
import type { PromptPresetRow } from '@/types';

export function PresetPicker({
  currentValue,
  onApply,
}: {
  currentValue: string;
  onApply: (body: string) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const { data, isLoading, isError } = usePromptPresets();

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        leftIcon={<Sparkles className="h-3.5 w-3.5" />}
        onClick={() => setIsOpen(true)}
        data-testid="open-presets"
      >
        Пресеты
      </Button>

      <PresetPickerDialog
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        presets={data ?? []}
        isLoading={isLoading}
        isError={isError}
        currentValue={currentValue}
        onApply={(body) => {
          onApply(body);
          setIsOpen(false);
        }}
      />
    </>
  );
}

export function PresetPickerDialog({
  isOpen,
  onClose,
  presets,
  isLoading,
  isError,
  currentValue,
  onApply,
}: {
  isOpen: boolean;
  onClose: () => void;
  presets: PromptPresetRow[];
  isLoading: boolean;
  isError: boolean;
  currentValue: string;
  onApply: (body: string) => void;
}) {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  // Вторая стадия кнопки вместо вложенного диалога: Modal рендерится инлайном
  // и держит один жёсткий id заголовка, два вложенных сломали бы фокус и ARIA.
  const [confirming, setConfirming] = useState(false);

  const selected = presets.find((preset) => preset.slug === selectedSlug) ?? presets[0] ?? null;
  const willOverwrite = currentValue.trim().length > 0;

  const handleClose = () => {
    setConfirming(false);
    onClose();
  };

  const handleSelect = (slug: string) => {
    setSelectedSlug(slug);
    setConfirming(false);
  };

  const handleApply = () => {
    if (!selected) return;
    if (willOverwrite && !confirming) {
      setConfirming(true);
      return;
    }
    setConfirming(false);
    onApply(selected.body);
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title="Пресеты промптов"
      size="xl"
      className="max-w-3xl"
    >
      {isLoading && <Skeleton className="h-64 w-full" />}

      {!isLoading && isError && (
        <p role="alert" className="font-mono text-xs text-crimson-400">
          Не удалось загрузить пресеты
        </p>
      )}

      {!isLoading && !isError && presets.length === 0 && (
        <p className="font-mono text-xs text-void-400">Пресетов пока нет</p>
      )}

      {!isLoading && !isError && presets.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
          <div role="listbox" aria-label="Пресеты" className="flex flex-col gap-1 max-h-72 overflow-y-auto">
            {presets.map((preset) => (
              <button
                key={preset.slug}
                type="button"
                role="option"
                aria-selected={selected?.slug === preset.slug}
                onClick={() => handleSelect(preset.slug)}
                className={cn(
                  'text-left rounded-sm border px-3 py-2 transition-colors duration-150',
                  selected?.slug === preset.slug
                    ? 'border-plasma-600 bg-plasma-950/40'
                    : 'border-void-700 hover:border-void-500',
                )}
              >
                <span className="block font-mono text-xs text-void-100">{preset.title}</span>
                <span className="block font-mono text-[11px] text-void-500">{preset.summary}</span>
              </button>
            ))}
          </div>

          <pre
            data-testid="preset-body"
            className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-sm border border-void-700 bg-void-900 p-3 font-mono text-xs text-void-300"
          >
            {selected?.body}
          </pre>
        </div>
      )}

      <div className="mt-6 flex items-center justify-end gap-3">
        {confirming && (
          <span role="alert" className="mr-auto font-mono text-xs text-amber-400">
            Текущий характер будет заменён
          </span>
        )}
        <Button type="button" variant="ghost" size="sm" onClick={handleClose}>
          Отмена
        </Button>
        <Button type="button" size="sm" onClick={handleApply} disabled={!selected}>
          {confirming ? 'Всё равно заменить' : 'Применить пресет'}
        </Button>
      </div>
    </Modal>
  );
}
```

- [ ] **Step 4: Запустить тесты и проверки**

Run: `cd frontend && bun test src/__tests__/preset-picker.test.tsx && bun run typecheck && bun run lint`
Expected: 7 pass, typecheck и lint без ошибок

- [ ] **Step 5: Коммит**

```bash
git add frontend/src/components/agent/PresetPicker.tsx frontend/src/__tests__/preset-picker.test.tsx
git commit -m "feat(frontend): preset picker dialog"
```

---

### Task 4: Вынести `TabSettings` и подключить пикер

**Files:**
- Create: `frontend/src/components/agent/TabSettings.tsx`
- Modify: `frontend/src/app/(dashboard)/agent/[id]/page.tsx:193-357` (вырезать блок), плюс импорты в шапке

**Interfaces:**
- Consumes: `PresetPicker` из Task 3.
- Produces: `export function TabSettings({ agentId }: { agentId: string })` в `@/components/agent/TabSettings`. Страница агента импортирует его вместо локального определения.

Вкладка «Настройки» — единственное, что переезжает. Остальные вкладки и `AgentControls` остаются в `page.tsx`.

- [ ] **Step 1: Создать файл вкладки**

Создать `frontend/src/components/agent/TabSettings.tsx`. Содержимое: строка `'use client';`, затем импорты (ниже), затем **дословно перенесённые** функции `TabSettings` и `SettingsSkeleton` из `frontend/src/app/(dashboard)/agent/[id]/page.tsx` (строки 193–357, от комментария `// ── Tab: Settings ──` до строки перед `// ── Tab: Actions ──`). У `TabSettings` и `SettingsSkeleton` добавить `export`.

Шапка файла:

```tsx
'use client';

import { useState, useEffect } from 'react';
import { useAgentDetails, useUpdateAgentSettings } from '@/hooks/useAgent';
import { useModelReasoning } from '@/hooks/useModelReasoning';
import { useToast } from '@/components/ui/toast';
import { Button } from '@/components/ui/button';
import { Input, Textarea } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/card';
import { PresetPicker } from '@/components/agent/PresetPicker';
import { DEFAULT_MODEL, optionsIncluding } from '@/lib/models';
import { agentsApi } from '@/lib/api';
import { pickReasoningValue, reasoningLabel, reasoningOptionValues } from '@/lib/reasoning';
import { agentSettingsSchema, type AgentSettingsValues } from '@/lib/validators';
import type { ApiError } from '@/types';
```

- [ ] **Step 2: Подключить пикер к полю SOUL.md**

В перенесённом `TabSettings` заменить блок `<Textarea label="SOUL.md — Характер" ... />` на:

```tsx
      <div className="space-y-2">
        <div className="flex justify-end">
          <PresetPicker
            currentValue={values.soul_prompt}
            onApply={(body) => set('soul_prompt', body)}
          />
        </div>
        <Textarea
          label="SOUL.md — Характер"
          value={values.soul_prompt}
          onChange={(e) => set('soul_prompt', e.target.value)}
          error={formErrors.soul_prompt}
          className="min-h-[200px]"
          showCount
          maxLength={50000}
          hint="Описание личности, стиля общения и особенностей агента"
        />
      </div>
```

`set` уже помечает форму как `dirty`, поэтому кнопка «Сохранить изменения» разблокируется сама, а сохранение и `agentsApi.reload` остаются на ней.

- [ ] **Step 3: Вырезать блок из страницы и починить импорты**

В `frontend/src/app/(dashboard)/agent/[id]/page.tsx`:

1. Удалить строки 193–357 (функции `TabSettings` и `SettingsSkeleton` вместе с комментарием-разделителем).
2. Добавить в шапку: `import { TabSettings } from '@/components/agent/TabSettings';`
3. Удалить целиком ставшие ненужными импорты:

```tsx
import { DEFAULT_MODEL, optionsIncluding } from '@/lib/models';
import { agentsApi } from '@/lib/api';
import { useModelReasoning } from '@/hooks/useModelReasoning';
import {
  pickReasoningValue,
  reasoningLabel,
  reasoningOptionValues,
} from '@/lib/reasoning';
```

4. Сократить два импорта до того, что осталось в файле:

```tsx
import { useAgentStatus, useAgentDetails } from '@/hooks/useAgent';
import {
  triggerMessageSchema,
  type TriggerMessageValues,
} from '@/lib/validators';
```

Остальные импорты (`useState`, `useEffect`, `Button`, `Input`, `Textarea`, `Skeleton`, `useToast`, `ApiError`, `Card`, `Divider`, `Spinner`, `cn`, иконки) используются другими вкладками — их не трогать.

- [ ] **Step 4: Проверить, что ничего не отвалилось**

Run: `cd frontend && bun run typecheck && bun run lint && bun test`
Expected: typecheck и lint чисто, все `bun test` зелёные

Если lint ругается на неиспользованный импорт — значит в шаге 3 что-то осталось; удалить названный им символ.

- [ ] **Step 5: Коммит**

```bash
git add frontend/src/components/agent/TabSettings.tsx "frontend/src/app/(dashboard)/agent/[id]/page.tsx"
git commit -m "feat(frontend): preset picker on agent settings tab"
```

---

### Task 5: Пикер на шаге «Характер» в онбординге

**Files:**
- Modify: `frontend/src/app/(dashboard)/onboarding/page.tsx` (импорт в шапке + `StepSoul`, строки ~226–283)

**Interfaces:**
- Consumes: `PresetPicker` из Task 3.
- Produces: ничего нового наружу.

- [ ] **Step 1: Добавить импорт**

В шапку `frontend/src/app/(dashboard)/onboarding/page.tsx`:

```tsx
import { PresetPicker } from '@/components/agent/PresetPicker';
```

- [ ] **Step 2: Вставить пикер в `StepSoul`**

В функции `StepSoul` заменить блок `<Textarea label={...} ... />` на:

```tsx
      <div className="space-y-2">
        <div className="flex justify-end">
          <PresetPicker currentValue={soulPrompt} onApply={setSoulPrompt} />
        </div>
        <Textarea
          label={`SOUL.md — ${session?.agent_name ?? 'Агент'}`}
          placeholder={placeholder}
          value={soulPrompt}
          onChange={(e) => setSoulPrompt(e.target.value)}
          error={error}
          className="min-h-[220px]"
          showCount
          maxLength={50000}
          autoFocus
        />
      </div>
```

- [ ] **Step 3: Проверить сборку**

Run: `cd frontend && bun run typecheck && bun run lint && bun test`
Expected: всё чисто

- [ ] **Step 4: Коммит**

```bash
git add "frontend/src/app/(dashboard)/onboarding/page.tsx"
git commit -m "feat(frontend): preset picker on onboarding soul step"
```

---

### Task 6: e2e-проверка применения пресета

**Files:**
- Modify: `tests/e2e/test_agent.py` (новый тест в конец класса `TestAgentPage`)

**Interfaces:**
- Consumes: `data-testid="open-presets"` и `data-testid="preset-body"` из Task 3; вкладка настроек из Task 4.
- Produces: ничего.

- [ ] **Step 1: Написать тест**

Добавить в конец класса `TestAgentPage` в `tests/e2e/test_agent.py`:

```python
    def test_preset_fills_soul_prompt(
        self, persona_page: Callable[..., Page], api: httpx.Client, users: dict
    ) -> None:
        agent_id = _new_agent(api, users, "Пресеты")
        page = persona_page("full")
        page.goto(f"/agent/{agent_id}?tab=settings")

        soul = page.get_by_label("SOUL.md — Характер")
        expect(soul).to_be_visible()
        # Пустое поле — применение проходит одним кликом, без подтверждения.
        soul.fill("")

        page.get_by_test_id("open-presets").click()
        page.get_by_role("option", name=re.compile("Фанат сасыча")).click()
        body = page.get_by_test_id("preset-body").inner_text()
        page.get_by_role("button", name="Применить пресет").click()

        expect(page.get_by_test_id("preset-body")).to_be_hidden()
        expect(soul).to_have_value(body)
        expect(page.get_by_text("● Есть несохранённые изменения")).to_be_visible()

    def test_preset_asks_before_overwriting(
        self, persona_page: Callable[..., Page], api: httpx.Client, users: dict
    ) -> None:
        agent_id = _new_agent(api, users, "Пресеты поверх")
        page = persona_page("full")
        page.goto(f"/agent/{agent_id}?tab=settings")

        soul = page.get_by_label("SOUL.md — Характер")
        expect(soul).to_be_visible()
        soul.fill("мой старый характер")

        page.get_by_test_id("open-presets").click()
        page.get_by_role("button", name="Применить пресет").click()

        expect(page.get_by_text("Текущий характер будет заменён")).to_be_visible()
        expect(soul).to_have_value("мой старый характер")

        page.get_by_role("button", name="Всё равно заменить").click()
        expect(soul).not_to_have_value("мой старый характер")
```

- [ ] **Step 2: Запустить e2e**

Run: `uv run pytest tests/e2e/test_agent.py -k preset -v`
Expected: 2 passed

Прогон поднимает бэкенд на 8000 и фронт на 3000 — порты должны быть свободны.

- [ ] **Step 3: Полный прогон перед финалом**

Run: `cd frontend && bun test && bun run typecheck && bun run lint`
Run: `uv run pytest -m db`
Expected: всё зелёное

- [ ] **Step 4: Коммит и пуш ветки**

```bash
git add tests/e2e/test_agent.py
git commit -m "test(e2e): preset application on settings tab"
git push -u origin feat/issue-68-prompt-presets
```

PR не открывать: сначала живая проверка в дашборде.

---

## Проверка вручную после Task 6

1. `cd frontend && bun run dev`, бэкенд — `uv run python -m mimic42.main`.
2. Открыть агента → «Настройки» → «Пресеты»: в списке четыре пресета, справа полный текст, переключение работает.
3. Применить пресет на непустое поле: появляется предупреждение, второй клик заменяет текст, кнопка «Сохранить изменения» разблокирована.
4. Сохранить и перезагрузить страницу — текст на месте.
5. Пройти онбординг до шага «Характер», применить пресет, продолжить — текст сохранился в сессию.
