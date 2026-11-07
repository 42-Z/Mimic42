'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAccountApi } from '@/hooks/useAccountApi';
import { getSupabaseClient } from '@/lib/supabase/client';
import { STATUS_STALE_TIME } from '@/lib/queryClient';
import { useAccount, useAccountQueryKeys } from '@/hooks/useAccount';
import { agentIdSchema } from '@/lib/validators';
import type { AgentRow, AgentSettingsForm } from '@/types';
import type { Json } from '@/types/supabase';

/**
 * Fetch single agent status from FastAPI backend.
 */
export function useAgentStatus(agentId: string) {
  const { agents: agentsApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
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
  const queryKeys = useAccountQueryKeys();
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: [...queryKeys.agents.detail(agentId), 'full'],
    queryFn: async ({ signal }) => {
      const supabase = getSupabaseClient();
      const { data, error } = await supabase
        .from('agents')
        .select('*')
        .eq('id', agentId)
        .abortSignal(signal)
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
  const account = useAccount();
  const queryKeys = useAccountQueryKeys();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async (values: Partial<AgentSettingsForm>) => {
      const supabase = getSupabaseClient();
      account?.controller.signal.throwIfAborted();
      const request = supabase
        .from('agents')
        .update({
          name: values.name,
          soul_prompt: values.soul_prompt,
          settings: values.settings as Json,
          updated_at: new Date().toISOString(),
        })
        .eq('id', agentId)
        .select();
      const { data, error } = await (account ? request.abortSignal(account.controller.signal) : request).single();

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
  const { agents: agentsApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
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
 * на каждый возврат в окно; новые чаты подтягивает кнопка «Обновить список», а запуск
 * и остановка агента сбрасывают список вместе со всем `agents`.
 */
export function useAgentChats(agentId: string) {
  const { agents: agentsApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: queryKeys.agents.chats(agentId),
    queryFn: () => agentsApi.listChats(agentId),
    enabled: isValidId,
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

/** Включить восстановление: сервер сам записывает выбор, форма настроек не участвует. */
export function useStartWarmupRecovery(agentId: string) {
  const { agents: agentsApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: () => agentsApi.startWarmupRecovery(agentId),
    onSuccess: (state) => {
      qc.setQueryData([...queryKeys.agents.detail(agentId), 'warmup'], state);
    },
  });
}

/**
 * Наличие облачного пароля. Запрос идёт только когда форма пароля открыта:
 * просмотр вкладки остановленного агента не должен поднимать Telegram-клиент.
 */
export function useTelegramPasswordState(agentId: string, enabled: boolean) {
  const { agents: agentsApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: queryKeys.telegram.password(agentId),
    queryFn: () => agentsApi.getTelegramPasswordState(agentId),
    enabled: isValidId && enabled,
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  });
}
