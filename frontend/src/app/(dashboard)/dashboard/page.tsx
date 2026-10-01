'use client';

import { useAgents, useStartAgent, useStopAgent } from '@/hooks/useAgents';
import { useAllAgentsKPIs, useAgentsDetails, type AgentDetails } from '@/hooks/useTelegramSession';
import { useMultiAgentRealtimeFeed, useAllAgentsStatusRealtime } from '@/hooks/useRealtimeFeed';
import { useToast } from '@/components/ui/toast';
import { AgentStatusBadge } from '@/components/agents/AgentStatusBadge';
import { AgentToggleButton } from '@/components/agents/AgentToggleButton';
import { AgentIdentity } from '@/components/agents/AgentIdentity';
import { Card, Skeleton } from '@/components/ui/card';
import { Button, buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { maskPhoneNumber, sanitizeText, truncate } from '@/lib/sanitize';
import { needsRebind } from '@/lib/telegram';
import { getSupabaseClient } from '@/lib/supabase/client';
import { formatDistanceToNow } from 'date-fns';
import { ru } from 'date-fns/locale';
import {
  MessageSquare, Activity, AlertTriangle, Users,
  RefreshCw, Wifi, WifiOff, Bot, Plus, Settings,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { AgentRecord } from '@/types';
import { incomingBody, type ActivityItem } from '@/lib/activity/normalize';

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
        <div className="h-10 w-10 rounded-sm bg-primary/10 border border-primary/20 flex items-center justify-center" aria-hidden="true">
          <Bot className="h-5 w-5 text-primary" />
        </div>
        <div>
          <h1 className="font-display text-2xl font-bold text-foreground">Ваши агенты</h1>
          <p className="font-mono text-xs text-muted-foreground mt-1">
            {agentsCount} {agentsCount === 1 ? 'агент' : agentsCount < 5 ? 'агента' : 'агентов'} на связи
          </p>
        </div>
      </div>

      <Link href="/onboarding" className={buttonVariants({ variant: 'default', size: 'sm' })}>
        <Plus className="h-3.5 w-3.5" />
        Новый агент
      </Link>
    </div>
  );
}

