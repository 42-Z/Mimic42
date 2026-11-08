'use client';

import { useQuery } from '@tanstack/react-query';
import { getSupabaseClient, type SupabaseBrowserClient } from '@/lib/supabase/client';
import { useAccountQueryKeys } from '@/hooks/useAccount';

export interface PresetAuthor {
  id: string;
  display_name: string | null;
}

/**
 * Авторы выложенных пресетов из представления preset_authors: только
 * display_name, без почты.
 */
export async function fetchPresetAuthors(
  client: SupabaseBrowserClient,
  signal?: AbortSignal,
): Promise<PresetAuthor[]> {
  const request = client.from('preset_authors').select('*');
  const { data, error } = await (signal ? request.abortSignal(signal) : request);
  if (error) throw new Error(error.message);
  return (data ?? []) as PresetAuthor[];
}

export function usePresetAuthors() {
  const queryKeys = useAccountQueryKeys();
  return useQuery({
    queryKey: queryKeys.presets.authors(),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: 'always',
    refetchOnReconnect: true,
    queryFn: ({ signal }) => fetchPresetAuthors(getSupabaseClient(), signal),
  });
}
