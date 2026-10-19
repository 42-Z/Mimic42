import { describe, expect, test } from 'bun:test';
import { fetchPromptPresets } from '@/hooks/usePromptPresets';
import type { SupabaseBrowserClient } from '@/lib/supabase/client';
import type { PromptPresetRow } from '@/types';

interface FakeCalls {
  table?: string;
  selectedColumns?: string;
  orderColumn?: string;
}

function fakeClient(result: { data: unknown; error: { message: string } | null }) {
  const calls: FakeCalls = {};
  const client = {
    from(table: string) {
      calls.table = table;
      return {
        select(columns: string) {
          calls.selectedColumns = columns;
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
  return { client: client as unknown as SupabaseBrowserClient, calls };
}

const ROW: PromptPresetRow = {
  id: '11111111-1111-1111-1111-111111111111',
  slug: 'rage_comments',
  title: 'Рейджбейт в комментариях',
  summary: 'спорит под постами',
  body: 'текст пресета',
  settings: null,
  sort_order: 1,
  is_active: true,
  owner_id: null,
  published_at: null,
  created_at: '2026-09-20T00:00:00Z',
  updated_at: '2026-09-20T00:00:00Z',
};

describe('fetchPromptPresets', () => {
  test('возвращает безопасный набор строк RLS в порядке sort_order без клиентского фильтра активности', async () => {
    const hiddenOwnPreset: PromptPresetRow = {
      ...ROW,
      id: '22222222-2222-2222-2222-222222222222',
      owner_id: 'user-1',
      published_at: '2026-10-01T00:00:00Z',
      is_active: false,
    };
    const { client, calls } = fakeClient({ data: [ROW, hiddenOwnPreset], error: null });

    const presets = await fetchPromptPresets(client);

    expect(presets).toEqual([ROW, hiddenOwnPreset]);
    expect(calls).toEqual({
      table: 'prompt_presets',
      selectedColumns: '*',
      orderColumn: 'sort_order',
    });
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
