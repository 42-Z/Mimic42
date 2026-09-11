'use client';

import { useState, useEffect } from 'react';
import { useParams, useSearchParams, useRouter } from 'next/navigation';
import { agentIdSchema } from '@/lib/validators';
import { useAgentStatus, useAgentDetails, useUpdateAgentSettings } from '@/hooks/useAgent';
import { useAgentStatusRealtime } from '@/hooks/useRealtimeFeed';
import { TabLogsChat } from '@/components/chat/TabLogsChat';
import { TabLogs } from '@/components/agent/TabLogs';
import { TabAnalytics } from '@/components/agent/TabAnalytics';
import { useTelegramSession } from '@/hooks/useTelegramSession';
import { useStartAgent, useStopAgent, useTriggerMessage, useDeleteAgent } from '@/hooks/useAgents';
import { useAgentMemories, useAgentMemoryHistory } from '@/hooks/useMemory';
import { useToast } from '@/components/ui/toast';
import { AgentStatusBadge } from '@/components/agents/AgentStatusBadge';
import { Button } from '@/components/ui/button';
import { Input, Textarea } from '@/components/ui/input';
import { Card, Skeleton, Spinner, Divider } from '@/components/ui/card';
import { ConfirmDialog, Modal } from '@/components/ui/modal';
import { sanitizeText, maskPhoneNumber } from '@/lib/sanitize';
import {
  agentSettingsSchema, triggerMessageSchema,
  type AgentSettingsValues, type TriggerMessageValues,
} from '@/lib/validators';
import { DEFAULT_MODEL, MODEL_OPTIONS } from '@/lib/models';
import { agentsApi } from '@/lib/api';
import {
  Settings, ScrollText, Zap, MessageSquare, BarChart2, Brain,
  Play, Square, Send, AlertTriangle, RefreshCw,
  Bot, Clock, Search, Trash2,
} from 'lucide-react';
import { formatDistanceToNow, format } from 'date-fns';
import { ru } from 'date-fns/locale';
import { cn } from '@/lib/utils';
import type { AgentTab, ApiError } from '@/types';

const TABS: { id: AgentTab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'settings',  label: 'Настройки',  icon: Settings },
  { id: 'logs',      label: 'Логи',        icon: ScrollText },
  { id: 'actions',   label: 'Управление',  icon: Zap },
  { id: 'telegram',  label: 'Telegram',    icon: MessageSquare },
  { id: 'analytics', label: 'Аналитика',   icon: BarChart2 },
  { id: 'memory',    label: 'Память',      icon: Brain },
];

export default function AgentPage() {
  const params = useParams();
  const searchParams = useSearchParams();

  const rawId = params['id'] as string;
  const parsed = agentIdSchema.safeParse(rawId);
  if (!parsed.success) {
    return <div className="p-8 font-mono text-crimson-400">Недопустимый ID агента</div>;
  }
  const initialTab = (searchParams.get('tab') as AgentTab) ?? 'settings';
  return <AgentPageContent agentId={parsed.data} initialTab={initialTab} />;
}

