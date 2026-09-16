'use client';

import { useInfiniteQuery } from '@tanstack/react-query';
import { agentsApi } from '@/lib/api';
import { queryKeys, HISTORICAL_STALE_TIME } from '@/lib/queryClient';
import { agentIdSchema } from '@/lib/validators';

const PAGE_SIZE = 50;

/**
 * Курсорная бесконечная лента ходов: страница запрашивается строго старше
 * последнего показанного хода, поэтому стыки страниц не теряют и не дублируют
 * ходы.
 */
export function useActivityFeed(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useInfiniteQuery({
    queryKey: queryKeys.conversation.byAgent(agentId),
    queryFn: ({ pageParam }) =>
      agentsApi.getConversation(agentId, PAGE_SIZE, pageParam ?? null),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_before ?? undefined,
    enabled: isValidId,
    staleTime: HISTORICAL_STALE_TIME,
  });
}

export const ACTIVITY_PAGE_SIZE = PAGE_SIZE;
