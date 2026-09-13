'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { ScrollText, Wifi, WifiOff } from 'lucide-react';
import { useAgentMessages, useAgentActions } from '@/hooks/useAgentMessages';
import { useRealtimeFeed } from '@/hooks/useRealtimeFeed';
import { useMessageThreads } from '@/hooks/useTelegramSession';
import { Card, Spinner } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { UnifiedItem } from './UnifiedItem';
import {
  buildActivityFeed,
  type ActivityItem,
  type EventLike,
  type MessageLike,
} from '@/lib/activity/normalize';
import { cn } from '@/lib/utils';

type ActivityFilter = 'full' | 'chat';

const FILTER_LABELS: Record<ActivityFilter, string> = {
  full: 'Полный',
  chat: 'Только чат',
};

// P2 #5: Pre-compute toLowerCase to avoid redundant calls per keystroke.
function matchesSearch(item: ActivityItem, q: string): boolean {
  const ql = q.toLowerCase();
  if (item.peerTitle?.toLowerCase().includes(ql)) return true;
  if (item.incoming?.content.toLowerCase().includes(ql)) return true;
  if (item.response?.content.toLowerCase().includes(ql)) return true;
  if (item.trigger?.content.toLowerCase().includes(ql)) return true;
  return item.actions.some(
    (a) => a.label.toLowerCase().includes(ql) || a.hint?.toLowerCase().includes(ql),
  );
}

/**
 * Build a stable peerNames Map that only changes when the underlying
 * thread data actually differs (deep-equality by peer_id→title pairs).
 */
function useStablePeerNames(threads: ReturnType<typeof useMessageThreads>['data']) {
  const ref = useRef<Map<string, string>>(new Map());

  const peerNames = useMemo(() => {
    const next = new Map(
      (threads ?? [])
        .filter((t) => t.title)
        .map((t) => [t.telegram_peer_id, t.title as string]),
    );
    // Deep-compare: if contents are identical, keep the old reference
    if (ref.current.size === next.size) {
      let identical = true;
      for (const [k, v] of next) {
        if (ref.current.get(k) !== v) { identical = false; break; }
      }
      if (identical) return ref.current;
    }
    ref.current = next;
    return next;
  }, [threads]);

  return peerNames;
}

export function UnifiedActivity({ agentId }: { agentId: string }) {
  const { data: messages, isLoading: messagesLoading } = useAgentMessages(agentId, 200);
  const { data: actions, isLoading: actionsLoading } = useAgentActions(agentId, 200);
  const { data: threads } = useMessageThreads(agentId);
  const { items: realtimeItems, isConnected } = useRealtimeFeed(agentId);

  const [filter, setFilter] = useState<ActivityFilter>('full');
  const [search, setSearch] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const topRef = useRef<HTMLDivElement>(null);
  const prevItemCountRef = useRef(0);

  const peerNames = useStablePeerNames(threads);

  const items = useMemo(() => {
    const initial = buildActivityFeed(
      (messages ?? []) as unknown as MessageLike[],
      (actions ?? []) as unknown as EventLike[],
      peerNames,
    );
    // P2 #4: Apply peerNames to realtime items here — buildActivityFeed
    // already resolved peerNames for initial items, so no double lookup.
    const realtime = realtimeItems.map((item) => ({
      ...item,
      peerTitle: item.peerTitle ?? peerNames.get(item.peer) ?? null,
    }));
    const seen = new Set(initial.map((i) => i.id));
    const merged = [...realtime.filter((i) => !seen.has(i.id)), ...initial];
    merged.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
    return merged;
  }, [messages, actions, realtimeItems, peerNames]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter((item) => {
      // Chat-only filter: skip lifecycle events and tool-only turns
      if (filter === 'chat') {
        if (item.kind === 'lifecycle') return false;
        const hasMessage = Boolean(item.incoming || item.trigger || item.response);
        if (!hasMessage) return false;
      }
      if (q && !matchesSearch(item, q)) return false;
      return true;
    });
  }, [items, filter, search]);

  // P1 #1: Auto-scroll only on new data arrival (items.length increases),
  // not on filter/search changes.
  useEffect(() => {
    if (autoScroll && items.length > prevItemCountRef.current) {
      topRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
    prevItemCountRef.current = items.length;
  }, [items.length, autoScroll]);

  const isLoading = messagesLoading || actionsLoading;

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-3">
        <Input
          placeholder="Поиск по содержимому..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="sm:max-w-xs"
        />
        <div className="flex items-center gap-1">
          {(Object.keys(FILTER_LABELS) as ActivityFilter[]).map((f) => (
            <button
              key={f}
              data-testid={`activity-filter-${f}`}
              onClick={() => setFilter(f)}
              className={cn(
                'px-3 py-1.5 rounded-sm font-mono text-xs border transition-colors',
                filter === f
                  ? 'bg-plasma-950 border-plasma-800 text-plasma-400'
                  : 'border-void-700 text-void-500 hover:text-void-300 hover:border-void-600',
              )}
            >
              {FILTER_LABELS[f]}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 ml-auto">
          <button
            onClick={() => setAutoScroll((v) => !v)}
            title={autoScroll ? 'Автоматически прокручивать к новым записям' : 'Авто-скролл отключён'}
            className={cn(
              'font-mono text-xs px-3 py-1.5 rounded-sm border transition-colors',
              autoScroll ? 'border-neon-800 text-neon-500' : 'border-void-700 text-void-600',
            )}
          >
            {autoScroll ? '↓ Авто-скролл' : '— Авто-скролл'}
          </button>
          <div className="flex items-center gap-1.5">
            {isConnected ? (
              <Wifi className="h-3.5 w-3.5 text-neon-400" />
            ) : (
              <WifiOff className="h-3.5 w-3.5 text-void-600" />
            )}
            <span className={cn('font-mono text-[10px]', isConnected ? 'text-neon-500' : 'text-void-600')}>
              {isConnected ? 'LIVE' : 'OFFLINE'}
            </span>
          </div>
        </div>
      </div>

      {/* Feed */}
      <Card variant="glass" padding="none">
        <div className="h-[600px] overflow-y-auto">
          <div ref={topRef} />
          {isLoading ? (
            <div className="flex items-center justify-center h-full">
              <Spinner />
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-void-600 gap-2">
              <ScrollText className="h-8 w-8 opacity-30" />
              <p className="font-mono text-sm">Нет записей</p>
            </div>
          ) : (
            filtered.map((item) => (
              <UnifiedItem
                key={item.id}
                item={item}
                showTools={filter === 'full'}
              />
            ))
          )}
        </div>
      </Card>

      <p className="font-mono text-xs text-void-600 text-right">
        {filtered.length} записей
      </p>
    </div>
  );
}
