'use client';

import { useQuery } from '@tanstack/react-query';
import { getSupabaseClient } from '@/lib/supabase/client';
import { queryKeys } from '@/lib/queryClient';
import { agentIdSchema } from '@/lib/validators';
import type {
  TelegramAuthorizationStatus,
  TelegramSessionRow,
  MessageThreadRow,
} from '@/types';

/**
 * Fetch Telegram session for an agent directly from Supabase.
 */
export function useTelegramSession(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: queryKeys.telegram.byAgent(agentId),
    queryFn: async () => {
      const supabase = getSupabaseClient();
      const { data, error } = await supabase
        .from('telegram_sessions')
        // Явный список колонок вместо `*`: api_id и api_hash_ciphertext —
        // секреты Telegram-приложения и в браузер не выгружаются.
        .select(
          'id, agent_id, username, phone_number, authorization_status, last_authorized_at, last_error, created_at, updated_at',
        )
        .eq('agent_id', agentId)
        .maybeSingle();

      if (error) throw error;
      return data as TelegramSessionRow | null;
    },
    enabled: isValidId,
    staleTime: 30_000,
  });
}

/**
 * Fetch all message threads for an agent from Supabase.
 */
export function useMessageThreads(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: queryKeys.threads.byAgent(agentId),
    queryFn: async () => {
      const supabase = getSupabaseClient();
      const { data, error } = await supabase
        .from('message_threads')
        .select('*')
        .eq('agent_id', agentId)
        .order('last_message_at', { ascending: false });

      if (error) throw error;
      return (data ?? []) as MessageThreadRow[];
    },
    enabled: isValidId,
  });
}

/**
 * Fetch dashboard KPI metrics directly from Supabase.
 * Every counter is live: contacts from message_threads, messages from the
 * visible conversation rows, actions and errors from agent_events.
 */
export function useDashboardKPIs(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: queryKeys.analytics.kpis(agentId),
    queryFn: async () => {
      const supabase = getSupabaseClient();
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const todayISO = today.toISOString();

      const [contactsToday, messagesToday, actionsToday, errorsToday] = await Promise.all([
        // Contacts with activity today
        supabase
          .from('message_threads')
          .select('id', { count: 'exact', head: true })
          .eq('agent_id', agentId)
          .gte('last_message_at', todayISO),

        // Visible conversation rows (incoming + agent responses)
        supabase
          .from('agent_messages')
          .select('id', { count: 'exact', head: true })
          .eq('agent_id', agentId)
          .in('direction', ['incoming', 'agent_response'])
          .gte('created_at', todayISO),

        // Tool calls today
        supabase
          .from('agent_events')
          .select('id', { count: 'exact', head: true })
          .eq('agent_id', agentId)
          .like('event_type', 'tool.%')
          .gte('created_at', todayISO),

        // Failed events today
        supabase
          .from('agent_events')
          .select('id', { count: 'exact', head: true })
          .eq('agent_id', agentId)
          .eq('status', 'failed')
          .gte('created_at', todayISO),
      ]);

      return {
        contacts_today: contactsToday.count ?? 0,
        messages_today: messagesToday.count ?? 0,
        actions_today: actionsToday.count ?? 0,
        errors_today: errorsToday.count ?? 0,
      };
    },
    enabled: isValidId,
    staleTime: 60_000,
    refetchInterval: 60_000, // refresh every minute
  });
}

/**
 * Fetch dashboard KPI metrics across all agents of the user from Supabase.
 */
