'use client';

import { useQuery } from '@tanstack/react-query';
import { useAccountApi } from '@/hooks/useAccountApi';
import { HISTORICAL_STALE_TIME } from '@/lib/queryClient';
import { useAccountQueryKeys } from '@/hooks/useAccount';
import { agentIdSchema } from '@/lib/validators';

/**
 * Fetch agent memories (supports query string for semantic search).
 */
export function useAgentMemories(agentId: string, query?: string) {
  const { memory: agentMemoryApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: queryKeys.memories.byAgentSearch(agentId, query),
    queryFn: () => agentMemoryApi.list(agentId, query),
    enabled: isValidId,
    staleTime: 5000, // Short stale time for fresh memory search/listing
  });
}

/**
 * Fetch history for a specific memory item.
 */
export function useAgentMemoryHistory(agentId: string, memoryId: string, enabled = true) {
  const { memory: agentMemoryApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: queryKeys.memories.history(agentId, memoryId),
    queryFn: () => agentMemoryApi.getHistory(agentId, memoryId),
    enabled: isValidId && !!memoryId && enabled,
    staleTime: HISTORICAL_STALE_TIME,
  });
}
