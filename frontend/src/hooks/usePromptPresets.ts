'use client';

import { useQuery } from '@tanstack/react-query';
import { getSupabaseClient, type SupabaseBrowserClient } from '@/lib/supabase/client';
import { useAccountQueryKeys } from '@/hooks/useAccount';
import type { PromptPresetRow } from '@/types';

/**
 * Читает справочник пресетов напрямую из Supabase под RLS — как useAgentDetails
 * читает agents. Вынесено из хука отдельной функцией, чтобы фильтр и порядок
 * можно было проверить тестом без react-query.
 */
export async function fetchPromptPresets(
  client: SupabaseBrowserClient,
  signal?: AbortSignal,
): Promise<PromptPresetRow[]> {
  const request = client
    .from('prompt_presets')
    .select('*')
    .order('sort_order');
  const { data, error } = await (signal ? request.abortSignal(signal) : request);

  if (error) throw new Error(error.message);
  return (data ?? []) as PromptPresetRow[];
}

export function usePromptPresets() {
  const queryKeys = useAccountQueryKeys();
  return useQuery({
    queryKey: queryKeys.presets.list(),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: 'always',
    refetchOnReconnect: true,
    queryFn: ({ signal }) => fetchPromptPresets(getSupabaseClient(), signal),
  });
}
