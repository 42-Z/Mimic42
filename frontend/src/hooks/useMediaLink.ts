'use client';

import { useQuery } from '@tanstack/react-query';
import type { MediaUrlResult } from '@/hooks/useMediaUrl';
import { agentsApi } from '@/lib/api';
import { queryKeys } from '@/lib/queryClient';

/**
 * Ссылка на объект Storage без Authorization: браузер сам шлёт Range.
 * React Query держит ссылку, пока компонент смонтирован, и подписывает
 * заново после 30 минут без монтирования.
 */
export function useMediaLink(
  agentId: string,
  storagePath: string | null | undefined,
): MediaUrlResult {
  const path = storagePath ?? '';
  const { data, isError } = useQuery({
    queryKey: queryKeys.media.link(agentId, path),
    queryFn: () => agentsApi.signMediaLink(agentId, path),
    enabled: Boolean(agentId && path),
    staleTime: Infinity,
    gcTime: 30 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  if (!agentId || !path) return { url: null, status: 'idle' };
  if (isError) return { url: null, status: 'error' };
  if (data) return { url: data.url, status: 'ready' };
  return { url: null, status: 'loading' };
}
