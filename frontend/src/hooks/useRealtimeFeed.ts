'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { getSupabaseClient } from '@/lib/supabase/client';
import { queryKeys } from '@/lib/queryClient';
import type { AgentMessageRow, AgentEventRow, ConversationTurn, FeedItem, ToolCallRecord, RealtimePayload } from '@/types';
import type { RealtimeChannel } from '@supabase/supabase-js';

const MAX_FEED_ITEMS = 200;

export function useRealtimeFeed(agentId: string) {
  const qc = useQueryClient();
  const channelRef = useRef<RealtimeChannel | null>(null);
  const [newTurns, setNewTurns] = useState<ConversationTurn[]>([]);
  const [isConnected, setIsConnected] = useState(false);

  const addTurn = useCallback((turn: ConversationTurn) => {
    setNewTurns((prev) => {
      const updated = [...prev, turn];
      if (updated.length > MAX_FEED_ITEMS) {
        return updated.slice(updated.length - MAX_FEED_ITEMS);
      }
      return updated;
    });
    qc.invalidateQueries({ queryKey: queryKeys.conversation.byAgent(agentId) });
  }, [agentId, qc]);

  const addMessage = useCallback((msg: AgentMessageRow) => {
    const isIncoming = msg.direction === 'incoming' || msg.direction === 'dashboard_trigger';
    const turn: ConversationTurn = {
      id: msg.id,
      agent_id: agentId,
      timestamp: msg.created_at,
      peer_id: msg.peer || String(msg.payload?.peer ?? ''),
      peer_name: String(msg.payload?.peer_name ?? ''),
      agent_name: String(msg.payload?.agent_name ?? ''),
      incoming: isIncoming ? msg.content : '',
      outgoing: isIncoming ? '' : msg.content,
      direction: isIncoming ? 'incoming' : 'outgoing',
      tools: [],
    };
    addTurn(turn);
  }, [agentId, addTurn]);

  const addEvent = useCallback((event: AgentEventRow) => {
    const started = (event as unknown as Record<string, unknown>).started_at;
    const completed = (event as unknown as Record<string, unknown>).completed_at;
    let duration_ms = 0;
    if (typeof started === 'string' && typeof completed === 'string') {
      const ms = new Date(completed).getTime() - new Date(started).getTime();
      if (Number.isFinite(ms) && ms >= 0) duration_ms = ms;
    }
    const tool: ToolCallRecord = {
      id: event.id,
      name: event.event_type,
      status: event.status,
      payload: event.payload ?? undefined,
      result: event.result,
      error: event.error,
      duration_ms,
      created_at: event.created_at,
    };
    const turn: ConversationTurn = {
      id: event.id,
      agent_id: agentId,
      timestamp: event.created_at,
      peer_id: String(event.payload?.parent_peer ?? ''),
      peer_name: '',
      agent_name: '',
      incoming: '',
      outgoing: '',
      direction: 'tools',
      tools: [tool],
    };
    addTurn(turn);
  }, [agentId, addTurn]);

  // Reset feed when agent changes
  useEffect(() => {
    setNewTurns([]);
  }, [agentId]);

  useEffect(() => {
    if (!agentId) return;

    const supabase = getSupabaseClient();
    const channelName = `agent-feed-${agentId}`;

    const existingChannel = supabase.getChannels().find(
      (ch) => ch.topic === `realtime:${channelName}`
    );
    if (existingChannel) {
      channelRef.current = existingChannel;
      setIsConnected(true);
      return () => {
        setIsConnected(false);
      };
    }

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

  // Backward compatibility: feedItems for dashboard LiveFeed
  const feedItems: import('@/types').FeedItem[] = newTurns.map((t) => {
    if (t.direction === 'incoming') {
      return {
        type: 'message' as const,
        id: t.id,
        timestamp: t.timestamp,
        peer: t.peer_id,
        role: 'user',
        content: t.incoming,
        direction: 'incoming' as const,
      };
    }
    if (t.direction === 'outgoing' || (t.outgoing && t.tools.length === 0)) {
      return {
        type: 'message' as const,
        id: t.id,
        timestamp: t.timestamp,
        peer: t.peer_id,
        role: 'assistant',
        content: t.outgoing,
        direction: 'outgoing' as const,
      };
    }
    if (t.direction === 'tools' && t.tools.length > 0) {
      const first = t.tools[0]!;
      return {
        type: 'event' as const,
        id: t.id,
        timestamp: t.timestamp,
        event_type: first.name,
        status: first.status,
        error: first.error,
      };
    }
    // Fallback: 'both' or any turn with outgoing content — surface as message
    // so live agent replies are never invisible on the dashboard.
    if (t.outgoing) {
      return {
        type: 'message' as const,
        id: t.id,
        timestamp: t.timestamp,
        peer: t.peer_id,
        role: 'assistant',
        content: t.outgoing,
        direction: 'outgoing' as const,
      };
    }
    return {
      type: 'event' as const,
      id: t.id,
      timestamp: t.timestamp,
      event_type: 'response',
      status: 'succeeded' as const,
      error: null,
    };
  });

  return {
    newTurns,
    feedItems,
    isConnected,
    clearFeed: () => setNewTurns([]),
  };
}

/**
 * Live feed merged across multiple agents over a single realtime channel.
 * Initial data must be loaded separately; the hook only provides
 * incremental updates. Each item carries agent_id of its owner.
 */
export function useMultiAgentRealtimeFeed(agentIds: string[]) {
  const qc = useQueryClient();
  const [newMessages, setNewMessages] = useState<AgentMessageRow[]>([]);
  const [newEvents, setNewEvents] = useState<AgentEventRow[]>([]);
  const [isConnected, setIsConnected] = useState(false);

  const agentKey = [...agentIds].sort().join(',');

  useEffect(() => {
    if (!agentKey) {
      setNewMessages([]);
      setNewEvents([]);
      return;
    }

    const supabase = getSupabaseClient();
    const channelName = 'agent-feed-all';
    const filter = `agent_id=in.(${agentKey})`;

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

  // Merge new messages and events into a unified sorted feed
  const feedItems: FeedItem[] = [
    ...newMessages.map((m): FeedItem => ({
      type: 'message',
      id: m.id,
      timestamp: m.created_at,
      peer: String(m.peer || m.payload?.peer || ''),
      role: m.role,
      content: m.content,
      direction: m.direction ?? undefined,
      agent_id: m.agent_id,
    })),
    ...newEvents.map((e): FeedItem => ({
      type: 'event',
      id: e.id,
      timestamp: e.created_at,
      event_type: e.event_type,
      status: e.status,
      error: e.error,
      agent_id: e.agent_id,
    })),
  ].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

  return {
    feedItems,
    newMessageCount: newMessages.length,
    newEventCount: newEvents.length,
    isConnected,
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

    const existingChannel = supabase.getChannels().find(
      (ch) => ch.topic === `realtime:${channelName}`
    );
    if (existingChannel) {
      channelRef.current = existingChannel;
      return;
    }

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
