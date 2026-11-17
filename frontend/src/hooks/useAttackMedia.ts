'use client';

import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';

import { useAccountApi } from '@/hooks/useAccountApi';
import { useAccountQueryKeys } from '@/hooks/useAccount';
import type { MediaUrlResult } from '@/hooks/useMediaUrl';
import type { AttackImage, AttackMedia } from '@/types';

export interface AttackMediaLinkResult extends MediaUrlResult {
  refresh: () => Promise<string | null>;
}

/**
 * Подписанная ссылка на картинку пула атаки. Если ответ уже принёс `url`,
 * запрос не нужен; иначе ссылка продлевается до истечения TTL.
 */
export function useAttackMediaLink(
  media: AttackImage | AttackMedia | null | undefined,
): AttackMediaLinkResult {
  const { attacks: attacksApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const path = media?.path ?? '';
  const presetUrl = media && 'url' in media ? (media.url ?? null) : null;

  const { data, isError, refetch } = useQuery({
    queryKey: queryKeys.attacks.media(path),
    queryFn: async () => {
      const requestedAt = Date.now();
      const link = await attacksApi.mediaLink(path);
      return { ...link, renewAt: requestedAt + link.expires_in * 1000 * 0.9 };
    },
    enabled: Boolean(path) && !presetUrl,
    staleTime: (query) =>
      Math.max(0, (query.state.data?.renewAt ?? 0) - query.state.dataUpdatedAt),
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
    if (!path || presetUrl) return presetUrl;
    const result = await refetch({ cancelRefetch: false });
    return result.isError ? null : (result.data?.url ?? null);
  }, [path, presetUrl, refetch]);

  if (presetUrl) return { url: presetUrl, status: 'ready', refresh };
  if (!path) return { url: null, status: 'idle', refresh };
  if (data) return { url: data.url, status: 'ready', refresh };
  if (isError) return { url: null, status: 'error', refresh };
  return { url: null, status: 'loading', refresh };
}
