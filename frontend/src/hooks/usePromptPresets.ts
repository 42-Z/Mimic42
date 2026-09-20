'use client';

import { useQuery } from '@tanstack/react-query';
import { getSupabaseClient, type SupabaseBrowserClient } from '@/lib/supabase/client';
import { queryKeys } from '@/lib/queryClient';
import type { PromptPresetRow } from '@/types';

/**
 * Читает справочник пресетов напрямую из Supabase под RLS — как useAgentDetails
 * читает agents. Вынесено из хука отдельной функцией, чтобы фильтр и порядок
 * можно было проверить тестом без react-query.
 */
export async function fetchPromptPresets(
  client: SupabaseBrowserClient,
): Promise<PromptPresetRow[]> {
  const { data, error } = await client
    .from('prompt_presets')
    .select('*')
    .eq('is_active', true)
    .order('sort_order');

  if (error) throw new Error(error.message);
  return (data ?? []) as PromptPresetRow[];
}

export function usePromptPresets() {
  return useQuery({
    queryKey: queryKeys.presets.list(),
    // Справочник правится миграцией, в рамках сессии он неизменен.
    staleTime: Infinity,
    queryFn: () => fetchPromptPresets(getSupabaseClient()),
  });
}
