'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { getSupabaseClient } from '@/lib/supabase/client';
import { queryKeys } from '@/lib/queryClient';
import type { AgentMessageRow, AgentEventRow, ConversationTurn } from '@/types';
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
    const turn: ConversationTurn = {
      id: msg.id,
      agent_id: agentId,
      timestamp: msg.created_at,
      peer_id: msg.peer || (msg as any).payload?.peer || '',
      peer_name: (msg as any).payload?.peer_name || '',
      agent_name: (msg as any).payload?.agent_name || '',
      incoming: msg.direction === 'incoming' ? msg.content : '',
      outgoing: msg.direction === 'agent_response' ? msg.content : '',
      direction: msg.direction === 'incoming' ? 'incoming' : 'outgoing',
    };
    addTurn(turn);
  }, [agentId, addTurn]);

  const addEvent = useCallback((event: AgentEventRow) => {
    // Tool calls shown as turns with tools (Phase 4 - tool cards)
    const turn: ConversationTurn = {
      id: event.id,
      agent_id: agentId,
      timestamp: event.created_at,
      peer_id: '',
      peer_name: '',
      agent_name: '',
      incoming: '',
      outgoing: `[${event.event_type}] ${event.status}`,
      direction: 'outgoing',
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
        (payload: any) => {
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
        (payload: any) => {
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
    // Outgoing or tool call
    return {
      type: 'event' as const,
      id: t.id,
      timestamp: t.timestamp,
      event_type: t.outgoing?.startsWith('[') ? (t.outgoing.match(/^\[(.+?)\]/)?.[1] || 'tool') : 'response',
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
