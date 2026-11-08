'use client';

import { useQuery } from '@tanstack/react-query';
import { getSupabaseClient, type SupabaseBrowserClient } from '@/lib/supabase/client';
import { useAccountQueryKeys } from '@/hooks/useAccount';
import type { PresetFavoriteRow } from '@/types';

/**
 * Читает избранное пресетов напрямую из Supabase под RLS. Живые записи
 * соединяются с пресетами на клиенте по preset_id.
 */
export async function fetchPresetFavorites(
  client: SupabaseBrowserClient,
  signal?: AbortSignal,
): Promise<PresetFavoriteRow[]> {
  const request = client
    .from('preset_favorites')
    .select('*')
    .order('created_at');
  const { data, error } = await (signal ? request.abortSignal(signal) : request);

  if (error) throw new Error(error.message);
  return (data ?? []) as PresetFavoriteRow[];
}

export function usePresetFavorites() {
  const queryKeys = useAccountQueryKeys();
  return useQuery({
    queryKey: queryKeys.presets.favorites(),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: 'always',
    refetchOnReconnect: true,
    queryFn: ({ signal }) => fetchPresetFavorites(getSupabaseClient(), signal),
  });
}
