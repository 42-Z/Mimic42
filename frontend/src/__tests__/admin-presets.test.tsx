import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { adminApi } from '@/lib/adminApi';
import { AdminAccessContext, type AdminAccess } from '@/hooks/useAdminAccess';
import { queryKeys } from '@/lib/queryClient';
import type {
  AdminPage,
  AdminPresetDetail,
  AdminPresetSummary,
  AdminPresetKind,
} from '@/types/admin';

const adminId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const ownerId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const officialId = '11111111-1111-4111-8111-111111111111';
const publishedId = '22222222-2222-4222-8222-222222222222';
const updatedAt = '2026-10-18T12:00:00Z';

const access: AdminAccess = {
  userId: adminId,
  isLoading: false,
  isAdmin: true,
  isDenied: false,
  error: null,
  retry: () => undefined,
};

function presetSummary(
  id: string,
  owner: string | null,
  overrides: Partial<AdminPresetSummary> = {},
): AdminPresetSummary {
  return {
    id,
    owner_id: owner,
    owner_name: owner === null ? null : 'Автор',
    title: owner === null ? 'Официальный' : 'Пресет автора',
    summary: 'Краткое описание',
    sort_order: owner === null ? 1 : 2,
    is_active: true,
    published_at: owner === null ? null : updatedAt,
    updated_at: updatedAt,
    ...overrides,
  };
}

function presetDetail(summary: AdminPresetSummary): AdminPresetDetail {
  return {
    ...summary,
    body: `Текст: ${summary.title}`,
    settings: { enabled_tools: ['send_text_message'] },
  };
}

function presetPage(
  items: AdminPresetSummary[],
  params: { page: number; page_size: number },
  total = items.length,
): AdminPage<AdminPresetSummary> {
  return { items, total, page: params.page, page_size: params.page_size };
}

const originalPresets = adminApi.presets;
const originalPreset = adminApi.preset;
const originalCreate = adminApi.createPreset;
const originalUpdate = adminApi.updatePreset;
const originalVisibility = adminApi.setPresetVisibility;
let rows: AdminPresetSummary[];
let listCalls: Array<{ q: string; kind: AdminPresetKind; page: number; page_size?: number }>;
let detailCalls: string[];
let createCalls: unknown[];
let updateCalls: Array<{ id: string; values: unknown }>;
let visibilityCalls: Array<{ id: string; is_active: boolean }>;
let resolveVisibility: ((value: AdminPresetDetail) => void) | null;
let rejectVisibility: ((error: Error) => void) | null;

function renderPresets() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <AdminAccessContext.Provider value={access}>
        <AdminPresets />
      </AdminAccessContext.Provider>
    </QueryClientProvider>,
  );
  return { queryClient, ...view };
}

beforeEach(() => {
  rows = [presetSummary(officialId, null), presetSummary(publishedId, ownerId)];
  listCalls = [];
  detailCalls = [];
  createCalls = [];
  updateCalls = [];
  visibilityCalls = [];
  resolveVisibility = null;
  rejectVisibility = null;

  adminApi.presets = async (params) => {
    listCalls.push(params);
    const matching = rows.filter((row) => {
      const searchMatches =
        !params.q || `${row.title} ${row.summary}`.toLocaleLowerCase('ru').includes(params.q.toLocaleLowerCase('ru'));
      const kindMatches =
        params.kind === 'all' ||
        (params.kind === 'official' && row.owner_id === null) ||
        (params.kind === 'published' && row.owner_id !== null && row.published_at !== null);
      return searchMatches && kindMatches;
    });
    return presetPage(matching, {
      page: params.page,
      page_size: params.page_size ?? 25,
    });
  };
  adminApi.preset = async (id) => {
    detailCalls.push(id);
    const row = rows.find((preset) => preset.id === id);
    if (!row) throw new Error('not found');
    return presetDetail(row);
  };
  adminApi.createPreset = async (values) => {
    createCalls.push(values);
    const summary = presetSummary('33333333-3333-4333-8333-333333333333', null, {
      title: values.title,
      summary: values.summary,
      sort_order: values.sort_order ?? 0,
    });
    rows = [...rows, summary];
    return { ...presetDetail(summary), body: values.body, settings: values.settings ?? null };
  };
  adminApi.updatePreset = async (id, values) => {
    updateCalls.push({ id, values });
    rows = rows.map((row) => (row.id === id ? { ...row, ...values } : row));
    const updated = rows.find((row) => row.id === id);
    if (!updated) throw new Error('not found');
    return { ...presetDetail(updated), ...values };
  };
  adminApi.setPresetVisibility = async (id, isActive) => {
    visibilityCalls.push({ id, is_active: isActive });
    return new Promise<AdminPresetDetail>((resolve, reject) => {
      resolveVisibility = resolve;
      rejectVisibility = reject;
    });
  };
});

afterEach(() => {
  cleanup();
  adminApi.presets = originalPresets;
  adminApi.preset = originalPreset;
  adminApi.createPreset = originalCreate;
  adminApi.updatePreset = originalUpdate;
  adminApi.setPresetVisibility = originalVisibility;
});

const { AdminPresets } = await import('@/components/admin/AdminPresets');

