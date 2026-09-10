'use client';

import { useQuery } from '@tanstack/react-query';
import { agentsApi } from '@/lib/api';
import { queryKeys, HISTORICAL_STALE_TIME } from '@/lib/queryClient';
import { agentIdSchema } from '@/lib/validators';

/**
 * Fetch agent message history from FastAPI backend.
 */
export function useAgentMessages(agentId: string, limit = 50) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: queryKeys.messages.byAgentPaged(agentId, limit),
    queryFn: () => agentsApi.getMessages(agentId, limit),
    enabled: isValidId,
    staleTime: HISTORICAL_STALE_TIME,
    select: (data) =>
      [...data].sort(
        (a, b) =>
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      ),
  });
}

/**
 * Fetch agent action/event history from FastAPI backend.
 */
export function useAgentActions(agentId: string, limit = 50) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: queryKeys.actions.byAgentPaged(agentId, limit),
    queryFn: () => agentsApi.getActions(agentId, limit),
    enabled: isValidId,
    staleTime: HISTORICAL_STALE_TIME,
    select: (data) =>
      [...data].sort(
        (a, b) =>
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      ),
  });
}
