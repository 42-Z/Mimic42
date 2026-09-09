'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getSupabaseClient } from '@/lib/supabase/client';
import { queryKeys } from '@/lib/queryClient';
import { buildActivityFeed, type ActivityItem, type EventLike, type MessageLike } from '@/lib/activity/normalize';
import type { AgentMessageRow, AgentEventRow, MessageThreadRow, RealtimePayload } from '@/types';
import type { RealtimeChannel } from '@supabase/supabase-js';

const MAX_FEED_ITEMS = 200;
const SEED_ROW_LIMIT = 40;

/** Raw LangChain transcript rows — replaced by typed tool.* events. */
const TRANSCRIPT_DIRECTIONS = new Set(['tool_call', 'tool_result']);

function isTranscriptRow(row: AgentMessageRow): boolean {
  return TRANSCRIPT_DIRECTIONS.has(row.direction ?? '');
}

function dedupeById<T extends { id: string }>(rows: T[]): T[] {
  const seen = new Set<string>();
  return rows.filter((row) => {
    if (seen.has(row.id)) return false;
    seen.add(row.id);
    return true;
  });
}

interface ActivitySeed {
  messages: AgentMessageRow[];
  events: AgentEventRow[];
  peerNames: Map<string, string>;
}

async function fetchActivitySeed(agentIds: string[]): Promise<ActivitySeed> {
  const supabase = getSupabaseClient();
  const [messagesResult, eventsResult, threadsResult] = await Promise.all([
    supabase
      .from('agent_messages')
      .select('*')
      .in('agent_id', agentIds)
      .order('created_at', { ascending: false })
      .limit(SEED_ROW_LIMIT),
    supabase
      .from('agent_events')
      .select('*')
      .in('agent_id', agentIds)
      .order('created_at', { ascending: false })
      .limit(SEED_ROW_LIMIT),
    supabase.from('message_threads').select('*').in('agent_id', agentIds),
  ]);

  if (messagesResult.error) throw messagesResult.error;
  if (eventsResult.error) throw eventsResult.error;
  if (threadsResult.error) throw threadsResult.error;

  const messages = ((messagesResult.data ?? []) as AgentMessageRow[]).reverse();
  const events = ((eventsResult.data ?? []) as AgentEventRow[]).reverse();
  const peerNames = new Map(
    ((threadsResult.data ?? []) as MessageThreadRow[])
      .filter((t) => t.title)
      .map((t) => [t.telegram_peer_id, t.title as string]),
  );
  return { messages, events, peerNames };
}

/**
 * Manages Supabase Realtime subscriptions for an agent's messages and events.
 * Incoming rows are normalized into human-facing activity items; raw tool
 * transcripts are discarded on the client (the typed events replace them).
 *
 * Initial data must be loaded separately (via useAgentMessages / useAgentActions).
 */
export function useRealtimeFeed(agentId: string) {
  const qc = useQueryClient();
  const channelRef = useRef<RealtimeChannel | null>(null);
  const [newMessages, setNewMessages] = useState<AgentMessageRow[]>([]);
  const [newEvents, setNewEvents] = useState<AgentEventRow[]>([]);
  const [isConnected, setIsConnected] = useState(false);

  const addMessage = useCallback((msg: AgentMessageRow) => {
    if (isTranscriptRow(msg)) return;
    setNewMessages((prev) => {
      const updated = [...prev, msg];
      return updated.length > MAX_FEED_ITEMS
        ? updated.slice(updated.length - MAX_FEED_ITEMS)
        : updated;
    });
    qc.invalidateQueries({ queryKey: queryKeys.messages.byAgent(agentId) });
    // A brand-new contact must resolve to a human name promptly.
    qc.invalidateQueries({ queryKey: queryKeys.threads.byAgent(agentId) });
  }, [agentId, qc]);

  const addEvent = useCallback((event: AgentEventRow) => {
    setNewEvents((prev) => {
      const updated = [...prev, event];
      return updated.length > MAX_FEED_ITEMS
        ? updated.slice(updated.length - MAX_FEED_ITEMS)
        : updated;
    });
    qc.invalidateQueries({ queryKey: queryKeys.actions.byAgent(agentId) });
  }, [agentId, qc]);

  useEffect(() => {
    if (!agentId) return;

    // A new agent must not inherit rows from the previous one.
    setNewMessages([]);
    setNewEvents([]);

    const supabase = getSupabaseClient();
    const channelName = `agent-feed-${agentId}`;

    const channel = supabase
      .channel(channelName)
      .on<AgentMessageRow>(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'agent_messages',
          filter: `agent_id=eq.${agentId}`,
        },
        (payload: RealtimePayload<AgentMessageRow>) => {
          addMessage(payload.new);
        }
      )
      .on<AgentEventRow>(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'agent_events',
          filter: `agent_id=eq.${agentId}`,
        },
        (payload: RealtimePayload<AgentEventRow>) => {
          addEvent(payload.new);
        }
      )
      .subscribe((status) => {
        setIsConnected(status === 'SUBSCRIBED');
      });

    channelRef.current = channel;

    return () => {
      supabase.removeChannel(channel);
      channelRef.current = null;
      setIsConnected(false);
    };
  }, [agentId, addMessage, addEvent]);

  const items: ActivityItem[] = buildActivityFeed(
    newMessages as unknown as MessageLike[],
    newEvents as unknown as EventLike[],
  );

  return {
    items,
    isConnected,
    clearFeed: () => {
      setNewMessages([]);
      setNewEvents([]);
    },
  };
}

