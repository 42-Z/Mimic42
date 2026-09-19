'use client';

import { useInfiniteQuery, type InfiniteData, type QueryClient } from '@tanstack/react-query';
import {
  agentsApi,
  type ConversationCursor,
  type ConversationPage,
} from '@/lib/api';
import { queryKeys, HISTORICAL_STALE_TIME } from '@/lib/queryClient';
import { agentIdSchema } from '@/lib/validators';

const PAGE_SIZE = 50;

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

/**
 * Live-tail: с keyset-курсором глубокие страницы неизменяемы, поэтому на
 * realtime-вспышку перезапрашиваем только новейшую страницу и вклеиваем её в
 * кэшированную первую. Её курсор сохраняем — граница со второй страницей уже
 * загруженных ходов не должна сдвинуться, иначе между ними появятся дыры.
 * Нет данных — начальная загрузка ещё в полёте, не трогаем.
 */
export async function refreshActivityFeedHead(
  queryClient: QueryClient,
  agentId: string,
  pageSize = PAGE_SIZE,
): Promise<void> {
  const key = queryKeys.conversation.byAgent(agentId);
  const cached = queryClient.getQueryData<ActivityFeedPages>(key);
  if (!cached || cached.pages.length === 0) return;

  const head = await agentsApi.getConversation(agentId, pageSize, null, null);

  queryClient.setQueryData<ActivityFeedPages>(key, (old) => {
    if (!old || old.pages.length === 0) return old;
    const [first, ...rest] = old.pages;
    if (!first) return old;
    const headIds = new Set(head.turns.map((turn) => turn.id));
    return {
      ...old,
      pages: [
        {
          ...head,
          turns: [...head.turns, ...first.turns.filter((turn) => !headIds.has(turn.id))],
          next_before: first.next_before,
          next_before_id: first.next_before_id,
        },
        ...rest,
      ],
    };
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
