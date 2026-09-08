'use client';

import { useState } from 'react';
import { useAgents, useDeleteAgent, useStartAgent, useStopAgent } from '@/hooks/useAgents';
import { useAllAgentsKPIs, useAgentsDetails } from '@/hooks/useTelegramSession';
import { useMultiAgentRealtimeFeed, useAllAgentsStatusRealtime } from '@/hooks/useRealtimeFeed';
import { useToast } from '@/components/ui/toast';
import { AgentStatusBadge } from '@/components/agents/AgentStatusBadge';
import { Card, Skeleton } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/modal';
import { cn } from '@/lib/utils';
import { sanitizeText, truncate } from '@/lib/sanitize';
import { formatDistanceToNow } from 'date-fns';
import { ru } from 'date-fns/locale';
import {
  MessageSquare, Activity, AlertTriangle, TrendingUp,
  Play, Square, RefreshCw, Wifi, WifiOff, Bot, Trash2, Plus, Settings,
} from 'lucide-react';
import Link from 'next/link';
import type { AgentRecord, FeedItem } from '@/types';

export default function DashboardPage() {
  const { data: agents, isLoading: agentsLoading } = useAgents();
  const agentIds = agents?.map((a) => a.agent_id) ?? [];

  useAllAgentsStatusRealtime();

  const agentNameById = new Map((agents ?? []).map((a) => [a.agent_id, a.name]));

  if (agentsLoading) return <DashboardSkeleton />;
  if (!agents || agents.length === 0) return <NoAgents />;

  return (
    <div className="space-y-6 animate-fade-in">
      <DashboardHeader agentsCount={agents.length} />
      <KPIRow agentIds={agentIds} />
      <AgentsGrid agents={agents} />
      <LiveFeed agentIds={agentIds} agentNameById={agentNameById} />
    </div>
  );
}

// ── Header ────────────────────────────────────────────────────────────────────
function DashboardHeader({ agentsCount }: { agentsCount: number }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div className="flex items-center gap-4">
        <div className="h-10 w-10 rounded-sm bg-plasma-950 border border-plasma-800 flex items-center justify-center">
          <Bot className="h-5 w-5 text-plasma-400" />
        </div>
        <div>
          <h1 className="font-display text-xl font-bold text-void-100">Ваши агенты</h1>
          <p className="font-mono text-xs text-void-500 mt-0.5">
            {agentsCount} {agentsCount === 1 ? 'агент' : agentsCount < 5 ? 'агента' : 'агентов'} на связи
          </p>
        </div>
      </div>

      <Link href="/onboarding">
        <Button variant="default" size="sm" leftIcon={<Plus className="h-3.5 w-3.5" />}>
          Новый агент
        </Button>
      </Link>
    </div>
  );
}

