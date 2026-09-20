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
