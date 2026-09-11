'use client';

import React, { useState, useCallback, useEffect, useRef } from 'react';
import { useConversation } from '@/hooks/useConversation';
import { useRealtimeFeed } from '@/hooks/useRealtimeFeed';
import { ConversationThread } from '@/components/chat/ConversationThread';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { getToolLabel, toolArgs } from '@/lib/toolLabels';

const FILTERS = [
  { id: 'all', label: 'Все' },
  { id: 'dialog', label: 'Диалог' },
  { id: 'tools', label: 'Тулзы' },
] as const;

export function TabLogsChat({ agentId }: { agentId: string }) {
  const { data, isLoading, fetchNextPage, hasNextPage } = useConversation(agentId);
  const { newTurns, isConnected, clearFeed } = useRealtimeFeed(agentId);
  const [filter, setFilter] = useState<'all' | 'dialog' | 'tools'>('all');
  const [search, setSearch] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);
  const initialScrollDone = useRef(false);

  const allTurns = React.useMemo(() => data?.pages.flat() ?? [], [data?.pages]);

  // Merge historical + realtime, deduplicate by id
  const mergedTurns = React.useMemo(() => {
    const seen = new Set<string>();
    const combined = [...allTurns, ...newTurns].sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    );
    return combined.filter((turn) => {
      if (seen.has(turn.id)) return false;
      seen.add(turn.id);
      return true;
    });
  }, [allTurns, newTurns]);

  const filtered = mergedTurns.filter((turn) => {
    if (filter === 'dialog') {
      return turn.direction === 'both' || turn.direction === 'incoming' || turn.direction === 'outgoing';
    }
    if (filter === 'tools') {
      return turn.tools.length > 0 || turn.direction === 'tools';
    }
    return true;
  }).filter((turn) => {
    if (!search) return true;
    const q = search.toLowerCase();
    const inMessages =
      turn.incoming.toLowerCase().includes(q) ||
      turn.outgoing.toLowerCase().includes(q);
    const inTools = turn.tools.some((tool) => {
      const label = getToolLabel(tool.name, toolArgs(tool.payload?.args));
      return label.toLowerCase().includes(q);
    });
    return inMessages || inTools;
  });

  const handleLoadMore = useCallback(() => {
    if (!hasNextPage || !containerRef.current) return;
    const el = containerRef.current;
    const prevScrollHeight = el.scrollHeight;
    fetchNextPage().then(() => {
      // Preserve scroll position after prepending older turns
      requestAnimationFrame(() => {
        el.scrollTop += el.scrollHeight - prevScrollHeight;
      });
    });
  }, [hasNextPage, fetchNextPage]);

  // Auto-scroll to bottom on new turns
  useEffect(() => {
    if (containerRef.current && newTurns.length > 0) {
      const el = containerRef.current;
      // Only scroll if user is near bottom (within 100px)
      const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
      if (isNearBottom) {
        el.scrollTop = el.scrollHeight;
      }
    }
  }, [newTurns.length]);

  // Initial scroll to newest (bottom) once historical turns first load —
  // otherwise the user lands on the oldest turn.
  useEffect(() => {
    if (!initialScrollDone.current && containerRef.current && allTurns.length > 0) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
      initialScrollDone.current = true;
    }
  }, [allTurns.length]);

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
        <Input
          placeholder="Поиск по сообщениям..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="sm:max-w-xs"
        />
        <div className="flex items-center gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              className={cn(
                'px-3 py-1.5 rounded-sm font-mono text-xs border transition-colors',
                filter === f.id
                  ? 'bg-plasma-950 border-plasma-800 text-plasma-400'
                  : 'border-void-700 text-void-500 hover:text-void-300 hover:border-void-600',
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 ml-auto">
          <div className={cn('h-2 w-2 rounded-full', isConnected ? 'bg-neon-400' : 'bg-crimson-400')} />
          <span className={cn('text-[10px] font-mono', isConnected ? 'text-neon-500' : 'text-crimson-500')}>
            {isConnected ? 'LIVE' : 'OFF'}
          </span>
          {newTurns.length > 0 && (
            <button
              onClick={clearFeed}
              className="text-[10px] text-void-600 hover:text-void-400 transition-colors"
            >
              Очистить
            </button>
          )}
        </div>
      </div>

      <div
        ref={containerRef}
        className="h-[60vh] min-h-[400px] max-h-[600px] overflow-y-auto bg-void-950 border border-void-800 rounded-sm"
      >
        <ConversationThread
          turns={filtered}
          isLoading={isLoading}
          hasMore={!!hasNextPage}
          onLoadMore={handleLoadMore}
        />
      </div>
    </div>
  );
}
