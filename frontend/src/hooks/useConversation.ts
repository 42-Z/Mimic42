'use client';

import { useInfiniteQuery } from '@tanstack/react-query';
import { agentsApi } from '@/lib/api';
import { queryKeys, HISTORICAL_STALE_TIME } from '@/lib/queryClient';
import { agentIdSchema } from '@/lib/validators';

const PAGE_SIZE = 50;

/**
 * Fetch agent conversation history as grouped turns with infinite scroll.
 */
export function useConversation(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useInfiniteQuery({
    queryKey: queryKeys.conversation.byAgent(agentId),
    queryFn: ({ pageParam = 0 }) => agentsApi.getConversation(agentId, PAGE_SIZE, pageParam),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      return lastPage.length === PAGE_SIZE ? pages.length * PAGE_SIZE : undefined;
    },
    enabled: isValidId,
    staleTime: HISTORICAL_STALE_TIME,
  });
}
