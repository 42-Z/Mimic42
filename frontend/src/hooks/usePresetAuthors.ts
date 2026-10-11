'use client';

import { useQuery } from '@tanstack/react-query';
import { getSupabaseClient, type SupabaseBrowserClient } from '@/lib/supabase/client';
import { queryKeys } from '@/lib/queryClient';

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
): Promise<PresetAuthor[]> {
  const { data, error } = await client.from('preset_authors').select('*');
  if (error) throw new Error(error.message);
  return (data ?? []) as PresetAuthor[];
}

export function usePresetAuthors() {
  return useQuery({
    queryKey: queryKeys.presets.authors(),
    queryFn: () => fetchPresetAuthors(getSupabaseClient()),
  });
}