function AgentPageContent({
  agentId,
  initialTab,
}: {
  agentId: string;
  initialTab: AgentTab;
}) {
  const router = useRouter();

  const [activeTab, setActiveTab] = useState<AgentTab>(
    TABS.some(t => t.id === initialTab) ? initialTab : 'settings'
  );
  const [logsView, setLogsView] = useState<'activity' | 'chat'>('activity');

  const handleTabChange = (tab: AgentTab) => {
    setActiveTab(tab);
    router.replace(`/agent/${agentId}?tab=${tab}`, { scroll: false });
  };

  const { data: status } = useAgentStatus(agentId);
  const { data: details } = useAgentDetails(agentId);
  useAgentStatusRealtime(agentId);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Page header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="h-10 w-10 rounded-sm bg-plasma-950 border border-plasma-800 flex items-center justify-center">
            <Bot className="h-5 w-5 text-plasma-400" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="font-display text-xl font-bold text-void-100">
                {details?.name ?? <Skeleton className="h-6 w-32 inline-block" />}
              </h1>
              {status && <AgentStatusBadge state={status.state} />}
            </div>
            <p className="font-mono text-xs text-void-600 mt-0.5">{agentId}</p>
          </div>
        </div>
        <div className="hidden sm:block">
          <AgentControls agentId={agentId} state={status?.state} />
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-void-800">
        <div className="flex gap-0 overflow-x-auto" data-testid="agent-tabs">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              data-testid={`agent-tab-${tab.id}`}
              onClick={() => handleTabChange(tab.id)}
              className={cn(
                'flex items-center gap-2 px-4 py-3 font-mono text-xs border-b-2 transition-all duration-150 whitespace-nowrap',
                activeTab === tab.id
                  ? 'border-plasma-500 text-plasma-400'
                  : 'border-transparent text-void-500 hover:text-void-300 hover:border-void-700',
              )}
            >
              <tab.icon className="h-3.5 w-3.5" />
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div>
        {activeTab === 'settings'  && <TabSettings  agentId={agentId} />}
        {activeTab === 'logs'      && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              {(['activity', 'chat'] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setLogsView(v)}
                  className={cn(
                    'px-4 py-1.5 rounded-sm font-mono text-xs border transition-colors',
                    logsView === v
                      ? 'bg-plasma-950 border-plasma-800 text-plasma-400'
                      : 'border-void-700 text-void-500 hover:text-void-300'
                  )}
                >
                  {v === 'activity' ? 'Активность' : 'Чат'}
                </button>
              ))}
            </div>
            {logsView === 'activity'
              ? <TabLogs agentId={agentId} />
              : <TabLogsChat agentId={agentId} />}
          </div>
        )}
        {activeTab === 'actions'   && <TabActions    agentId={agentId} />}
        {activeTab === 'telegram'  && <TabTelegram   agentId={agentId} />}
        {activeTab === 'analytics' && <TabAnalytics  agentId={agentId} />}
        {activeTab === 'memory'    && <TabMemory agentId={agentId} />}
      </div>
    </div>
  );
}

// ── Agent Controls ────────────────────────────────────────────────────────────
function AgentControls({ agentId, state }: { agentId: string; state?: string }) {
  const { toast } = useToast();
  const { mutate: start, isPending: starting } = useStartAgent();
  const { mutate: stop,  isPending: stopping } = useStopAgent();
  const [stopConfirm, setStopConfirm] = useState(false);

  return (
    <div className="flex items-center gap-2">
      <Button variant="success" size="sm"
        onClick={() => start(agentId, {
          onSuccess: () => toast('Агент запускается', 'success'),
          onError: (e: unknown) => toast((e as ApiError).message, 'error'),
        })}
        disabled={state === 'running' || state === 'starting'}
        isLoading={starting}
        leftIcon={<Play className="h-3.5 w-3.5" />}
      >
        Запустить
      </Button>

      <Button variant="danger" size="sm"
        onClick={() => setStopConfirm(true)}
        disabled={state !== 'running'}
        isLoading={stopping}
        leftIcon={<Square className="h-3.5 w-3.5" />}
      >
        Стоп
      </Button>

      <ConfirmDialog
        isOpen={stopConfirm}
        onClose={() => setStopConfirm(false)}
        onConfirm={() => {
          setStopConfirm(false);
          stop(agentId, {
            onSuccess: () => toast('Агент остановлен', 'warning'),
            onError: (e: unknown) => toast((e as ApiError).message, 'error'),
          });
        }}
        title="Остановить агента?"
        description="Агент перестанет отвечать на сообщения. Вы сможете перезапустить его в любой момент."
        confirmLabel="Остановить"
        variant="danger"
      />
    </div>
  );
}

