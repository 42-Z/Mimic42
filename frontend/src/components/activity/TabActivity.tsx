'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Wifi, WifiOff } from 'lucide-react';
import { useActivityFeed } from '@/hooks/useActivityFeed';
import { useRealtimeFeed } from '@/hooks/useRealtimeFeed';
import { useMessageThreads } from '@/hooks/useTelegramSession';
import { Card, Spinner } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { TurnCard } from './TurnCard';
import { turnToActivityItem, type ActivityItem } from '@/lib/activity/normalize';
import { cn } from '@/lib/utils';

type FeedFilter = 'full' | 'chat';

const FILTER_LABELS: Record<FeedFilter, string> = { full: 'Полный', chat: 'Только чат' };

function isDialog(item: ActivityItem): boolean {
  return Boolean(item.incoming || item.trigger || item.response);
}

function matchesSearch(item: ActivityItem, q: string): boolean {
  if (item.peerTitle?.toLowerCase().includes(q)) return true;
  if (item.incoming?.content.toLowerCase().includes(q)) return true;
  if (item.response?.content.toLowerCase().includes(q)) return true;
  if (item.trigger?.content.toLowerCase().includes(q)) return true;
  return item.actions.some(
    (a) => a.label.toLowerCase().includes(q) || a.hint?.toLowerCase().includes(q),
  );
}

export function TabActivity({ agentId }: { agentId: string }) {
  const { data, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useActivityFeed(agentId);
  const { items: realtimeItems, isConnected } = useRealtimeFeed(agentId);
  const { data: threads } = useMessageThreads(agentId);

  const [filter, setFilter] = useState<FeedFilter>('full');
  const [search, setSearch] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const topRef = useRef<HTMLDivElement>(null);

  const peerNames = useMemo(
    () =>
      new Map(
        (threads ?? [])
          .filter((t) => t.title)
          .map((t) => [t.telegram_peer_id, t.title as string]),
      ),
    [threads],
  );

  const items = useMemo(() => {
    const historical = (data?.pages ?? []).flatMap((page) =>
      page.turns.map((turn) => {
        const item = turnToActivityItem(turn);
        item.peerTitle = item.peerTitle ?? peerNames.get(item.peer) ?? null;
        return item;
      }),
    );
    const seen = new Set(historical.map((i) => i.id));
    const realtime = realtimeItems.filter((i) => !seen.has(i.id));
    const merged = [...realtime, ...historical];
    merged.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
    return merged;
  }, [data?.pages, realtimeItems, peerNames]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter((item) => {
      if (filter === 'chat' && !isDialog(item)) return false;
      if (q && !matchesSearch(item, q)) return false;
      return true;
    });
  }, [items, filter, search]);

  useEffect(() => {
    // The list is newest-first, so "follow the latest" means the top.
    if (autoScroll) topRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [filtered.length, autoScroll]);

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row gap-3">
        <Input
          placeholder="Поиск по содержимому..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="sm:max-w-xs"
        />
        <div className="flex items-center gap-1">
          {(Object.keys(FILTER_LABELS) as FeedFilter[]).map((f) => (
            <button
              key={f}
              data-testid={`log-filter-${f}`}
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
            className={cn(
              'font-mono text-xs px-3 py-1.5 rounded-sm border transition-colors',
              autoScroll ? 'border-neon-800 text-neon-500' : 'border-void-700 text-void-600',
            )}
          >
            {autoScroll ? '⬇ Авто-скролл' : '— Авто-скролл'}
          </button>
          <div className="flex items-center gap-1.5">
            {isConnected ? (
              <Wifi className="h-3.5 w-3.5 text-neon-400" />
            ) : (
              <WifiOff className="h-3.5 w-3.5 text-void-600" />
            )}
            <span
              className={cn(
                'font-mono text-[10px]',
                isConnected ? 'text-neon-500' : 'text-void-600',
              )}
            >
              {isConnected ? 'LIVE' : 'OFFLINE'}
            </span>
          </div>
        </div>
      </div>

      <Card variant="glass" padding="none">
        <div className="h-[640px] overflow-y-auto" data-testid="activity-feed">
          <div ref={topRef} />
          {isLoading ? (
            <div className="flex items-center justify-center h-full">
              <Spinner />
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-void-600 gap-2">
              <Activity className="h-8 w-8 opacity-30" />
              <p>Нет записей</p>
            </div>
          ) : (
            <>
              {filtered.map((item) => (
                <TurnCard key={item.id} item={item} chatOnly={filter === 'chat'} />
              ))}
              <div className="py-3 text-center">
                {isFetchingNextPage ? (
                  <Spinner className="inline-block" />
                ) : hasNextPage ? (
                  <button
                    onClick={() => fetchNextPage()}
                    className="font-mono text-xs text-void-500 hover:text-void-300 transition-colors"
                  >
                    Загрузить ещё
                  </button>
                ) : null}
              </div>
            </>
          )}
        </div>
      </Card>

      <p className="font-mono text-xs text-void-600 text-right">{filtered.length} записей</p>
    </div>
  );
}
