'use client';

import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { MediaUrlResult } from '@/hooks/useMediaUrl';
import { useAccountApi } from '@/hooks/useAccountApi';
import { useAccountQueryKeys } from '@/hooks/useAccount';

export interface MediaLinkResult extends MediaUrlResult {
  refresh: () => Promise<string | null>;
}

/** Ссылка без Authorization для Range-запросов; обновляется до истечения TTL. */
export function useMediaLink(
  agentId: string,
  storagePath: string | null | undefined,
): MediaLinkResult {
  const { agents: agentsApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const path = storagePath ?? '';
  const { data, isError, refetch } = useQuery({
    queryKey: queryKeys.media.link(agentId, path),
    queryFn: async () => {
      const requestedAt = Date.now();
      const link = await agentsApi.signMediaLink(agentId, path);
      return { ...link, renewAt: requestedAt + link.expires_in * 1000 * 0.9 };
    },
    enabled: Boolean(agentId && path),
    staleTime: (query) => Math.max(0, (query.state.data?.renewAt ?? 0) - query.state.dataUpdatedAt),
    gcTime: 30 * 60_000,
    refetchInterval: (query) =>
      query.state.status === 'error' || query.state.fetchStatus !== 'idle' || !query.state.data
        ? false
        : Math.max(1, query.state.data.renewAt - Date.now()),
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    retry: false,
  });

  const refresh = useCallback(async () => {
    if (!agentId || !path) return null;
    const result = await refetch({ cancelRefetch: false });
    return result.isError ? null : (result.data?.url ?? null);
  }, [agentId, path, refetch]);

  if (!agentId || !path) return { url: null, status: 'idle', refresh };
  if (data) return { url: data.url, status: 'ready', refresh };
  if (isError) return { url: null, status: 'error', refresh };
  return { url: null, status: 'loading', refresh };
}