// ── Tab: Settings ─────────────────────────────────────────────────────────────
function TabSettings({ agentId }: { agentId: string }) {
  const { toast } = useToast();
  const { data: details, isLoading } = useAgentDetails(agentId);
  const update = useUpdateAgentSettings(agentId);

  const [values, setValues] = useState<AgentSettingsValues>({
    name: '', soul_prompt: '', reasoning_effort: 'high', model: DEFAULT_MODEL,
  });
  const [formErrors, setFormErrors] = useState<Partial<Record<keyof AgentSettingsValues, string>>>({});
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (details) {
      setValues({
        name: details.name,
        soul_prompt: details.soul_prompt ?? '',
        reasoning_effort: (details.settings?.reasoning_effort as 'none' | 'medium' | 'high') ?? 'high',
        model: (details.settings?.model as string) ?? DEFAULT_MODEL,
      });
    }
  }, [details]);

  const set = (field: keyof AgentSettingsValues, value: string) => {
    setValues((v) => ({ ...v, [field]: value }));
    setDirty(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = agentSettingsSchema.safeParse(values);
    if (!result.success) {
      const fe: Partial<Record<keyof AgentSettingsValues, string>> = {};
      result.error.issues.forEach(i => { fe[i.path[0] as keyof AgentSettingsValues] = i.message; });
      setFormErrors(fe);
      return;
    }
    setFormErrors({});
    try {
      // Merge instead of overwrite: keep settings keys the form does not own.
      const existingSettings = (details?.settings ?? {}) as Record<string, unknown>;
      const submissionData = {
        name: result.data.name,
        soul_prompt: result.data.soul_prompt,
        settings: {
          ...existingSettings,
          reasoning_effort: result.data.reasoning_effort,
          model: result.data.model,
        },
      };
      await update.mutateAsync(submissionData);
      // The runtime is built once: new settings need a rebuild.
      await agentsApi.reload(agentId);
      toast('Настройки сохранены', 'success');
      setDirty(false);
    } catch (e: unknown) {
      toast((e as ApiError).message ?? 'Ошибка сохранения', 'error');
    }
  };

  if (isLoading) return <SettingsSkeleton />;

  return (
    <form onSubmit={handleSave} className="max-w-2xl space-y-6">
      <Input
        label="Имя агента"
        value={values.name}
        onChange={(e) => set('name', e.target.value)}
        error={formErrors.name}
      />

      <Textarea
        label="SOUL.md — Характер"
        value={values.soul_prompt}
        onChange={(e) => set('soul_prompt', e.target.value)}
        error={formErrors.soul_prompt}
        className="min-h-[200px]"
        showCount
        maxLength={50000}
        hint="Описание личности, стиля общения и особенностей агента"
      />

      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-mono font-medium text-void-300 uppercase tracking-wider">
          Модель
        </label>
        <select
          value={values.model}
          onChange={(e) => set('model', e.target.value)}
          className="flex h-10 w-full rounded-sm bg-void-800 border border-void-600 px-3 py-2 font-mono text-base sm:text-sm text-void-100 placeholder:text-void-500 transition-colors duration-150 focus:outline-none focus:ring-1 focus:ring-plasma-500 focus:border-plasma-600 hover:border-void-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {MODEL_OPTIONS.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}{m.freeVariant ? ' · есть бесплатный лимит' : ''}
            </option>
          ))}
        </select>
        <p className="text-xs font-mono text-void-400">
          У моделей с бесплатным лимитом он расходуется первым; при его исчерпании
          автоматически используется платная версия.
        </p>
        {formErrors.model && (
          <p className="text-xs text-crimson-400 font-mono flex items-center gap-1">
            <span aria-hidden="true">✗</span>
            {formErrors.model}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-mono font-medium text-void-300 uppercase tracking-wider">
          Уровень рассуждения (Reasoning Effort)
        </label>
        <select
          value={values.reasoning_effort}
          onChange={(e) => set('reasoning_effort', e.target.value)}
          className="flex h-10 w-full rounded-sm bg-void-800 border border-void-600 px-3 py-2 font-mono text-base sm:text-sm text-void-100 placeholder:text-void-500 transition-colors duration-150 focus:outline-none focus:ring-1 focus:ring-plasma-500 focus:border-plasma-600 hover:border-void-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <option value="none">None (Без рассуждения)</option>
          <option value="medium">Medium (Среднее рассуждение)</option>
          <option value="high">High (Глубокое рассуждение)</option>
        </select>
        {formErrors.reasoning_effort && (
          <p className="text-xs text-crimson-400 font-mono flex items-center gap-1">
            <span aria-hidden="true">✗</span>
            {formErrors.reasoning_effort}
          </p>
        )}
      </div>

      <div className="flex items-center gap-3 pt-2">
        <Button type="submit" isLoading={update.isPending} disabled={!dirty}>
          Сохранить изменения
        </Button>
        {dirty && (
          <span className="font-mono text-xs text-amber-400">● Есть несохранённые изменения</span>
        )}
      </div>
    </form>
  );
}

function SettingsSkeleton() {
  return (
    <div className="max-w-2xl space-y-6">
      {[120, 240, 200].map((h, i) => <Skeleton key={i} style={{ height: h }} />)}
    </div>
  );
}

