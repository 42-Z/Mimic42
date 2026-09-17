'use client';

import { useInfiniteQuery } from '@tanstack/react-query';
import { agentsApi, type ConversationCursor } from '@/lib/api';
import { queryKeys, HISTORICAL_STALE_TIME } from '@/lib/queryClient';
import { agentIdSchema } from '@/lib/validators';

const PAGE_SIZE = 50;

/**
 * Курсорная бесконечная лента ходов. Курсор — пара (timestamp, id) последнего
 * хода страницы: равные `created_at` не теряют и не дублируют ходы на стыках.
 */
export function useActivityFeed(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useInfiniteQuery({
    queryKey: queryKeys.conversation.byAgent(agentId),
    queryFn: ({ pageParam }: { pageParam: ConversationCursor | null }) =>
      agentsApi.getConversation(agentId, PAGE_SIZE, pageParam?.before ?? null, pageParam?.id ?? null),
    initialPageParam: null as ConversationCursor | null,
    getNextPageParam: (lastPage) =>
      lastPage.next_before
        ? { before: lastPage.next_before, id: lastPage.next_before_id ?? '' }
        : undefined,
    enabled: isValidId,
    staleTime: HISTORICAL_STALE_TIME,
  });
}
