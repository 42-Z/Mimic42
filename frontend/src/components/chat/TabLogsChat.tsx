'use client';

import React, { useState, useCallback } from 'react';
import { useConversation } from '@/hooks/useConversation';
import { ConversationThread } from '@/components/chat/ConversationThread';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

const FILTERS = [
  { id: 'all', label: 'Все' },
  { id: 'dialog', label: 'Диалог' },
] as const;

export function TabLogsChat({ agentId }: { agentId: string }) {
  const { data, isLoading, fetchNextPage, hasNextPage } = useConversation(agentId);
  const [filter, setFilter] = useState<'all' | 'dialog'>('all');
  const [search, setSearch] = useState('');

  const allTurns = data?.pages.flat() ?? [];

  const filtered = allTurns.filter((turn) => {
    if (filter === 'dialog') {
      return turn.direction === 'both' || turn.direction === 'incoming' || turn.direction === 'outgoing';
    }
    return true;
  }).filter((turn) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      turn.incoming.toLowerCase().includes(q) ||
      turn.outgoing.toLowerCase().includes(q)
    );
  });

  const handleLoadMore = useCallback(() => {
    if (hasNextPage) fetchNextPage();
  }, [hasNextPage, fetchNextPage]);

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row gap-3">
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
      </div>

      <div className="h-[60vh] min-h-[400px] max-h-[600px] overflow-y-auto bg-void-950 border border-void-800 rounded-sm">
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