// ── KPI Cards ─────────────────────────────────────────────────────────────────
function KPIRow({ agentIds }: { agentIds: string[] }) {
  const { data: kpis, isLoading } = useAllAgentsKPIs(agentIds);

  const cards = [
    {
      label: 'Сообщений сегодня',
      value: kpis?.messages_today ?? 0,
      icon: MessageSquare,
      color: 'text-plasma-400',
      bg: 'bg-plasma-950/40',
      border: 'border-plasma-900',
    },
    {
      label: 'Активных тредов',
      value: kpis?.active_threads ?? 0,
      icon: Activity,
      color: 'text-neon-400',
      bg: 'bg-neon-950/40',
      border: 'border-neon-900',
    },
    {
      label: 'Ошибок сегодня',
      value: kpis?.errors_today ?? 0,
      icon: AlertTriangle,
      color: 'text-crimson-400',
      bg: 'bg-crimson-950/40',
      border: 'border-crimson-900',
    },
    {
      label: 'Обращений за неделю',
      value: kpis?.incoming_week ?? 0,
      icon: TrendingUp,
      color: 'text-amber-400',
      bg: 'bg-amber-950/40',
      border: 'border-amber-900',
    },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((card) => (
        <Card key={card.label} variant="glass" padding="md" className={cn('border', card.border)}>
          <div className="flex items-start justify-between">
            <div>
              {isLoading ? (
                <Skeleton className="h-8 w-16 mb-1" />
              ) : (
                <p className={cn('font-mono text-3xl font-bold tabular-nums', card.color)}>
                  {card.value.toLocaleString('ru-RU')}
                </p>
              )}
              <p className="font-mono text-xs text-void-500 mt-1 leading-tight">{card.label}</p>
            </div>
            <div className={cn('h-8 w-8 rounded-sm flex items-center justify-center', card.bg)}>
              <card.icon className={cn('h-4 w-4', card.color)} />
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

// ── Agents Grid ───────────────────────────────────────────────────────────────
function AgentsGrid({ agents }: { agents: AgentRecord[] }) {
  const { data: details } = useAgentsDetails(agents.map((a) => a.agent_id));

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {agents.map((agent) => (
        <AgentCard
          key={agent.agent_id}
          agent={agent}
          details={details?.[agent.agent_id]}
        />
      ))}
      <Link href="/onboarding" className="block h-full">
        <Card
          variant="glass"
          padding="md"
          className="h-full min-h-[160px] border-dashed border-void-700 flex flex-col items-center justify-center gap-2 text-void-500 hover:text-plasma-400 hover:border-plasma-700 transition-colors cursor-pointer"
        >
          <Plus className="h-8 w-8" />
          <span className="font-mono text-sm">Новый агент</span>
        </Card>
      </Link>
    </div>
  );
}

function AgentCard({ agent, details }: { agent: AgentRecord; details?: { phone_number: string | null; last_started_at: string | null } }) {
  const { mutate: start, isPending: starting } = useStartAgent();
  const { mutate: stop, isPending: stopping } = useStopAgent();
  const { mutate: remove, isPending: deleting } = useDeleteAgent();
  const { toast } = useToast();
  const [deleteOpen, setDeleteOpen] = useState(false);

  const canStart = agent.state === 'stopped' || agent.state === 'error';
  const canStop = agent.state === 'running';

  const handleStart = () => {
    start(agent.agent_id, {
      onSuccess: () => toast('Агент запускается...', 'success'),
      onError: (e: unknown) => toast((e as { message?: string }).message ?? 'Ошибка запуска', 'error'),
    });
  };

  const handleStop = () => {
    stop(agent.agent_id, {
      onSuccess: () => toast('Агент останавливается...', 'warning'),
      onError: (e: unknown) => toast((e as { message?: string }).message ?? 'Ошибка остановки', 'error'),
    });
  };

  const handleDelete = () => {
    remove(agent.agent_id, {
      onSuccess: () => {
        setDeleteOpen(false);
        toast(`Агент «${agent.name}» удалён`, 'success');
      },
      onError: (e: unknown) => toast((e as { message?: string }).message ?? 'Ошибка удаления', 'error'),
    });
  };

  return (
    <Card variant="glass" padding="md" className="space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-3 min-w-0">
          <div className="h-9 w-9 rounded-sm bg-void-800 border border-void-600 flex items-center justify-center shrink-0">
            <Bot className="h-4 w-4 text-plasma-400" />
          </div>
          <div className="min-w-0">
            <p className="font-display text-sm font-bold text-void-100 truncate">
              {sanitizeText(agent.name)}
            </p>
            <p className="font-mono text-xs text-void-500 truncate">
              {details?.phone_number ?? 'Telegram не подключён'}
            </p>
          </div>
        </div>
        <AgentStatusBadge state={agent.state} />
      </div>

      <p className="font-mono text-[10px] text-void-600">
        {details?.last_started_at
          ? `Запускался ${formatDistanceToNow(new Date(details.last_started_at), { addSuffix: true, locale: ru })}`
          : 'Ещё не запускался'}
      </p>

      <div className="flex items-center gap-2 pt-1">
        <Button
          variant="success" size="sm"
          onClick={handleStart}
          disabled={!canStart}
          isLoading={starting}
          leftIcon={<Play className="h-3.5 w-3.5" />}
        >
          Запустить
        </Button>
        <Button
          variant="danger" size="sm"
          onClick={handleStop}
          disabled={!canStop}
          isLoading={stopping}
          leftIcon={<Square className="h-3.5 w-3.5" />}
        >
          Стоп
        </Button>
        <div className="flex-1" />
        <Link href={`/agent/${agent.agent_id}`} aria-label="Настройки агента">
          <Button variant="ghost" size="sm" className="px-2">
            <Settings className="h-4 w-4" />
          </Button>
        </Link>
        <Button
          variant="ghost" size="sm" className="px-2 text-void-500 hover:text-crimson-400"
          onClick={() => setDeleteOpen(true)}
          aria-label="Удалить агента"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>

      <ConfirmDialog
        isOpen={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onConfirm={handleDelete}
        title="Удалить агента?"
        description={`Агент «${sanitizeText(agent.name)}» будет остановлен и удалён вместе с историей сообщений, событиями и Telegram-сессией. Это действие необратимо.`}
        confirmLabel="Удалить"
        variant="danger"
        isLoading={deleting}
      />
    </Card>
  );
}

// ── Live Feed ─────────────────────────────────────────────────────────────────
function LiveFeed({
  agentIds,
  agentNameById,
}: {
  agentIds: string[];
  agentNameById: Map<string, string>;
}) {
  const { feedItems, isConnected, clearFeed } = useMultiAgentRealtimeFeed(agentIds);

  return (
    <Card variant="glass" padding="none" className="flex flex-col h-[480px]">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-void-700">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-medium text-void-300 uppercase tracking-wider">
            Live Feed
          </span>
          <div className="flex items-center gap-1.5">
            {isConnected ? (
              <Wifi className="h-3 w-3 text-neon-400" />
            ) : (
              <WifiOff className="h-3 w-3 text-void-600" />
            )}
            <span className={cn('font-mono text-[10px]', isConnected ? 'text-neon-500' : 'text-void-600')}>
              {isConnected ? 'LIVE' : 'OFFLINE'}
            </span>
          </div>
        </div>
        <button
          onClick={clearFeed}
          className="font-mono text-xs text-void-600 hover:text-void-400 transition-colors flex items-center gap-1"
        >
          <RefreshCw className="h-3 w-3" />
          Очистить
        </button>
      </div>

      {/* Items */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {feedItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-void-600">
            <Activity className="h-8 w-8 mb-2 opacity-30" />
            <p className="font-mono text-xs">Ожидание событий...</p>
          </div>
        ) : (
          [...feedItems].reverse().map((item) => (
            <FeedItemRow key={item.id} item={item} agentNameById={agentNameById} />
          ))
        )}
      </div>
    </Card>
  );
}

function FeedItemRow({ item, agentNameById }: { item: FeedItem; agentNameById: Map<string, string> }) {
  const time = formatDistanceToNow(new Date(item.timestamp), {
    addSuffix: true,
    locale: ru,
  });
  const agentName = item.agent_id ? agentNameById.get(item.agent_id) : undefined;

  if (item.type === 'message') {
    const isIncoming = item.direction === 'incoming' || item.role === 'user';
    return (
      <div className={cn(
        'flex gap-3 px-3 py-2 rounded-sm text-xs font-mono group',
        'hover:bg-void-800/50 transition-colors',
        isIncoming ? 'border-l-2 border-plasma-700' : 'border-l-2 border-neon-800'
      )}>
        <span className={cn('shrink-0 uppercase text-[10px]', isIncoming ? 'text-plasma-500' : 'text-neon-600')}>
          {isIncoming ? '← IN' : '→ OUT'}
        </span>
        {agentName && (
          <span className="shrink-0 text-void-600">{truncate(sanitizeText(agentName), 16)}</span>
        )}
        <span className="text-void-400 shrink-0 tabular-nums">{item.peer}</span>
        <span className="text-void-300 flex-1 truncate">{sanitizeText(item.content)}</span>
        <span className="text-void-600 shrink-0">{time}</span>
      </div>
    );
  }

  const statusColors: Record<string, string> = {
    succeeded: 'text-neon-500',
    failed: 'text-crimson-500',
    running: 'text-plasma-500',
    pending: 'text-void-500',
    cancelled: 'text-void-600',
  };

  return (
    <div className="flex gap-3 px-3 py-2 rounded-sm text-xs font-mono hover:bg-void-800/50 transition-colors border-l-2 border-void-700">
      <span className="shrink-0 text-void-600 uppercase text-[10px]">EVT</span>
      {agentName && (
        <span className="shrink-0 text-void-600">{truncate(sanitizeText(agentName), 16)}</span>
      )}
      <span className={cn('shrink-0', statusColors[item.status] ?? 'text-void-400')}>
        [{item.status.toUpperCase()}]
      </span>
      <span className="text-void-400 flex-1 truncate">{item.event_type}</span>
      {item.error && <span className="text-crimson-400 truncate max-w-[120px]">{item.error}</span>}
      <span className="text-void-600 shrink-0">{time}</span>
    </div>
  );
}

// ── Skeletons & empty states ──────────────────────────────────────────────────
function DashboardSkeleton() {
  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center gap-4">
        <Skeleton className="h-10 w-10 rounded-sm" />
        <div className="space-y-2">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-32" />
        </div>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-sm" />
        ))}
      </div>
      <Skeleton className="h-[480px] rounded-sm" />
    </div>
  );
}

function NoAgents() {
  return (
    <div className="flex flex-col items-center justify-center h-[60vh] text-center space-y-4">
      <Bot className="h-16 w-16 text-void-700" />
      <h2 className="font-display text-xl font-bold text-void-300">Нет агентов</h2>
      <p className="font-mono text-sm text-void-600 max-w-xs">
        Вы ещё не создали агентов. Пройдите онбординг, чтобы создать первого.
      </p>
      <Link href="/onboarding">
        <Button>Создать агента</Button>
      </Link>
    </div>
  );
}
