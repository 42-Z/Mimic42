'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { agentsApi } from '@/lib/api';
import { getSupabaseClient } from '@/lib/supabase/client';
import { queryKeys, STATUS_STALE_TIME } from '@/lib/queryClient';
import { agentIdSchema } from '@/lib/validators';
import type { AgentRow, AgentSettingsForm } from '@/types';
import type { Json } from '@/types/supabase';

/**
 * Fetch single agent status from FastAPI backend.
 */
export function useAgentStatus(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: queryKeys.agents.detail(agentId),
    queryFn: () => agentsApi.get(agentId),
    enabled: isValidId,
    staleTime: STATUS_STALE_TIME,
    refetchInterval: (query) => {
      // Poll more frequently when agent is transitioning states
      const state = query.state.data?.state;
      if (state === 'starting' || state === 'stopping') {
        return 3_000;
      }
      return false; // rely on realtime for stable states
    },
  });
}

/**
 * Fetch full agent row from Supabase (includes soul_prompt, system_prompt, settings).
 */
export function useAgentDetails(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: [...queryKeys.agents.detail(agentId), 'full'],
    queryFn: async () => {
      const supabase = getSupabaseClient();
      const { data, error } = await supabase
        .from('agents')
        .select('*')
        .eq('id', agentId)
        .single();

      if (error) throw error;
      return data as AgentRow;
    },
    enabled: isValidId,
  });
}

/**
 * Update agent settings in Supabase.
 * RLS ensures user can only update their own agents.
 */
export function useUpdateAgentSettings(agentId: string) {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async (values: Partial<AgentSettingsForm>) => {
      const supabase = getSupabaseClient();
      const { data, error } = await supabase
        .from('agents')
        .update({
          name: values.name,
          soul_prompt: values.soul_prompt,
          settings: values.settings as Json,
          updated_at: new Date().toISOString(),
        })
        .eq('id', agentId)
        .select()
        .single();

      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.agents.detail(agentId) });
      qc.invalidateQueries({ queryKey: queryKeys.agents.list() });
    },
  });
}

/**
 * Ограничение аккаунта Telegram и режим восстановления: ведёт сервер, поэтому
 * читается отдельно от настроек и обновляется опросом, пока агент работает.
 */
export function useWarmupState(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: [...queryKeys.agents.detail(agentId), 'warmup'],
    queryFn: () => agentsApi.getWarmupState(agentId),
    enabled: isValidId,
    refetchInterval: 30_000,
  });
}

/**
 * Диалоги аккаунта для настройки «Чаты и каналы». Читаются из клиента запущенного
 * агента: 409 — штатное «агент не запущен», поэтому без повторов и без перезапроса
 * на каждый возврат в окно (список кешируется на бэкенде на минуту).
 */
export function useAgentChats(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: [...queryKeys.agents.detail(agentId), 'chats'],
    queryFn: () => agentsApi.listChats(agentId),
    enabled: isValidId,
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

/** Включить восстановление: сервер сам записывает выбор, форма настроек не участвует. */
export function useStartWarmupRecovery(agentId: string) {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: () => agentsApi.startWarmupRecovery(agentId),
    onSuccess: (state) => {
      qc.setQueryData([...queryKeys.agents.detail(agentId), 'warmup'], state);
    },
  });
}