describe('AdminPresets', () => {
  test('official details open in the existing editor; user presets are read-only', async () => {
    renderPresets();
    await screen.findByRole('button', { name: 'Редактировать: Официальный' });
    await screen.findByText('Пресет автора');
    expect(detailCalls).toEqual([]);
    expect(screen.queryByRole('button', { name: 'Редактировать: Пресет автора' })).toBeNull();
    expect(screen.queryByRole('spinbutton', { name: 'Порядок: Пресет автора' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Редактировать: Официальный' }));
    expect(await screen.findByRole('dialog', { name: 'Правка пресета' })).toBeTruthy();
    expect(screen.getByLabelText('Название')).toHaveProperty('value', 'Официальный');
    expect(detailCalls).toEqual([officialId]);

    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
    fireEvent.click(screen.getByRole('button', { name: 'Просмотреть: Пресет автора' }));
    const readOnly = await screen.findByRole('dialog', { name: 'Просмотр пресета' });
    expect(within(readOnly).getByText('Текст: Пресет автора')).toBeTruthy();
    expect(within(readOnly).queryByRole('button', { name: /Редактировать|Удалить/ })).toBeNull();
  });

  test('creating an official preset uses the existing editor and a direct request', async () => {
    const { queryClient } = renderPresets();
    await screen.findByRole('button', { name: 'Редактировать: Официальный' });

    fireEvent.click(screen.getByRole('button', { name: 'Новый официальный пресет' }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый пресет' });
    fireEvent.change(within(dialog).getByLabelText('Название'), {
      target: { value: 'Новый официальный' },
    });
    fireEvent.change(within(dialog).getByLabelText('Короткое описание'), {
      target: { value: 'Описание' },
    });
    fireEvent.change(within(dialog).getByLabelText('Промпт'), {
      target: { value: 'Текст характера' },
    });
    fireEvent.click(within(dialog).getByTestId('preset-editor-save'));

    await waitFor(() =>
      expect(createCalls).toEqual([
        {
          title: 'Новый официальный',
          summary: 'Описание',
          body: 'Текст характера',
          settings: null,
        },
      ]),
    );
    expect(queryClient.getMutationCache().getAll()).toEqual([]);
  });

  test('sort order is an independent strict integer patch', async () => {
    renderPresets();
    await screen.findByRole('button', { name: 'Редактировать: Официальный' });
    const input = screen.getByRole('spinbutton', { name: 'Порядок: Официальный' });
    const save = screen.getByRole('button', { name: 'Сохранить порядок: Официальный' });

    fireEvent.change(input, { target: { value: '1.5' } });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    expect(updateCalls).toEqual([]);

    fireEvent.change(input, { target: { value: '-7' } });
    expect((save as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(save);
    await waitFor(() => expect(updateCalls).toEqual([{ id: officialId, values: { sort_order: -7 } }]));
  });

  test('filters the admin list by kind and search while preserving the current page request', async () => {
    renderPresets();
    await screen.findByRole('button', { name: 'Редактировать: Официальный' });

    fireEvent.click(screen.getByRole('button', { name: 'Пользовательские' }));
    await waitFor(() => expect(listCalls.at(-1)).toMatchObject({ kind: 'published', page: 1 }));
    expect(screen.queryByRole('button', { name: 'Редактировать: Официальный' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Просмотреть: Пресет автора' })).toBeTruthy();

    fireEvent.change(screen.getByRole('searchbox', { name: 'Поиск пресетов' }), {
      target: { value: 'Автор' },
    });
    await waitFor(() =>
      expect(listCalls.at(-1)).toMatchObject({ q: 'Автор', kind: 'published', page: 1 }),
    );
  });

  test('hiding waits for the server, blocks repeats, and invalidates both cache families', async () => {
    const { queryClient } = renderPresets();
    await screen.findByText('Пресет автора');
    const catalogKeys = [
      queryKeys.presets.list(),
      queryKeys.presets.favorites(),
      queryKeys.presets.authors(),
    ];
    for (const key of catalogKeys) queryClient.setQueryData(key, []);

    fireEvent.click(screen.getByRole('button', { name: 'Скрыть пресет: Пресет автора' }));
    const confirmation = await screen.findByRole('dialog', { name: 'Скрыть пользовательский пресет?' });
    expect(confirmation.textContent).toContain('Существующие избранные сохранятся как снимок');
    fireEvent.click(within(confirmation).getByRole('button', { name: 'Скрыть пресет' }));

    expect(visibilityCalls).toEqual([{ id: publishedId, is_active: false }]);
    expect(
      (within(confirmation).getByRole('button', { name: 'Скрыть пресет' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(queryClient.getQueryCache().find({ queryKey: catalogKeys[0]! })?.state.isInvalidated).toBe(
      false,
    );

    const hidden = { ...presetDetail(rows[1]!), is_active: false };
    rows = rows.map((row) => (row.id === publishedId ? { ...row, is_active: false } : row));
    resolveVisibility?.(hidden);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Вернуть в каталог: Пресет автора' })).toBeTruthy(),
    );
    for (const key of catalogKeys) {
      expect(queryClient.getQueryCache().find({ queryKey: key })?.state.isInvalidated).toBe(true);
    }
    expect(queryClient.getQueryCache().find({ queryKey: queryKeys.admin.presets(adminId, '', 'all', 1, 25) })).toBeTruthy();
  });

  test('visibility error reports failure and keeps the old status', async () => {
    renderPresets();
    await screen.findByText('Пресет автора');

    fireEvent.click(screen.getByRole('button', { name: 'Скрыть пресет: Пресет автора' }));
    const confirmation = await screen.findByRole('dialog', { name: 'Скрыть пользовательский пресет?' });
    fireEvent.click(within(confirmation).getByRole('button', { name: 'Скрыть пресет' }));
    rejectVisibility?.(new Error('private database detail'));

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Скрыть пресет: Пресет автора' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Вернуть в каталог: Пресет автора' })).toBeNull();
    expect(screen.getByRole('alert').textContent).not.toContain('private database detail');
    expect(screen.queryByRole('dialog', { name: 'Скрыть пользовательский пресет?' })).toBeNull();
  });
});
