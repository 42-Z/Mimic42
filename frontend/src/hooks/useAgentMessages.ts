'use client';

import { useInfiniteQuery } from '@tanstack/react-query';
import { agentsApi } from '@/lib/api';
import { queryKeys, HISTORICAL_STALE_TIME } from '@/lib/queryClient';
import { agentIdSchema } from '@/lib/validators';

const PAGE_SIZE = 50;

/**
 * Fetch agent message history with infinite scroll pagination.
 */
export function useAgentMessages(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useInfiniteQuery({
    queryKey: queryKeys.messages.byAgentPaged(agentId, PAGE_SIZE),
    queryFn: ({ pageParam = 0 }) => agentsApi.getMessages(agentId, PAGE_SIZE, pageParam),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      return lastPage.length === PAGE_SIZE ? pages.length * PAGE_SIZE : undefined;
    },
    enabled: isValidId,
    staleTime: HISTORICAL_STALE_TIME,
    select: (data) => {
      const all = data.pages.flat();
      return [...all].sort(
        (a, b) =>
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      );
    },
  });
}

/**
 * Fetch agent action/event history with infinite scroll pagination.
 */
export function useAgentActions(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useInfiniteQuery({
    queryKey: queryKeys.actions.byAgentPaged(agentId, PAGE_SIZE),
    queryFn: ({ pageParam = 0 }) => agentsApi.getActions(agentId, PAGE_SIZE, pageParam),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      return lastPage.length === PAGE_SIZE ? pages.length * PAGE_SIZE : undefined;
    },
    enabled: isValidId,
    staleTime: HISTORICAL_STALE_TIME,
    select: (data) => {
      const all = data.pages.flat();
      return [...all].sort(
        (a, b) =>
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      );
    },
  });
}
