'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { ScrollText, Wifi, WifiOff } from 'lucide-react';
import { useAgentMessages, useAgentActions } from '@/hooks/useAgentMessages';
import { useRealtimeFeed } from '@/hooks/useRealtimeFeed';
import { useMessageThreads } from '@/hooks/useTelegramSession';
import { Card, Spinner } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { TurnCard } from '@/components/activity/TurnCard';
import { buildActivityFeed, type ActivityItem, type EventLike, type MessageLike } from '@/lib/activity/normalize';
import { cn } from '@/lib/utils';

type LogFilter = 'all' | 'messages' | 'actions' | 'errors';

const FILTER_LABELS: Record<LogFilter, string> = {
  all: 'Все',
  messages: 'Сообщения',
  actions: 'Действия',
  errors: 'Ошибки',
};

function isMessageish(item: ActivityItem): boolean {
  return Boolean(item.incoming || item.trigger);
}

function hasActions(item: ActivityItem): boolean {
  return item.actions.length > 0;
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

export function TabLogs({ agentId }: { agentId: string }) {
  const searchParams = useSearchParams();
  const initialFilter = searchParams.get('filter') as LogFilter | null;
  const { data: messages, isLoading: messagesLoading } = useAgentMessages(agentId, 50);
  const { data: actions, isLoading: actionsLoading } = useAgentActions(agentId, 50);
  const { data: threads } = useMessageThreads(agentId);
  const { items: realtimeItems, isConnected } = useRealtimeFeed(agentId);

  const [filter, setFilter] = useState<LogFilter>(
    initialFilter && initialFilter in FILTER_LABELS ? initialFilter : 'all',
  );
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
    const initial = buildActivityFeed(
      (messages ?? []) as unknown as MessageLike[],
      (actions ?? []) as unknown as EventLike[],
      peerNames,
    );
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
      if (filter === 'messages' && !isMessageish(item)) return false;
      if (filter === 'actions' && !hasActions(item)) return false;
      if (filter === 'errors' && !item.failed) return false;
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
          {(Object.keys(FILTER_LABELS) as LogFilter[]).map((f) => (
            <button
              key={f}
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
            <span className={cn('font-mono text-[10px]', isConnected ? 'text-neon-500' : 'text-void-600')}>
              {isConnected ? 'LIVE' : 'OFFLINE'}
            </span>
          </div>
        </div>
      </div>

      <Card variant="glass" padding="none">
        <div className="h-[600px] overflow-y-auto">
          <div ref={topRef} />
          {messagesLoading || actionsLoading ? (
            <div className="flex items-center justify-center h-full">
              <Spinner />
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-void-600 gap-2">
              <ScrollText className="h-8 w-8 opacity-30" />
              <p>Нет записей</p>
            </div>
          ) : (
            filtered.map((item) => <TurnCard key={item.id} item={item} />)
          )}
        </div>
      </Card>

      <p className="font-mono text-xs text-void-600 text-right">
        {filtered.length} записей
      </p>
    </div>
  );
}
