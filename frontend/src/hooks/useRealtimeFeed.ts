'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { getSupabaseClient } from '@/lib/supabase/client';
import { queryKeys } from '@/lib/queryClient';
import type { AgentMessageRow, AgentEventRow, FeedItem, RealtimePayload } from '@/types';
import type { RealtimeChannel } from '@supabase/supabase-js';

const MAX_FEED_ITEMS = {}

/**
 * Manages Supabase Realtime subscriptions for an agent's messages and events.
 * Returns a live-updating feed of items sorted by timestamp.
 *
 * Initial data must be loaded separately (via useAgentMessages / useAgentActions).
 * This hook only provides incremental updates.
 */
export function useRealtimeFeed(agentId: string) {
  const qc = useQueryClient();
  const channelRef = useRef<RealtimeChannel | null>(null);
  const [newMessages, setNewMessages] = useState<AgentMessageRow[]>([]);
  const [newEvents, setNewEvents] = useState<AgentEventRow[]>([]);
  const [isConnected, setIsConnected] = useState(false);

  const addMessage = useCallback((msg: AgentMessageRow) => {
    setNewMessages((prev) => {
      const updated = [...prev, msg];
      if (updated.length > MAX_FEED_ITEMS) {
        return updated.slice(updated.length - MAX_FEED_ITEMS);
      }
      return updated;
    });
    // Also invalidate the messages query so pagination stays in sync
    qc.invalidateQueries({ queryKey: queryKeys.messages.byAgent(agentId) });
  }, [agentId, qc]);

  const addEvent = useCallback((event: AgentEventRow) => {
    setNewEvents((prev) => {
      const updated = [...prev, event];
      if (updated.length > MAX_FEED_ITEMS) {
        return updated.slice(updated.length - MAX_FEED_ITEMS);
      }
      return updated;
    });
    qc.invalidateQueries({ queryKey: queryKeys.actions.byAgent(agentId) });
  }, [agentId, qc]);

  useEffect(() => {
    if (!agentId) return;

    const supabase = getSupabaseClient();
    const channelName = `agent-feed-${agentId}`;

    // Prevent duplicate subscriptions
    const existingChannel = supabase.getChannels().find(
      (ch) => ch.topic === `realtime:${channelName}`
    );
    if (existingChannel) {
      channelRef.current = existingChannel;
      return;
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

  // Merge new messages and events into a unified sorted feed
  const feedItems: FeedItem[] = [
    ...newMessages.map((m): FeedItem => ({
      type: 'message',
      id: m.id,
      timestamp: m.created_at,
      peer: m.peer || (m as any).payload?.peer || '',
      role: m.role,
      content: m.content,
      direction: m.direction ?? undefined as string,
    })),
    ...newEvents.map((e): FeedItem => ({
      type: 'event',
      id: e.id,
      timestamp: e.created_at,
      event_type: e.event_type,
      status: e.status,
      error: e.error,
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