/**
 * Live feed merged across multiple agents over a single realtime channel.
 * Seeded with the most recent rows so the feed is populated right after
 * page load, then extended by realtime increments. Rows are normalized the
 * same way as the per-agent feed.
 */
export function useMultiAgentRealtimeFeed(agentIds: string[]) {
  const qc = useQueryClient();
  const [newMessages, setNewMessages] = useState<AgentMessageRow[]>([]);
  const [newEvents, setNewEvents] = useState<AgentEventRow[]>([]);
  const [isConnected, setIsConnected] = useState(false);

  const agentKey = [...agentIds].sort().join(',');

  const { data: seed, refetch: refetchSeed } = useQuery<ActivitySeed>({
    queryKey: ['agent-feed-seed', agentKey],
    queryFn: () => fetchActivitySeed(agentIds),
    enabled: agentIds.length > 0,
    staleTime: 30_000,
    // Keep the feed fresh even if the websocket subscription stalls.
    refetchInterval: 60_000,
  });

  useEffect(() => {
    if (!agentKey) {
      setNewMessages([]);
      setNewEvents([]);
      return;
    }

    const supabase = getSupabaseClient();
    const channelName = 'agent-feed-all';
    const filter = `agent_id=in.(${agentKey})`;

    setNewMessages([]);
    setNewEvents([]);

    const channel = supabase
      .channel(channelName)
      .on<AgentMessageRow>(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'agent_messages',
          filter,
        },
        (payload: RealtimePayload<AgentMessageRow>) => {
          const msg = payload.new;
          if (isTranscriptRow(msg)) return;
          setNewMessages((prev) => {
            const updated = [...prev, msg];
            return updated.length > MAX_FEED_ITEMS
              ? updated.slice(updated.length - MAX_FEED_ITEMS)
              : updated;
          });
          qc.invalidateQueries({ queryKey: queryKeys.messages.byAgent(msg.agent_id) });
        }
      )
      .on<AgentEventRow>(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'agent_events',
          filter,
        },
        (payload: RealtimePayload<AgentEventRow>) => {
          const event = payload.new;
          setNewEvents((prev) => {
            const updated = [...prev, event];
            return updated.length > MAX_FEED_ITEMS
              ? updated.slice(updated.length - MAX_FEED_ITEMS)
              : updated;
          });
          qc.invalidateQueries({ queryKey: queryKeys.actions.byAgent(event.agent_id) });
        }
      )
      .subscribe((status) => {
        setIsConnected(status === 'SUBSCRIBED');
      });

    return () => {
      supabase.removeChannel(channel);
      setIsConnected(false);
    };
  }, [agentKey, qc]);

  // Merge the seed (recent history) with realtime increments, then normalize.
  const mergedMessages = dedupeById([...(seed?.messages ?? []), ...newMessages]).slice(
    -MAX_FEED_ITEMS,
  );
  const mergedEvents = dedupeById([...(seed?.events ?? []), ...newEvents]).slice(
    -MAX_FEED_ITEMS,
  );

  const items: ActivityItem[] = buildActivityFeed(
    mergedMessages as unknown as MessageLike[],
    mergedEvents as unknown as EventLike[],
  );

  return {
    items,
    peerNames: seed?.peerNames ?? new Map<string, string>(),
    isConnected,
    refetchSeed,
    clearFeed: () => {
      setNewMessages([]);
      setNewEvents([]);
    },
  };
}

/**
 * Subscribes to agent state changes in Supabase.
 * Invalidates the agent status query when the state changes.
 */
export function useAgentStatusRealtime(agentId: string) {
  const qc = useQueryClient();
  const channelRef = useRef<RealtimeChannel | null>(null);

  useEffect(() => {
    if (!agentId) return;

    const supabase = getSupabaseClient();
    const channelName = `agent-status-${agentId}`;

    const channel = supabase
      .channel(channelName)
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'agents',
          filter: `id=eq.${agentId}`,
        },
        () => {
          qc.invalidateQueries({ queryKey: queryKeys.agents.detail(agentId) });
          qc.invalidateQueries({ queryKey: queryKeys.agents.list() });
        }
      )
      .subscribe();

    channelRef.current = channel;

    return () => {
      supabase.removeChannel(channel);
      channelRef.current = null;
    };
  }, [agentId, qc]);
}

/**
 * Subscribes to status changes of any agent the user owns (RLS filters the rest)
 * and refreshes the agent list.
 */
export function useAllAgentsStatusRealtime() {
  const qc = useQueryClient();

  useEffect(() => {
    const supabase = getSupabaseClient();

    const channel = supabase
      .channel('agents-status-all')
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'agents',
        },
        () => {
          qc.invalidateQueries({ queryKey: queryKeys.agents.list() });
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [qc]);
}
