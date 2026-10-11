'use client';

import { useQuery } from '@tanstack/react-query';
import { getSupabaseClient, type SupabaseBrowserClient } from '@/lib/supabase/client';
import { queryKeys } from '@/lib/queryClient';
import type { PresetFavoriteRow } from '@/types';

/**
 * Читает избранное пресетов напрямую из Supabase под RLS. Живые записи
 * соединяются с пресетами на клиенте по preset_id.
 */
export async function fetchPresetFavorites(
  client: SupabaseBrowserClient,
): Promise<PresetFavoriteRow[]> {
  const { data, error } = await client
    .from('preset_favorites')
    .select('*')
    .order('created_at');

  if (error) throw new Error(error.message);
  return (data ?? []) as PresetFavoriteRow[];
}

export function usePresetFavorites() {
  return useQuery({
    queryKey: queryKeys.presets.favorites(),
    queryFn: () => fetchPresetFavorites(getSupabaseClient()),
  });
}
