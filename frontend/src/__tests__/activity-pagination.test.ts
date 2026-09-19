import { afterEach, beforeEach, describe, expect, mock, spyOn, test } from 'bun:test';
import { QueryClient } from '@tanstack/react-query';
import { agentsApi, type ConversationPage } from '@/lib/api';
import { queryKeys } from '@/lib/queryClient';
import { activityFeedQueryOptions, refreshActivityFeedHead } from '@/hooks/useActivityFeed';
import type { ConversationTurn } from '@/types';

interface Row {
  id: string;
  created_at: string;
}

// Новейшие сверху, как отдаёт бэкенд. 'b'/'a' делят timestamp — проверяем keyset.
const SEED: Row[] = [
  { id: 'c', created_at: '2026-09-17T10:00:00Z' },
  { id: 'b', created_at: '2026-09-17T09:00:00Z' },
  { id: 'a', created_at: '2026-09-17T09:00:00Z' },
  { id: 'z', created_at: '2026-09-17T08:00:00Z' },
  { id: 'y', created_at: '2026-09-17T07:00:00Z' },
  { id: 'x', created_at: '2026-09-17T06:00:00Z' },
];

interface RecordedCall {
  agentId: string;
  limit: number;
  before: string | null;
  beforeId: string | null;
}

let DB: Row[];

function turn(id: string, createdAt: string): ConversationTurn {
  return {
    id,
    agent_id: 'agent-1',
    timestamp: createdAt,
    peer_id: 'chat',
    peer_name: '',
    agent_name: '',
    incoming: '',
    outgoing: '',
    direction: 'incoming',
    turn_id: null,
    incoming_media: [],
    tools: [],
  };
}

/** Подменяет настоящий клиент: записи о вызовах + та же keyset-выборка, что и на бэке. */
function installApi(calls: RecordedCall[]) {
  return spyOn(agentsApi, 'getConversation').mockImplementation(
    async (agentId, limit = 50, before = null, beforeId = null) => {
      calls.push({ agentId, limit, before: before ?? null, beforeId: beforeId ?? null });
      const rows = DB.filter(
        (row) =>
          !before ||
          row.created_at < before ||
          (row.created_at === before && row.id < (beforeId ?? '')),
      );
      const page = rows.slice(0, limit);
      const last = page[page.length - 1];
      const hasNext = page.length === limit && last !== undefined;
      return {
        turns: page.map((row) => turn(row.id, row.created_at)),
        next_before: hasNext ? last.created_at : null,
        next_before_id: hasNext ? last.id : null,
      };
    },
  );
}

function loadedIds(qc: QueryClient): string[] {
  const data = qc.getQueryData<{ pages: ConversationPage[] }>(
    queryKeys.conversation.byAgent('agent-1'),
  );
  return (data?.pages ?? []).flatMap((page) => page.turns.map((t) => t.id));
}

beforeEach(() => {
  DB = SEED.map((row) => ({ ...row }));
});

afterEach(() => {
  mock.restore();
});

describe('пагинация ленты активности', () => {
  test('курсор (before, id) реального клиента не теряет и не дублирует ходы', async () => {
    const qc = new QueryClient();
    const calls: RecordedCall[] = [];
    installApi(calls);

    await qc.fetchInfiniteQuery({ ...activityFeedQueryOptions('agent-1', 2), pages: 3 });

    // Второй и третий запросы обязаны нести курсор последнего хода страницы.
    expect(calls).toEqual([
      { agentId: 'agent-1', limit: 2, before: null, beforeId: null },
      { agentId: 'agent-1', limit: 2, before: '2026-09-17T09:00:00Z', beforeId: 'b' },
      { agentId: 'agent-1', limit: 2, before: '2026-09-17T08:00:00Z', beforeId: 'z' },
    ]);
    expect(loadedIds(qc)).toEqual(['c', 'b', 'a', 'z', 'y', 'x']);
  });

  test('live-tail: realtime обновляет только голову, не трогая глубокие страницы', async () => {
    const qc = new QueryClient();
    const calls: RecordedCall[] = [];
    installApi(calls);

    await qc.fetchInfiniteQuery({ ...activityFeedQueryOptions('agent-1', 2), pages: 2 });
    expect(loadedIds(qc)).toEqual(['c', 'b', 'a', 'z']);

    calls.length = 0;
    DB.unshift({ id: 'n', created_at: '2026-09-17T11:00:00Z' });
    await refreshActivityFeedHead(qc, 'agent-1', 2);

    // Ровно один запрос — за головой. Глубокие страницы не перезапрашивались.
    expect(calls).toEqual([{ agentId: 'agent-1', limit: 2, before: null, beforeId: null }]);

    // 'b' не потерян, дублей нет: граница со второй страницей сохранена.
    expect(loadedIds(qc)).toEqual(['n', 'c', 'b', 'a', 'z']);
  });
});
