'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { getSupabaseClient } from '@/lib/supabase/client';
import { onboardingApi } from '@/lib/api';
import { queryKeys } from '@/lib/queryClient';
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
  return useQuery({
    queryKey: queryKeys.onboarding.session(),
    queryFn: async () => {
      const supabase = getSupabaseClient();
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error('Not authenticated');

      const { data, error } = await supabase
        .from('agent_onboarding_sessions')
        .select('*')
        .eq('owner_id', user.id)
        .is('completed_agent_id', null)
        .order('created_at', { ascending: false })
        .limit(1)
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
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error('Not authenticated');

      const payload = {
        owner_id: user.id,
        ...update,
        updated_at: new Date().toISOString(),
      };

      const query = sessionId
        ? supabase
            .from('agent_onboarding_sessions')
            .update(payload)
            .eq('id', sessionId)
            .select()
            .single()
        : supabase
            .from('agent_onboarding_sessions')
            .insert(payload)
            .select()
            .single();

      const { data, error } = await query;
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
 * Step 2: Save soul prompt
 */
export function useSaveSoulPrompt() {
  const save = useSaveOnboardingStep();
  return {
    ...save,
    mutateAsync: ({ sessionId, values }: { sessionId: string; values: SoulPromptValues }) =>
      save.mutateAsync({
        sessionId,
        update: { soul_prompt: values.soul_prompt },
      }),
  };
}


/**
 * Step 4a: Start Telegram authorization for the current draft
 */
export function useStartTelegramAuth() {
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
    onSuccess: (result) => {
      if (result.authorization_status === 'authorized' && typeof window !== 'undefined') {
        sessionStorage.removeItem('_m42_tc_state');
      }
      qc.invalidateQueries({ queryKey: queryKeys.onboarding.session() });
    },
  });
}

/**
 * Step 5: Finalize agent creation
 */
export function useFinalizeAgent() {
  const qc = useQueryClient();
  const router = useRouter();

  return useMutation({
    mutationFn: async ({
      onboardingId,
      session,
    }: {
      onboardingId: string;
      session: OnboardingSessionRow;
    }) => {
      const result = await onboardingApi.finalizeAgent(onboardingId, {
        name: session.agent_name ?? 'Мой агент',
        soul_prompt: session.soul_prompt ?? '',
      });

      // Mark onboarding as complete in Supabase
      const supabase = getSupabaseClient();
      await supabase
        .from('agent_onboarding_sessions')
        .update({ completed_agent_id: result.agent_id })
        .eq('id', onboardingId);

      return result;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.onboarding.session() });
      qc.invalidateQueries({ queryKey: queryKeys.agents.list() });
      router.push(`/dashboard`);
    },
  });
}

/**
 * Deletes the current onboarding draft (for the "Start over" action)
 */
export function useDiscardOnboardingDraft() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async (sessionId: string) => {
      const supabase = getSupabaseClient();
      const { error } = await supabase
        .from('agent_onboarding_sessions')
        .delete()
        .eq('id', sessionId);
      if (error) throw error;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.onboarding.session() });
    },
  });
}