export function useAllAgentsKPIs(agentIds: string[]) {
  const isValid = agentIds.length > 0;

  return useQuery({
    queryKey: queryKeys.analytics.kpisAll(agentIds),
    queryFn: async () => {
      const supabase = getSupabaseClient();
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const todayISO = today.toISOString();

      const [contactsToday, messagesToday, actionsToday, errorsToday] = await Promise.all([
        supabase
          .from('message_threads')
          .select('id', { count: 'exact', head: true })
          .in('agent_id', agentIds)
          .gte('last_message_at', todayISO),

        supabase
          .from('agent_messages')
          .select('id', { count: 'exact', head: true })
          .in('agent_id', agentIds)
          .in('direction', ['incoming', 'agent_response'])
          .gte('created_at', todayISO),

        supabase
          .from('agent_events')
          .select('id', { count: 'exact', head: true })
          .in('agent_id', agentIds)
          .like('event_type', 'tool.%')
          .gte('created_at', todayISO),

        supabase
          .from('agent_events')
          .select('id', { count: 'exact', head: true })
          .in('agent_id', agentIds)
          .eq('status', 'failed')
          .gte('created_at', todayISO),
      ]);

      return {
        contacts_today: contactsToday.count ?? 0,
        messages_today: messagesToday.count ?? 0,
        actions_today: actionsToday.count ?? 0,
        errors_today: errorsToday.count ?? 0,
      };
    },
    enabled: isValid,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}

export interface AgentDetails {
  username: string | null;
  phone_number: string | null;
  authorization_status: TelegramAuthorizationStatus | null;
  last_started_at: string | null;
}

/**
 * Fetch Telegram username, phone numbers, session authorization status and last
 * start times for several agents.
 */
export function useAgentsDetails(agentIds: string[]) {
  const isValid = agentIds.length > 0;

  return useQuery({
    queryKey: queryKeys.agents.detailsAll(agentIds),
    queryFn: async () => {
      const supabase = getSupabaseClient();
      const [sessionsResult, agentsResult] = await Promise.all([
        supabase
          .from('telegram_sessions')
          .select('agent_id, username, phone_number, authorization_status')
          .in('agent_id', agentIds),
        supabase
          .from('agents')
          .select('id, last_started_at')
          .in('id', agentIds),
      ]);

      if (sessionsResult.error) throw sessionsResult.error;
      if (agentsResult.error) throw agentsResult.error;

      const details: Record<string, AgentDetails> = {};
      for (const row of agentsResult.data ?? []) {
        details[row.id] = {
          username: null,
          phone_number: null,
          authorization_status: null,
          last_started_at: row.last_started_at ?? null,
        };
      }
      for (const row of sessionsResult.data ?? []) {
        details[row.agent_id] = {
          ...(details[row.agent_id] ?? { last_started_at: null }),
          username: row.username ?? null,
          phone_number: row.phone_number ?? null,
          authorization_status: row.authorization_status ?? null,
        };
      }
      return details;
    },
    enabled: isValid,
    staleTime: 30_000,
  });
}

/**
 * Fetch analytics data for charts: messages, tool actions and errors per day.
 */
export function useAnalyticsData(agentId: string, days: 7 | 30) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: queryKeys.analytics.byAgent(agentId, days),
    queryFn: async ({ signal }) => {
      const supabase = getSupabaseClient();
      const now = new Date();
      const until = now.toISOString();
      const firstDay = new Date(now);
      firstDay.setUTCHours(0, 0, 0, 0);
      firstDay.setUTCDate(firstDay.getUTCDate() - days + 1);
      const since = firstDay.toISOString();
      type AnalyticsCursor = { created_at: string; id: string };
      const dayMap = new Map<string, { messages: number; actions: number; errors: number }>();

      for (let i = 0; i < days; i++) {
        const d = new Date(firstDay.getTime() + i * 24 * 60 * 60 * 1000);
        const key = d.toISOString().slice(0, 10);
        dayMap.set(key, { messages: 0, actions: 0, errors: 0 });
      }

      const pending = new AbortController();
      const cancel = () => pending.abort(signal.reason);
      signal.addEventListener('abort', cancel, { once: true });
      if (signal.aborted) cancel();

      try {
        await Promise.all([
          (async () => {
            let cursor: AnalyticsCursor | null = null;
            while (true) {
              let query = supabase
                .from('agent_messages')
                .select('id, created_at, direction')
                .eq('agent_id', agentId)
                .in('direction', ['incoming', 'agent_response'])
                .gte('created_at', since)
                .lt('created_at', until);
              if (cursor) {
                query = query.or(
                  `created_at.gt.${cursor.created_at},and(created_at.eq.${cursor.created_at},id.gt.${cursor.id})`,
                );
              }
              const { data, error } = await query
                .order('created_at', { ascending: true })
                .order('id', { ascending: true })
                .limit(500)
                .abortSignal(pending.signal);
              if (error) throw error;
              const rows = data ?? [];
              const last = rows.at(-1);
              if (!last) break;
              for (const message of rows) {
                const key = new Date(message.created_at).toISOString().slice(0, 10);
                const day = dayMap.get(key);
                if (day) day.messages++;
              }
              cursor = last;
            }
          })(),
          (async () => {
            let cursor: AnalyticsCursor | null = null;
            while (true) {
              let query = supabase
                .from('agent_events')
                .select('id, created_at, status, event_type')
                .eq('agent_id', agentId)
                .gte('created_at', since)
                .lt('created_at', until);
              if (cursor) {
                query = query.or(
                  `created_at.gt.${cursor.created_at},and(created_at.eq.${cursor.created_at},id.gt.${cursor.id})`,
                );
              }
              const { data, error } = await query
                .order('created_at', { ascending: true })
                .order('id', { ascending: true })
                .limit(500)
                .abortSignal(pending.signal);
              if (error) throw error;
              const rows = data ?? [];
              const last = rows.at(-1);
              if (!last) break;
              for (const event of rows) {
                const key = new Date(event.created_at).toISOString().slice(0, 10);
                const day = dayMap.get(key);
                if (!day) continue;
                if (event.event_type.startsWith('tool.')) day.actions++;
                if (event.status === 'failed') day.errors++;
              }
              cursor = last;
            }
          })(),
        ]);
      } catch (error) {
        pending.abort();
        throw error;
      } finally {
        signal.removeEventListener('abort', cancel);
      }

      return Array.from(dayMap.entries()).map(([date, counts]) => ({
        date,
        ...counts,
      }));
    },
    enabled: isValidId,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Fetch the agent's lifetime token counters from Supabase.
 * Counters always accumulate; the hook is independent of the day range.
 */
export function useTokenUsage(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: queryKeys.analytics.usage(agentId),
    queryFn: async () => {
      const supabase = getSupabaseClient();
      const { data, error } = await supabase
        .from('agent_token_usage')
        .select('input_tokens, output_tokens')
        .eq('agent_id', agentId)
        .maybeSingle();

      if (error) throw error;
      return {
        input_tokens: data?.input_tokens ?? 0,
        output_tokens: data?.output_tokens ?? 0,
      };
    },
    enabled: isValidId,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}
