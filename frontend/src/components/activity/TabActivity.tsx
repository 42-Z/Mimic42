'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Activity, ArrowDown, Wifi, WifiOff } from 'lucide-react';
import { useActivityFeed } from '@/hooks/useActivityFeed';
import { useRealtimeFeed } from '@/hooks/useRealtimeFeed';
import { useMessageThreads } from '@/hooks/useTelegramSession';
import { Card, Spinner } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { TurnCard } from './TurnCard';
import { LifecycleStack } from './LifecycleStack';
import { groupAgentToggles, type ActivityGroup } from '@/lib/activity/group';
import { isStackOpen, setStackOpen, type ExpandedStackIds } from '@/lib/activity/expand';
import { turnToActivityItem, type ActivityItem } from '@/lib/activity/normalize';
import { cn } from '@/lib/utils';

type FeedFilter = 'full' | 'chat' | 'errors';

const FILTER_LABELS: Record<FeedFilter, string> = {
  full: 'Полный',
  chat: 'Только чат',
  errors: 'Ошибки',
};

function isFeedFilter(value: string | null): value is FeedFilter {
  return value !== null && Object.hasOwn(FILTER_LABELS, value);
}

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

export function TabActivity({ agentId, agentName }: { agentId: string; agentName?: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useActivityFeed(agentId);
  const { items: realtimeItems, isConnected } = useRealtimeFeed(agentId);
  const { data: threads } = useMessageThreads(agentId);

  const [filter, setFilter] = useState<FeedFilter>(() => {
    const initial = searchParams.get('filter');
    return isFeedFilter(initial) ? initial : 'full';
  });

  // Keep the filter in the URL so a reload or a shared link restores it.
  const applyFilter = (next: FeedFilter) => {
    setFilter(next);
    const params = new URLSearchParams(searchParams.toString());
    if (next === 'full') params.delete('filter');
    else params.set('filter', next);
    router.replace(`/agent/${agentId}?${params.toString()}`, { scroll: false });
  };
  const [search, setSearch] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const topRef = useRef<HTMLDivElement>(null);
  const prevTopId = useRef<string | null>(null);

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
        // The short thread title beats the long "Name (@user, ID: ...)" string.
        item.peerTitle = peerNames.get(item.peer) ?? item.peerTitle ?? null;
        return item;
      }),
    );
    const seen = new Set(historical.map((i) => i.id));
    const realtime = realtimeItems
      .filter((i) => !seen.has(i.id))
      .map((i) => ({ ...i, peerTitle: peerNames.get(i.peer) ?? i.peerTitle ?? null }));
    const merged = [...realtime, ...historical];
    merged.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
    return merged;
  }, [data?.pages, realtimeItems, peerNames]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter((item) => {
      if (filter === 'chat' && !isDialog(item)) return false;
      if (filter === 'errors' && !item.failed) return false;
      if (q && !matchesSearch(item, q)) return false;
      return true;
    });
  }, [items, filter, search]);

  const grouped = useMemo(() => {
    const visible = new Set(filtered.map((item) => item.id));
    return groupAgentToggles(items)
      .map((group) => group.filter((item) => visible.has(item.id)))
      .filter((group): group is ActivityGroup => group.length > 0);
  }, [items, filtered]);

  // Раскрытие стека живёт по id событий, а не по DOM-позиции: «Загрузить ещё»
  // дописывает старые события к той же последовательности, realtime — новые
  // сверху, и пересборка групп не должна схлопывать уже раскрытый стек.
  const [expandedStackIds, setExpandedStackIds] = useState<ExpandedStackIds>(new Set());

  const topId = filtered[0]?.id ?? null;

  useEffect(() => {
    // The list is newest-first: follow the top only when a *new* top item
    // appears. Loading older pages (or a running fetchNextPage) must not
    // yank the reader back to the top.
    if (!autoScroll || isFetchingNextPage) {
      prevTopId.current = topId;
      return;
    }
    if (topId !== null && topId !== prevTopId.current) {
      topRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
    prevTopId.current = topId;
  }, [topId, autoScroll, isFetchingNextPage]);

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row gap-3">
        <Input
          placeholder="Поиск по содержимому..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="sm:max-w-xs"
        />
        <div className="flex items-center gap-1" role="group" aria-label="Фильтр записей">
          {(Object.keys(FILTER_LABELS) as FeedFilter[]).map((f) => (
            <Button
              key={f}
              type="button"
              size="xs"
              variant="outline"
              data-testid={`log-filter-${f}`}
              aria-pressed={filter === f}
              onClick={() => applyFilter(f)}
              className={cn(
                filter === f
                  ? 'border-primary/60 bg-primary/10 text-primary hover:border-primary hover:text-primary'
                  : 'border-border text-muted-foreground hover:border-border hover:text-foreground',
              )}
            >
              {FILTER_LABELS[f]}
            </Button>
          ))}
        </div>
        <div className="flex items-center gap-2 ml-auto">
          <Button
            type="button"
            size="xs"
            variant="outline"
            aria-pressed={autoScroll}
            onClick={() => setAutoScroll((v) => !v)}
            leftIcon={<ArrowDown className="h-3 w-3" aria-hidden="true" />}
            className={cn(
              autoScroll
                ? 'border-success/50 text-success hover:border-success/60 hover:text-success'
                : 'border-border text-muted-foreground hover:border-border hover:text-foreground',
            )}
          >
            Авто-скролл
          </Button>
          <div className="flex items-center gap-1.5">
            {isConnected ? (
              <Wifi className="h-3.5 w-3.5 text-neon-400" aria-hidden="true" />
            ) : (
              <WifiOff className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
            )}
            <span
              className={cn(
                'font-mono text-[10px] tracking-wider',
                isConnected ? 'text-neon-500' : 'text-muted-foreground',
              )}
            >
              {isConnected ? 'ОНЛАЙН' : 'ОФЛАЙН'}
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
          ) : (
            <>
              {filtered.length === 0 ? (
                <div
                  className={cn(
                    'flex flex-col items-center justify-center gap-2 text-muted-foreground',
                    hasNextPage ? 'py-16' : 'h-full',
                  )}
                >
                  <Activity className="h-8 w-8 opacity-30" aria-hidden="true" />
                  <p className="font-mono text-sm">
                    {hasNextPage ? 'На этой странице совпадений нет' : 'Нет записей'}
                  </p>
                </div>
              ) : (
                grouped.map((group) => group.length > 1 ? (
                  <LifecycleStack
                    key={group[0].id}
                    items={group}
                    isOpen={isStackOpen(group.map((item) => item.id), expandedStackIds)}
                    onToggle={(open) =>
                      setExpandedStackIds((prev) =>
                        setStackOpen(prev, group.map((item) => item.id), open),
                      )
                    }
                  />
                ) : (
                  <TurnCard
                    key={group[0].id}
                    item={group[0]}
                    chatOnly={filter === 'chat'}
                    agentName={agentName}
                  />
                ))
              )}
              <div className="py-3 text-center">
                {isFetchingNextPage ? (
                  <Spinner className="inline-block" />
                ) : hasNextPage ? (
                  <Button type="button" variant="ghost" size="xs" onClick={() => fetchNextPage()}>
                    Загрузить ещё
                  </Button>
                ) : null}
              </div>
            </>
          )}
        </div>
      </Card>

      <p className="text-right font-mono text-xs tabular-nums text-muted-foreground">
        {filtered.length} записей
      </p>
    </div>
  );
}
