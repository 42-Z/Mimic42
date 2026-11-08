'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getSupabaseClient } from '@/lib/supabase/client';
import { useAccountApi } from '@/hooks/useAccountApi';
import { useAccount, useAccountQueryKeys } from '@/hooks/useAccount';
import type {
  OnboardingSessionRow,
  OnboardingStep,
  OnboardingPublicStatus,
} from '@/types';
import type {
  AgentNameValues,
  SoulPromptValues,
  TelegramCredentialsValues,
} from '@/lib/validators';
import type { Json } from '@/types/supabase';

/**
 * Determines the current onboarding step from the session row.
 */
export function deriveOnboardingStep(session: OnboardingSessionRow | null | undefined): OnboardingStep {
  if (!session || !session.agent_name) return 'name';
  if (!session.soul_prompt) return 'soul';

  const authStatus = session.authorization_status;
  if (authStatus === 'not_started') return 'telegram_credentials';
  if (authStatus === 'code_requested') return 'telegram_code';
  if (authStatus === 'password_required') return 'telegram_2fa';

  if (authStatus === 'authorized' && !session.completed_agent_id) return 'finalize';

  return 'finalize'; // fallback
}

/**
 * Fetches the current onboarding draft from Supabase.
 * Only sessions without a completed agent are returned, so finished
 * wizard runs never block creating a new agent.
 * Returns null if no draft exists yet.
 */
export function useOnboardingSession() {
  const account = useAccount();
  const queryKeys = useAccountQueryKeys();
  return useQuery({
    queryKey: queryKeys.onboarding.session(),
    queryFn: async ({ signal }) => {
      const supabase = getSupabaseClient();
      signal.throwIfAborted();
      account?.controller.signal.throwIfAborted();
      if (!account?.userId) throw new Error('Not authenticated');

      const { data, error } = await supabase
        .from('agent_onboarding_sessions')
        .select('*')
        .eq('owner_id', account.userId)
        .is('completed_agent_id', null)
        .order('created_at', { ascending: false })
        .limit(1)
        .abortSignal(signal)
        .maybeSingle();

      if (error) throw error;
      return data as OnboardingSessionRow | null;
    },
    staleTime: 10_000,
  });
}

/**
 * Hook for saving onboarding step data to Supabase.
 * With sessionId === null inserts a new draft row (the database generates the id),
 * otherwise updates the existing draft.
 */
export function useSaveOnboardingStep() {
  const account = useAccount();
  const queryKeys = useAccountQueryKeys();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async ({
      sessionId,
      update,
    }: {
      sessionId: string | null;
      update: Partial<OnboardingSessionRow>;
    }) => {
      const supabase = getSupabaseClient();
      account?.controller.signal.throwIfAborted();
      if (!account?.userId) throw new Error('Not authenticated');

      const { settings, ...rest } = update;
      const payload = {
        ...rest,
        owner_id: account.userId,
        // OnboardingSessionRow is a manual mirror, wider than the generated
        // Json type: cast settings at the supabase-js boundary, as in
        // useUpdateAgentSettings.
        ...(settings != null ? { settings: settings as Json } : {}),
        updated_at: new Date().toISOString(),
      };

      const query = sessionId
        ? supabase
            .from('agent_onboarding_sessions')
            .update(payload)
            .eq('id', sessionId)
            .select()
        : supabase
            .from('agent_onboarding_sessions')
            .insert(payload)
            .select();

      const { data, error } = await (account ? query.abortSignal(account.controller.signal) : query).single();
      if (error) throw error;
      return data as OnboardingSessionRow;
    },
    onSuccess: (row) => {
      // Write the row into the cache immediately: deriveOnboardingStep moves
      // to the next step without waiting for the refetch, which also prevents
      // a second submit from inserting a duplicate draft.
      qc.setQueryData(queryKeys.onboarding.session(), row);
      qc.invalidateQueries({ queryKey: queryKeys.onboarding.session() });
    },
  });
}

/**
 * Step 1: Save agent name — creates the draft row when sessionId is null
 */
export function useSaveAgentName() {
  const save = useSaveOnboardingStep();
  return {
    ...save,
    mutateAsync: ({ sessionId, values }: { sessionId: string | null; values: AgentNameValues }) =>
      save.mutateAsync({ sessionId, update: { agent_name: values.name } }),
  };
}

/**
 * Step 2: Save soul prompt and the preset's tool settings (if any)
 */
export function useSaveSoulPrompt() {
  const save = useSaveOnboardingStep();
  return {
    ...save,
    mutateAsync: ({
      sessionId,
      values,
      settings,
    }: {
      sessionId: string;
      values: SoulPromptValues;
      settings?: Record<string, unknown> | null;
    }) =>
      save.mutateAsync({
        sessionId,
        update: {
          soul_prompt: values.soul_prompt,
          // Пресет без настроек не трогает уже сохранённый черновик.
          ...(settings ? { settings } : {}),
        },
      }),
  };
}

/**
 * Step 4a: Start Telegram authorization for the current draft
 */
export function useStartTelegramAuth() {
  const { onboarding: onboardingApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async ({
      onboardingId,
      values,
    }: {
      onboardingId: string | null;
      values: TelegramCredentialsValues;
    }) => {
      const result = await onboardingApi.startTelegram({
        phone_number: values.phone_number,
        onboarding_id: onboardingId,
      });

      return result as OnboardingPublicStatus;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.onboarding.session() });
    },
  });
}

/**
 * Step 4b: Submit Telegram code (and optionally 2FA password)
 */
export function useSubmitTelegramCode() {
  const { onboarding: onboardingApi } = useAccountApi();
  const queryKeys = useAccountQueryKeys();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async ({
      onboardingId,
      code,
      password,
    }: {
      onboardingId: string;
      code: string;
      password?: string;
    }) => {
      const result = await onboardingApi.submitCode(onboardingId, {
        code,
        password,
      });

      return result;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.onboarding.session() });
    },
  });
}

/**
 * Step 5: Finalize agent creation
 */
export function useFinalizeAgent() {
  const { onboarding: onboardingApi } = useAccountApi();
  const account = useAccount();
  return useMutation({
    mutationFn: async ({
      onboardingId,
      session,
    }: {
      onboardingId: string;
      session: OnboardingSessionRow;
    }) => {
      // Бэкенд сам помечает черновик завершённым вместе с созданием агента:
      // отдельный клиентский апдейт мог упасть и блокировал переход на дашборд.
      return await onboardingApi.finalizeAgent(onboardingId, {
        name: session.agent_name ?? 'Мой агент',
        soul_prompt: session.soul_prompt ?? '',
      });
    },
    onSuccess: () => {
      if (account?.controller.signal.aborted) return;
      // Полная навигация вместо router.push: клиентский Router Cache мог
      // сохранить префетч /dashboard → /onboarding (сделанный, пока агента
      // ещё не было), и push вернул бы на онбординг без запроса к серверу.
      window.location.assign('/dashboard');
    },
  });
}

/**
 * Deletes the current onboarding draft (for the "Start over" action)
 */
export function useDiscardOnboardingDraft() {
  const account = useAccount();
  const queryKeys = useAccountQueryKeys();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async (sessionId: string) => {
      const supabase = getSupabaseClient();
      account?.controller.signal.throwIfAborted();
      const request = supabase
        .from('agent_onboarding_sessions')
        .delete()
        .eq('id', sessionId);
      const { error } = await (account ? request.abortSignal(account.controller.signal) : request);
      if (error) throw error;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.onboarding.session() });
    },
  });
}
