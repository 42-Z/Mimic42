'use client';

import { useInfiniteQuery, type InfiniteData, type QueryClient } from '@tanstack/react-query';
import {
  agentsApi,
  type ConversationCursor,
  type ConversationPage,
} from '@/lib/api';
import { queryKeys, HISTORICAL_STALE_TIME } from '@/lib/queryClient';
import { agentIdSchema } from '@/lib/validators';
import type { ConversationTurn } from '@/types';

const PAGE_SIZE = 50;

/**
 * Предохранитель на всплеск: за один live-tail-рефреш не догоняем больше
 * стольких страниц. При превышении бросаем — вызывающий оставляет сырые
 * realtime-инкременты (они уже в ленте) и повторит на следующей вспышке.
 */
const MAX_CATCH_UP_PAGES = 20;

export type ActivityFeedPages = InfiniteData<ConversationPage, ConversationCursor | null>;

/**
 * Опции курсорной ленты ходов. Экспортированы, чтобы тесты прогоняли реальный
 * `getNextPageParam` и клиент `getConversation`, а не их копию.
 */
export function activityFeedQueryOptions(agentId: string, pageSize = PAGE_SIZE) {
  return {
    queryKey: queryKeys.conversation.byAgent(agentId),
    queryFn: ({ pageParam }: { pageParam: ConversationCursor | null }) =>
      agentsApi.getConversation(
        agentId,
        pageSize,
        pageParam?.before ?? null,
        pageParam?.id ?? null,
      ),
    initialPageParam: null as ConversationCursor | null,
    getNextPageParam: (lastPage: ConversationPage) =>
      lastPage.next_before
        ? { before: lastPage.next_before, id: lastPage.next_before_id ?? '' }
        : undefined,
  };
}

function cursorOf(turn: ConversationTurn): ConversationCursor {
  return { before: turn.timestamp, id: turn.id };
}

/**
 * Раскладывает непрерывный список ходов (новейшие сверху) на страницы и
 * пересобирает `pageParams` так, чтобы полный рефетч оставался корректным.
 * Каждая страница несёт курсор своего последнего хода (по нему TanStack
 * пересобирает страницы при рефетче), а у последней берём курсор прежней
 * последней страницы: только он знает, есть ли ещё история за загруженным.
 */
function paginate(
  turns: ConversationTurn[],
  pageSize: number,
  previousTail: ConversationPage | undefined,
): ActivityFeedPages {
  const pages: ConversationPage[] = [];
  for (let start = 0; start < turns.length; start += pageSize) {
    const slice = turns.slice(start, start + pageSize);
    const last = slice[slice.length - 1];
    pages.push({
      turns: slice,
      next_before: last ? last.timestamp : null,
      next_before_id: last ? last.id : null,
    });
  }
  const pageParams: (ConversationCursor | null)[] = pages.map((_, index) => {
    if (index === 0) return null;
    const previousLast = turns[index * pageSize - 1];
    return previousLast ? cursorOf(previousLast) : null;
  });
  const lastPage = pages[pages.length - 1];
  if (lastPage) {
    lastPage.next_before = previousTail?.next_before ?? null;
    lastPage.next_before_id = previousTail?.next_before_id ?? null;
  }
  return { pages, pageParams };
}

// Один live-tail-рефреш на агента: вспышки, наложившиеся друг на друга, не
// гонятся наперегонки и не могут применить устаревший снимок поверх свежего.
const refreshesInFlight = new Map<string, Promise<void>>();

/**
 * Live-tail: с keyset-курсором глубокие страницы неизменяемы, поэтому на
 * realtime-вспышку обновляем только голову ленты. Забираем новейшие страницы
 * до перекрытия с уже загруженной головой — иначе вспышка больше `pageSize`
 * оставила бы непокрытый зазор. Затем пересобираем страницы по `pageSize`,
 * чтобы голова не росла бесконечно за долгую сессию.
 * Нет данных — начальная загрузка ещё в полёте, не трогаем.
 */
export function refreshActivityFeedHead(
  queryClient: QueryClient,
  agentId: string,
  pageSize = PAGE_SIZE,
): Promise<void> {
  const running = refreshesInFlight.get(agentId);
  if (running) return running;

  const task = runHeadRefresh(queryClient, agentId, pageSize).finally(() => {
    refreshesInFlight.delete(agentId);
  });
  refreshesInFlight.set(agentId, task);
  return task;
}

async function runHeadRefresh(
  queryClient: QueryClient,
  agentId: string,
  pageSize: number,
): Promise<void> {
  const key = queryKeys.conversation.byAgent(agentId);
  const cached = queryClient.getQueryData<ActivityFeedPages>(key);
  if (!cached || cached.pages.length === 0) return;

  const newestExisting = cached.pages[0]?.turns[0] ?? null;

  const fetched: ConversationTurn[] = [];
  const fetchedIds = new Set<string>();
  let cursor: ConversationCursor | null = null;
  let covered = false;

  for (let page = 0; page < MAX_CATCH_UP_PAGES; page += 1) {
    const result = await agentsApi.getConversation(
      agentId,
      pageSize,
      cursor?.before ?? null,
      cursor?.id ?? null,
    );
    for (const turn of result.turns) {
      if (fetchedIds.has(turn.id)) continue;
      fetchedIds.add(turn.id);
      fetched.push(turn);
    }
    // Перекрылись с прежней головой или дошли до начала истории — зазора нет.
    covered = newestExisting === null || fetchedIds.has(newestExisting.id) || !result.next_before;
    if (covered) break;
    cursor = { before: result.next_before!, id: result.next_before_id ?? '' };
  }

  if (!covered) {
    throw new Error('activity feed head refresh exceeded the catch-up limit');
  }

  queryClient.setQueryData<ActivityFeedPages>(key, (old) => {
    if (!old || old.pages.length === 0) return old;
    const previousTail = old.pages[old.pages.length - 1];
    const existing = old.pages.flatMap((page) => page.turns);
    const merged = [...fetched, ...existing.filter((turn) => !fetchedIds.has(turn.id))];
    if (merged.length === 0) return old;
    return paginate(merged, pageSize, previousTail);
  });
}

/**
 * Курсорная бесконечная лента ходов. Курсор — пара (timestamp, id) последнего
 * хода страницы: равные `created_at` не теряют и не дублируют ходы на стыках.
 */
export function useActivityFeed(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useInfiniteQuery({
    ...activityFeedQueryOptions(agentId),
    enabled: isValidId,
    staleTime: HISTORICAL_STALE_TIME,
  });
}
