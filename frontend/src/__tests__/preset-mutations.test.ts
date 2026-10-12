import { describe, expect, test } from 'bun:test';
import {
  createPreset,
  deletePreset,
  favoritePreset,
  publishPreset,
  unfavoriteByPreset,
  unfavoritePreset,
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

  test('избранное вставляет владельца из сессии и preset_id', async () => {
    const calls: MutationCalls = {};
    const client = {
      auth: {
        getUser: () => Promise.resolve({ data: { user: { id: 'user-1' } } }),
      },
      from(table: string) {
        calls.table = table;
        return {
          insert(values: unknown) {
            calls.op = 'insert';
            calls.values = values;
            return Promise.resolve({ data: null, error: null });
          },
        };
      },
    } as unknown as SupabaseBrowserClient;

    await favoritePreset(client, 'preset-1');

    expect(calls.table).toBe('preset_favorites');
    expect(calls.op).toBe('insert');
    expect(calls.values).toEqual({ owner_id: 'user-1', preset_id: 'preset-1' });
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