// ── KPI Cards ─────────────────────────────────────────────────────────────────
function KPIRow({ agentIds }: { agentIds: string[] }) {
  const { data: kpis, isLoading } = useAllAgentsKPIs(agentIds);
  const router = useRouter();
  const { toast } = useToast();

  const openLatestError = async () => {
    if (!kpis || kpis.errors_today === 0 || agentIds.length === 0) return;
    const supabase = getSupabaseClient();
    const { data } = await supabase
      .from('agent_events')
      .select('agent_id')
      .in('agent_id', agentIds)
      .eq('status', 'failed')
      .order('created_at', { ascending: false })
      .limit(1)
      .maybeSingle();
    if (data?.agent_id) {
      router.push(`/agent/${data.agent_id}?tab=logs&filter=errors`);
    } else {
      toast('Не удалось найти ошибки', 'warning');
    }
  };

  const cards = [
    {
      label: 'Собеседников сегодня',
      value: kpis?.contacts_today ?? 0,
      icon: Users,
      color: 'text-warning',
      bg: 'bg-warning/10',
      border: 'border-warning/20',
    },
    {
      label: 'Сообщений сегодня',
      value: kpis?.messages_today ?? 0,
      icon: MessageSquare,
      color: 'text-primary',
      bg: 'bg-primary/10',
      border: 'border-primary/20',
    },
    {
      label: 'Действий сегодня',
      value: kpis?.actions_today ?? 0,
      icon: Activity,
      color: 'text-success',
      bg: 'bg-success/10',
      border: 'border-success/20',
    },
    {
      label: 'Ошибок сегодня',
      value: kpis?.errors_today ?? 0,
      icon: AlertTriangle,
      color: 'text-destructive',
      bg: 'bg-destructive/10',
      border: 'border-destructive/20',
      clickable: true,
    },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((card) => (
        <Card
          key={card.label}
          data-testid="kpi-card"
          variant="glass"
          padding="md"
          onClick={card.clickable ? openLatestError : undefined}
          className={cn(
            'border',
            card.border,
            card.clickable && kpis && kpis.errors_today > 0 &&
              'cursor-pointer hover:border-destructive/40 transition-colors',
          )}
        >
          <div className="flex items-start justify-between">
            <div>
              {isLoading ? (
                <Skeleton className="h-8 w-16 mb-1" />
              ) : (
                <p className={cn('font-mono text-3xl font-bold tabular-nums', card.color)}>
                  {card.value.toLocaleString('ru-RU')}
                </p>
              )}
              <p className="font-mono text-xs text-muted-foreground mt-1 leading-tight">{card.label}</p>
            </div>
            <div className={cn('h-8 w-8 rounded-sm flex items-center justify-center', card.bg)} aria-hidden="true">
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
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {agents.map((agent) => (
        <AgentCard
          key={agent.agent_id}
          agent={agent}
          details={details?.[agent.agent_id]}
        />
      ))}
      <Link
        href="/onboarding"
        className="block h-full rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <Card
          variant="glass"
          padding="md"
          className="h-full min-h-[160px] border-dashed border-border flex flex-col items-center justify-center gap-2 text-muted-foreground hover:text-primary hover:bg-primary/5 hover:border-primary/40 transition-colors cursor-pointer"
        >
          <Plus className="h-8 w-8" aria-hidden="true" />
          <span className="font-mono text-sm">Новый агент</span>
        </Card>
      </Link>
    </div>
  );
}

function AgentCard({ agent, details }: { agent: AgentRecord; details?: AgentDetails }) {
  const { mutate: start, isPending: starting } = useStartAgent();
  const { mutate: stop, isPending: stopping } = useStopAgent();
  const { toast } = useToast();

  const rebind = needsRebind(details?.authorization_status);

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

  return (
    <Card
      variant="glass"
      padding="md"
      className="space-y-3 transition-colors hover:border-primary/25"
      data-testid={`agent-card-${agent.agent_id}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-3 min-w-0">
          <div className="h-9 w-9 rounded-sm bg-muted border border-border flex items-center justify-center shrink-0" aria-hidden="true">
            <Bot className="h-4 w-4 text-primary" />
          </div>
          <AgentIdentity
            className="min-w-0"
            name={agent.name}
            username={details?.username}
            subtitle={details?.phone_number ? maskPhoneNumber(details.phone_number) : 'Telegram не подключён'}
          />
        </div>
        <AgentStatusBadge state={agent.state} />
      </div>

      <p className="font-mono text-xs text-muted-foreground">
        {details?.last_started_at
          ? `Запускался ${formatDistanceToNow(new Date(details.last_started_at), { addSuffix: true, locale: ru })}`
          : 'Ещё не запускался'}
      </p>

      <div className="flex items-center gap-2 pt-1">
        <AgentToggleButton
          agentId={agent.agent_id}
          state={agent.state}
          needsRebind={rebind}
          isStarting={starting}
          isStopping={stopping}
          onStart={handleStart}
          onStop={handleStop}
        />
        <div className="flex-1" />
        <Link
          href={`/agent/${agent.agent_id}`}
          aria-label="Настройки агента"
          title="Настройки агента"
          className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }), 'px-2')}
        >
          <Settings className="h-4 w-4" />
        </Link>
      </div>
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
  const { items, peerNames, isConnected, refetchSeed, clearFeed } =
    useMultiAgentRealtimeFeed(agentIds);

  const namedItems = items.map((item) => ({
    ...item,
    peerTitle: item.peerTitle ?? peerNames.get(item.peer) ?? null,
  }));

  // Newest turns first; within a turn keep the logical order:
  // incoming -> actions -> response.
  const rows: FeedLine[] = [...namedItems]
    .reverse()
    .flatMap((item) => toFeedLines(item));

  return (
    <Card variant="glass" padding="none" className="flex flex-col h-[480px]">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-border">
        <div className="flex items-center gap-2">
          <h2 className="font-mono text-xs font-medium text-muted-foreground uppercase tracking-wider">
            Живая лента
          </h2>
          <div className="flex items-center gap-1.5">
            {isConnected ? (
              <Wifi className="h-3 w-3 text-success" aria-hidden="true" />
            ) : (
              <WifiOff className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
            )}
            <span className={cn('font-mono text-[10px]', isConnected ? 'text-success' : 'text-muted-foreground')}>
              {isConnected ? 'ОНЛАЙН' : 'ОФЛАЙН'}
            </span>
          </div>
        </div>
        <Button
          variant="ghost"
          size="xs"
          onClick={() => {
            refetchSeed();
            clearFeed();
          }}
          leftIcon={<RefreshCw className="h-3 w-3" />}
        >
          Обновить
        </Button>
      </div>

      {/* Items — newest turns first, within a turn: incoming, actions, response */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {rows.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
            <Activity className="h-8 w-8 mb-2 opacity-30" aria-hidden="true" />
            <p className="font-mono text-xs">Ожидание событий...</p>
          </div>
        ) : (
          rows.map((line) => (
            <FeedRow key={line.key} line={line} agentNameById={agentNameById} />
          ))
        )}
      </div>
    </Card>
  );
}

interface FeedLine {
  key: string;
  direction: 'in' | 'out';
  text: string;
  failed: boolean;
  timestamp: string;
  agentId?: string;
  peer: string;
  peerTitle: string | null;
}

function toFeedLines(item: ActivityItem): FeedLine[] {
  const lines: FeedLine[] = [];

  if (item.incoming) {
    lines.push({
      key: `${item.id}:in`,
      direction: 'in',
      text: incomingBody(item.incoming.content),
      failed: false,
      timestamp: item.incoming.createdAt,
      agentId: item.agentId,
      peer: item.peer,
      peerTitle: item.peerTitle,
    });
  } else if (item.trigger) {
    lines.push({
      key: `${item.id}:in`,
      direction: 'in',
      text: item.trigger.content,
      failed: false,
      timestamp: item.trigger.createdAt,
      agentId: item.agentId,
      peer: item.peer,
      peerTitle: item.peerTitle,
    });
  }

  if (item.actions.length > 0) {
    const failedAction = item.actions.find((a) => a.status === 'failed');
    const text = failedAction?.hint
      ? `${failedAction.label} — ${failedAction.hint}`
      : item.actions
          .map((a) => a.label)
          .slice(0, 3)
          .join(', ');
    lines.push({
      key: `${item.id}:act`,
      direction: 'out',
      text,
      failed: Boolean(failedAction),
      timestamp: item.endedAt ?? item.createdAt,
      agentId: item.agentId,
      peer: item.peer,
      peerTitle: item.peerTitle,
    });
  }

  if (item.response) {
    lines.push({
      key: `${item.id}:resp`,
      direction: 'out',
      text: item.response.content,
      failed: false,
      timestamp: item.response.createdAt,
      agentId: item.agentId,
      peer: item.peer,
      peerTitle: item.peerTitle,
    });
  }

  if (lines.length === 0) {
    lines.push({
      key: `${item.id}:empty`,
      direction: 'out',
      text: '—',
      failed: false,
      timestamp: item.createdAt,
      agentId: item.agentId,
      peer: item.peer,
      peerTitle: item.peerTitle,
    });
  }
  return lines;
}

function FeedRow({ line, agentNameById }: { line: FeedLine; agentNameById: Map<string, string> }) {
  const time = formatDistanceToNow(new Date(line.timestamp), {
    addSuffix: true,
    locale: ru,
  });
  const agentName = line.agentId ? agentNameById.get(line.agentId) : undefined;
  const peerLabel = line.peerTitle ?? (line.peer ? `ID ${line.peer}` : null);

  return (
    <div className={cn(
      'flex gap-2.5 px-3 py-2 rounded-sm text-xs font-mono group hover:bg-muted/40 transition-colors',
      line.failed ? 'border-l-2 border-destructive/60' : 'border-l-2 border-muted',
    )}>
      {agentName && (
        <span className="shrink-0 text-muted-foreground">{truncate(sanitizeText(agentName), 16)}</span>
      )}
      <span
        className={cn(
          'shrink-0 font-bold',
          line.direction === 'in' ? 'text-primary' : 'text-success',
        )}
        title={line.direction === 'in' ? 'Входящее от собеседника' : 'Действие агента'}
      >
        {line.direction === 'in' ? '←' : '→'}
      </span>
      {peerLabel && (
        <span
          className={cn(
            'shrink-0 max-w-[140px] truncate',
            line.direction === 'in' ? 'text-primary' : 'text-muted-foreground',
          )}
        >
          {sanitizeText(peerLabel)}
        </span>
      )}
      <span className={cn('flex-1 truncate', line.failed ? 'text-destructive' : line.direction === 'in' ? 'text-foreground' : 'text-muted-foreground')}>
        {truncate(sanitizeText(line.text), 140)}
      </span>
      <span className="text-muted-foreground shrink-0">{time}</span>
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
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[...Array(3)].map((_, i) => (
          <Skeleton key={i} className="h-[160px] rounded-sm" />
        ))}
      </div>
      <Skeleton className="h-[480px] rounded-sm" />
    </div>
  );
}

function NoAgents() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center animate-fade-in">
      <div className="h-16 w-16 rounded-sm bg-muted border border-border flex items-center justify-center" aria-hidden="true">
        <Bot className="h-8 w-8 text-muted-foreground" />
      </div>
      <h1 className="mt-6 font-display text-2xl font-bold text-foreground">Нет агентов</h1>
      <p className="mt-2 font-mono text-sm text-muted-foreground max-w-xs leading-relaxed">
        Вы ещё не создали агентов. Пройдите онбординг, чтобы создать первого.
      </p>
      <Link href="/onboarding" className={cn(buttonVariants({ variant: 'default', size: 'md' }), 'mt-6')}>
        <Plus className="h-4 w-4" />
        Создать агента
      </Link>
    </div>
  );
}
