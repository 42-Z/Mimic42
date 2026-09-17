import { describe, expect, test } from 'bun:test';
import { QueryClient } from '@tanstack/react-query';
import type { ConversationCursor } from '@/lib/api';

interface Row {
  id: string;
  created_at: string;
}

// Новейшие сверху, как отдаёт бэкенд.
const DB: Row[] = [
  { id: 'c', created_at: '2026-09-17T10:00:00Z' },
  { id: 'b', created_at: '2026-09-17T09:00:00Z' },
  { id: 'a', created_at: '2026-09-17T09:00:00Z' },
  { id: 'z', created_at: '2026-09-17T08:00:00Z' },
  { id: 'y', created_at: '2026-09-17T07:00:00Z' },
  { id: 'x', created_at: '2026-09-17T06:00:00Z' },
];

const PAGE_SIZE = 2;

function slice(cursor: ConversationCursor | null) {
  const rows = DB.filter(
    (row) =>
      !cursor ||
      row.created_at < cursor.before ||
      (row.created_at === cursor.before && row.id < cursor.id),
  );
  const turns = rows.slice(0, PAGE_SIZE);
  const last = turns[turns.length - 1];
  const hasNext = turns.length === PAGE_SIZE && last !== undefined;
  return {
    turns,
    next_before: hasNext ? last.created_at : null,
    next_before_id: hasNext ? last.id : null,
  };
}

function feedOptions() {
  return {
    queryKey: ['feed'] as const,
    queryFn: ({ pageParam }: { pageParam: ConversationCursor | null }) =>
      Promise.resolve(slice(pageParam)),
    initialPageParam: null as ConversationCursor | null,
    getNextPageParam: (lastPage: ReturnType<typeof slice>) =>
      lastPage.next_before
        ? { before: lastPage.next_before, id: lastPage.next_before_id ?? '' }
        : undefined,
  };
}

function loadedIds(qc: QueryClient): string[] {
  const data = qc.getQueryData<{ pages: ReturnType<typeof slice>[] }>(['feed']);
  return (data?.pages ?? []).flatMap((page) => page.turns.map((turn) => turn.id));
}

describe('пагинация ленты активности', () => {
  test('курсор (before, id) не теряет и не дублирует ходы при равных timestamp', async () => {
    const qc = new QueryClient();
    await qc.fetchInfiniteQuery({ ...feedOptions(), pages: 3 });
    expect(loadedIds(qc)).toEqual(['c', 'b', 'a', 'z', 'y', 'x']);
  });

  test('рефетч после нового хода пересобирает страницы без дыр и дублей', async () => {
    const qc = new QueryClient();
    await qc.fetchInfiniteQuery({ ...feedOptions(), pages: 3 });

    // Новое сообщение пришло сверху — ровно то, что делает realtime-инвалидация.
    DB.unshift({ id: 'n', created_at: '2026-09-17T11:00:00Z' });
    await qc.refetchQueries({ queryKey: ['feed'], type: 'all' });

    // Сплошной префикс свежих ходов: без выпавшего интервала и без дублей.
    // Самый старый загруженный ход выезжает за окно — он не потерян, а
    // достаётся следующей страницей.
    expect(loadedIds(qc)).toEqual(['n', 'c', 'b', 'a', 'z', 'y']);

    await qc.fetchInfiniteQuery({ ...feedOptions(), pages: 4 });
    expect(loadedIds(qc)).toEqual(['n', 'c', 'b', 'a', 'z', 'y', 'x']);

    DB.shift();
  });
});