// ── Tab: Actions ──────────────────────────────────────────────────────────────
function TabActions({ agentId }: { agentId: string }) {
  const { toast } = useToast();
  const router = useRouter();
  const { mutate: start, isPending: starting } = useStartAgent();
  const { mutate: stop,  isPending: stopping }  = useStopAgent();
  const { mutate: remove, isPending: deleting } = useDeleteAgent();
  const trigger = useTriggerMessage(agentId);
  const [stopConfirm, setStopConfirm] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [triggerModal, setTriggerModal] = useState(false);
  const [triggerValues, setTriggerValues] = useState<TriggerMessageValues>({ peer: '', text: '' });
  const [triggerErrors, setTriggerErrors] = useState<Partial<TriggerMessageValues>>({});
  const [triggerResult, setTriggerResult] = useState<string | null>(null);

  const handleTrigger = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = triggerMessageSchema.safeParse(triggerValues);
    if (!result.success) {
      const fe: Partial<TriggerMessageValues> = {};
      result.error.issues.forEach(i => { fe[i.path[0] as keyof TriggerMessageValues] = i.message; });
      setTriggerErrors(fe);
      return;
    }
    setTriggerErrors({});
    try {
      const res = await trigger.mutateAsync(result.data);
      setTriggerResult(res.sent ? '✓ Отправлено' : `✗ ${res.error ?? 'Ошибка'}`);
      toast(res.sent ? 'Сообщение отправлено' : (res.error ?? 'Ошибка'), res.sent ? 'success' : 'error');
    } catch (e: unknown) {
      toast((e as ApiError).message, 'error');
    }
  };

  const actions = [
    {
      title: 'Запустить агента',
      desc: 'Агент начнёт получать и отвечать на сообщения в Telegram',
      icon: Play,
      color: 'text-neon-400',
      bg: 'bg-neon-950/40 border-neon-900',
      action: () => start(agentId, {
        onSuccess: () => toast('Агент запускается', 'success'),
        onError: (e: unknown) => toast((e as ApiError).message, 'error'),
      }),
      loading: starting,
      label: 'Запустить',
      variant: 'success' as const,
      destructive: false,
    },
    {
      title: 'Остановить агента',
      desc: 'Агент перестанет обрабатывать входящие сообщения',
      icon: Square,
      color: 'text-crimson-400',
      bg: 'bg-crimson-950/40 border-crimson-900',
      action: () => setStopConfirm(true),
      loading: stopping,
      label: 'Остановить',
      variant: 'danger' as const,
      destructive: true,
    },
    {
      title: 'Отправить сообщение',
      desc: 'Принудительно отправить сообщение конкретному пользователю',
      icon: Send,
      color: 'text-plasma-400',
      bg: 'bg-plasma-950/40 border-plasma-900',
      action: () => { setTriggerResult(null); setTriggerModal(true); },
      loading: false,
      label: 'Отправить',
      variant: 'default' as const,
      destructive: false,
    },
    {
      title: 'Удалить агента',
      desc: 'Полностью удалить агента, его историю и Telegram-сессию',
      icon: Trash2,
      color: 'text-crimson-400',
      bg: 'bg-crimson-950/40 border-crimson-900',
      action: () => setDeleteConfirm(true),
      loading: deleting,
      label: 'Удалить',
      variant: 'danger' as const,
      destructive: true,
    },
  ];

  return (
    <div className="max-w-2xl space-y-4">
      {actions.map((a) => (
        <Card key={a.title} variant="glass" padding="md" className={cn('flex items-center justify-between gap-4 border', a.bg)}>
          <div className="flex items-start gap-4">
            <div className={cn('h-9 w-9 rounded-sm flex items-center justify-center shrink-0 bg-void-800')}>
              <a.icon className={cn('h-4 w-4', a.color)} />
            </div>
            <div>
              <p className="font-mono text-sm font-medium text-void-200">{a.title}</p>
              <p className="font-mono text-xs text-void-500 mt-0.5">{a.desc}</p>
            </div>
          </div>
          <Button variant={a.variant} size="sm" onClick={a.action} isLoading={a.loading} className="shrink-0">
            {a.label}
          </Button>
        </Card>
      ))}

      <ConfirmDialog
        isOpen={stopConfirm}
        onClose={() => setStopConfirm(false)}
        onConfirm={() => {
          setStopConfirm(false);
          stop(agentId, {
            onSuccess: () => toast('Агент остановлен', 'warning'),
            onError: (e: unknown) => toast((e as ApiError).message, 'error'),
          });
        }}
        title="Остановить агента?"
        description="Агент перестанет отвечать. Можно перезапустить в любой момент."
        confirmLabel="Остановить"
        variant="danger"
      />

      <ConfirmDialog
        isOpen={deleteConfirm}
        onClose={() => setDeleteConfirm(false)}
        onConfirm={() => {
          remove(agentId, {
            onSuccess: () => {
              setDeleteConfirm(false);
              toast('Агент удалён', 'success');
              router.push('/dashboard');
            },
            onError: (e: unknown) => toast((e as ApiError).message ?? 'Ошибка удаления', 'error'),
          });
        }}
        title="Удалить агента?"
        description="Агент будет остановлен и удалён вместе с историей сообщений, событиями и Telegram-сессией. Это действие необратимо."
        confirmLabel="Удалить навсегда"
        variant="danger"
        isLoading={deleting}
      />

      <Modal isOpen={triggerModal} onClose={() => setTriggerModal(false)} title="Отправить сообщение" size="md">
        <form onSubmit={handleTrigger} className="space-y-4">
          <Input
            label="Получатель (peer)"
            placeholder="@username или +79991234567"
            value={triggerValues.peer}
            onChange={(e) => setTriggerValues(v => ({ ...v, peer: e.target.value }))}
            error={triggerErrors.peer}
          />
          <Textarea
            label="Текст сообщения"
            placeholder="Введите текст..."
            value={triggerValues.text}
            onChange={(e) => setTriggerValues(v => ({ ...v, text: e.target.value }))}
            error={triggerErrors.text}
            maxLength={4096}
            showCount
          />
          {triggerResult && (
            <p className={cn('font-mono text-sm', triggerResult.startsWith('✓') ? 'text-neon-400' : 'text-crimson-400')}>
              {triggerResult}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={() => setTriggerModal(false)}>
              Отмена
            </Button>
            <Button type="submit" size="sm" isLoading={trigger.isPending}
              leftIcon={<Send className="h-3.5 w-3.5" />}>
              Отправить
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

// ── Tab: Telegram ─────────────────────────────────────────────────────────────
function TabTelegram({ agentId }: { agentId: string }) {
  const { data: session, isLoading } = useTelegramSession(agentId);

  if (isLoading) return <Spinner className="mt-8" />;
  if (!session) return (
    <div className="font-mono text-sm text-void-500 mt-8">
      Telegram сессия не найдена
    </div>
  );

  const statusColors: Record<string, string> = {
    authorized:       'text-neon-400',
    code_requested:   'text-plasma-400',
    password_required:'text-amber-400',
    not_started:      'text-void-500',
    error:            'text-crimson-400',
    revoked:          'text-crimson-500',
  };

  const rows = [
    { label: 'Статус авторизации', value: session.authorization_status.toUpperCase(), color: statusColors[session.authorization_status] },
    { label: 'Номер телефона',      value: maskPhoneNumber(session.phone_number) },
    { label: 'API ID',              value: session.api_id ? String(session.api_id) : '—' },
    {
      label: 'Последняя авторизация',
      value: session.last_authorized_at
        ? formatDistanceToNow(new Date(session.last_authorized_at), { addSuffix: true, locale: ru })
        : '—',
    },
    { label: 'Последняя ошибка', value: session.last_error ?? '—', color: session.last_error ? 'text-crimson-400' : undefined },
  ];

  return (
    <div className="max-w-xl space-y-4">
      <Card variant="glass" padding="none">
        {rows.map((row, i) => (
          <div key={row.label} className={cn(
            'flex items-start justify-between px-5 py-4',
            i < rows.length - 1 && 'border-b border-void-800',
          )}>
            <span className="font-mono text-xs text-void-500 uppercase tracking-wider">{row.label}</span>
            <span className={cn('font-mono text-sm text-right', row.color ?? 'text-void-200')}>
              {row.value}
            </span>
          </div>
        ))}
      </Card>

      {(session.authorization_status === 'error' || session.authorization_status === 'revoked') && (
        <div className="p-4 rounded-sm bg-amber-950/20 border border-amber-900/50 flex items-center justify-between gap-4">
          <div>
            <p className="font-mono text-sm text-amber-400 font-medium">Требуется переподключение</p>
            <p className="font-mono text-xs text-amber-600 mt-0.5">
              Сессия истекла или была отозвана
            </p>
          </div>
          <Button variant="outline" size="sm" leftIcon={<RefreshCw className="h-3.5 w-3.5" />}>
            Переподключить
          </Button>
        </div>
      )}
    </div>
  );
}

// ── Tab: Memory (Interactive Read-Only View) ──────────────────────────────────
interface TabMemoryProps {
  agentId: string;
}

function TabMemory({ agentId }: TabMemoryProps) {
  const [searchVal, setSearchVal] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [selectedMemoryId, setSelectedMemoryId] = useState<string | null>(null);
  const [historyModalOpen, setHistoryModalOpen] = useState(false);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchVal), 300);
    return () => clearTimeout(timer);
  }, [searchVal]);

  const { data: memories, isLoading, error } = useAgentMemories(agentId, debouncedQuery);

  const { data: history, isLoading: isHistoryLoading } = useAgentMemoryHistory(
    agentId,
    selectedMemoryId || '',
    historyModalOpen
  );

  const handleShowHistory = (memoryId: string) => {
    setSelectedMemoryId(memoryId);
    setHistoryModalOpen(true);
  };

  const getCleanErrorMessage = (err: unknown): string => {
    if (err && typeof err === 'object' && 'message' in err) {
      return (err as { message: string }).message;
    }
    return 'Не удалось загрузить воспоминания.';
  };

  return (
    <div className="space-y-6">
      {/* Header and Search */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="font-display text-lg font-bold text-void-100 flex items-center gap-2">
            <Brain className="h-5 w-5 text-plasma-400 animate-pulse" />
            Долгосрочная память
          </h2>
          <p className="font-mono text-xs text-void-500 mt-1">
            Список фактов и предпочтений, автоматически выделенных агентом из диалогов.
          </p>
        </div>

        <div className="relative max-w-sm w-full">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-void-600" />
          <Input
            type="text"
            placeholder="Поиск воспоминаний..."
            value={searchVal}
            onChange={(e) => setSearchVal(e.target.value)}
            className="pl-9 bg-void-950/40 border-void-800 text-void-200 placeholder-void-600 focus:border-plasma-500"
          />
        </div>
      </div>

      <Divider className="border-void-900" />

      {/* Content Area */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Card variant="glass" padding="md" className="space-y-3">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-3 w-1/4 mt-4" />
          </Card>
          <Card variant="glass" padding="md" className="space-y-3">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-3 w-1/3 mt-4" />
          </Card>
        </div>
      ) : error ? (
        <Card variant="bordered" padding="lg" className="border-rose-950/40 bg-rose-950/10 text-center space-y-4">
          <AlertTriangle className="h-10 w-10 text-rose-500 mx-auto" />
          <h3 className="font-display text-base font-bold text-rose-400">
            Ошибка при загрузке памяти
          </h3>
          <p className="font-mono text-sm text-rose-600 max-w-md mx-auto">
            {getCleanErrorMessage(error)}
          </p>
        </Card>
      ) : !memories || memories.length === 0 ? (
        <Card variant="glass" padding="lg" className="text-center py-12 space-y-4 max-w-md mx-auto border-void-900">
          <Brain className="h-10 w-10 text-void-700 mx-auto" />
          <h3 className="font-display text-base font-bold text-void-400">
            {searchVal ? 'Ничего не найдено' : 'Память пуста'}
          </h3>
          <p className="font-mono text-xs text-void-600">
            {searchVal 
              ? 'Попробуйте изменить поисковый запрос.' 
              : 'Агент начнет автоматически формировать память после первых сообщений с пользователями.'}
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {memories.map((mem) => (
            <Card
              variant="glass"
              padding="md"
              key={mem.id}
              className="relative group border-void-800/80 hover:border-plasma-500/30 transition-colors flex flex-col justify-between"
            >
              <div>
                <p className="text-void-100 text-sm leading-relaxed whitespace-pre-wrap">
                  {sanitizeText(mem.memory)}
                </p>
              </div>

              <div className="mt-4 flex items-center justify-between border-t border-void-900/60 pt-3">
                <span className="font-mono text-[10px] text-void-600 flex items-center gap-1.5">
                  <Clock className="h-3 w-3" />
                  {mem.created_at 
                    ? format(new Date(mem.created_at), 'dd.MM.yyyy HH:mm', { locale: ru }) 
                    : 'Неизвестно'}
                </span>
                <Button
                  variant="ghost"
                  size="xs"
                  onClick={() => handleShowHistory(mem.id)}
                  leftIcon={<RefreshCw className="h-3 w-3" />}
                  className="text-void-400 hover:text-plasma-400 hover:bg-void-900/30 transition-all font-mono text-[10px]"
                >
                  История
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* History Timeline Modal */}
      <Modal
        isOpen={historyModalOpen}
        onClose={() => {
          setHistoryModalOpen(false);
          setSelectedMemoryId(null);
        }}
        title="История изменения воспоминания"
        size="md"
      >
        {isHistoryLoading ? (
          <div className="flex flex-col items-center justify-center py-12 space-y-4">
            <Spinner size="lg" className="text-plasma-500" />
            <span className="font-mono text-xs text-void-500">Загрузка истории изменений...</span>
          </div>
        ) : !history || history.length === 0 ? (
          <div className="text-center py-8 space-y-2">
            <Clock className="h-8 w-8 text-void-700 mx-auto" />
            <h4 className="font-display text-sm font-bold text-void-400">История отсутствует</h4>
            <p className="font-mono text-xs text-void-600">Для данного факта не найдено изменений.</p>
          </div>
        ) : (
          <div className="space-y-6 py-2 max-h-[450px] overflow-y-auto pr-2 custom-scrollbar">
            {history.map((item, index) => (
              <div key={item.id || index} className="flex gap-4 relative">
                {index < history.length - 1 && (
                  <div className="absolute left-[9px] top-6 bottom-0 w-0.5 bg-void-800" />
                )}
                
                <div className={cn(
                  "h-5 w-5 rounded-full border flex items-center justify-center shrink-0 mt-0.5 text-[8px] font-bold font-mono",
                  item.event_type === 'add' ? "bg-emerald-950/80 border-emerald-500 text-emerald-400" :
                  item.event_type === 'delete' ? "bg-rose-950/80 border-rose-500 text-rose-400" :
                  "bg-blue-950/80 border-blue-500 text-blue-400"
                )}>
                  {item.event_type === 'add' ? 'A' :
                   item.event_type === 'delete' ? 'D' : 'U'}
                </div>

                <div className="space-y-1.5 flex-1 min-w-0">
                  <div className="flex items-center gap-3">
                    <span className={cn(
                      "font-mono text-[10px] font-bold uppercase tracking-wider",
                      item.event_type === 'add' ? "text-emerald-400" :
                      item.event_type === 'delete' ? "text-rose-400" : "text-blue-400"
                    )}>
                      {item.event_type === 'add' ? 'Создано' :
                       item.event_type === 'delete' ? 'Удалено' : 'Обновлено'}
                    </span>
                    <span className="font-mono text-[10px] text-void-500">
                      {format(new Date(item.created_at), 'dd MMMM yyyy, HH:mm', { locale: ru })}
                    </span>
                  </div>

                  <p className="text-void-200 text-sm leading-relaxed bg-void-950/30 p-2.5 rounded-[4px] border border-void-900/60 break-words">
                    {sanitizeText(item.new_value || item.prev_value || '')}
                  </p>

                  {item.prev_value && item.new_value && item.prev_value !== item.new_value && (
                    <div className="text-xs border-l-2 border-void-800 pl-3 py-1 space-y-1 bg-void-950/20 rounded-r-sm">
                      <span className="text-void-500 font-mono block text-[10px]">Предыдущее значение:</span>
                      <span className="text-void-400 line-through block text-xs">{sanitizeText(item.prev_value)}</span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
        
        <div className="flex justify-end mt-6 border-t border-void-800/80 pt-4">
          <Button type="button" variant="ghost" size="sm" onClick={() => {
            setHistoryModalOpen(false);
            setSelectedMemoryId(null);
          }}>
            Закрыть
          </Button>
        </div>
      </Modal>
    </div>
  );
}
