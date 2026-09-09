'use client';

import { useQuery } from '@tanstack/react-query';
import { getSupabaseClient } from '@/lib/supabase/client';
import { queryKeys } from '@/lib/queryClient';
import { agentIdSchema } from '@/lib/validators';
import type { TelegramSessionRow, MessageThreadRow } from '@/types';

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
        .select('*')
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
  phone_number: string | null;
  last_started_at: string | null;
}

/**
 * Fetch Telegram phone numbers and last start times for several agents.
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
          .select('agent_id, phone_number')
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
        details[row.id] = { phone_number: null, last_started_at: row.last_started_at ?? null };
      }
      for (const row of sessionsResult.data ?? []) {
        details[row.agent_id] = {
          ...(details[row.agent_id] ?? { last_started_at: null }),
          phone_number: row.phone_number ?? null,
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
    queryFn: async () => {
      const supabase = getSupabaseClient();
      const since = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();

      const [messagesResult, eventsResult] = await Promise.all([
        supabase
          .from('agent_messages')
          .select('created_at, direction')
          .eq('agent_id', agentId)
          .in('direction', ['incoming', 'agent_response'])
          .gte('created_at', since)
          .order('created_at', { ascending: true }),

        supabase
          .from('agent_events')
          .select('created_at, status, event_type')
          .eq('agent_id', agentId)
          .gte('created_at', since)
          .order('created_at', { ascending: true }),
      ]);

      // Group by day
      const dayMap = new Map<string, { messages: number; actions: number; errors: number }>();

      // Initialize all days
      for (let i = 0; i < days; i++) {
        const d = new Date(Date.now() - (days - 1 - i) * 24 * 60 * 60 * 1000);
        const key = d.toISOString().slice(0, 10);
        dayMap.set(key, { messages: 0, actions: 0, errors: 0 });
      }

      (messagesResult.data ?? []).forEach((m) => {
        const key = m.created_at.slice(0, 10);
        const day = dayMap.get(key);
        if (day) day.messages++;
      });

      (eventsResult.data ?? []).forEach((e) => {
        const key = e.created_at.slice(0, 10);
        const day = dayMap.get(key);
        if (!day) return;
        if (typeof e.event_type === 'string' && e.event_type.startsWith('tool.')) day.actions++;
        if (e.status === 'failed') day.errors++;
      });

      return Array.from(dayMap.entries()).map(([date, counts]) => ({
        date,
        ...counts,
      }));
    },
    enabled: isValidId,
    staleTime: 5 * 60 * 1000,
  });
}
