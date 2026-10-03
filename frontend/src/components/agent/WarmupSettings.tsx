'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { AlertTriangle } from 'lucide-react';

import { Card, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Toggle } from '@/components/agent/FirstCommentSettings';
import { useToast } from '@/components/ui/toast';
import { useUpdateAgentSettings } from '@/hooks/useAgent';
import { useDeleteAgent } from '@/hooks/useAgents';
import { agentsApi } from '@/lib/api';
import type { ApiError, WarmupSettings } from '@/types';

export const EMPTY_WARMUP: WarmupSettings = { enabled: false, restricted_at: null, recovery: false };

/**
 * Прочитать настройку из нетипизированной JSON-колонки `agents.settings`.
 *
 * Чужая форма даёт выключенный прогрев, а не падение формы — как parse_warmup
 * на бэкенде.
 */
export function readWarmup(settings: Record<string, unknown> | null | undefined): WarmupSettings {
  const raw = settings?.['warmup'];
  if (typeof raw !== 'object' || raw === null) return EMPTY_WARMUP;
  const source = raw as { enabled?: unknown; restricted_at?: unknown; recovery?: unknown };
  return {
    enabled: source.enabled === true,
    restricted_at:
      typeof source.restricted_at === 'string' && source.restricted_at ? source.restricted_at : null,
    recovery: source.recovery === true,
  };
}

export function WarmupSettingsSection({
  value,
  onChange,
}: {
  value: Pick<WarmupSettings, 'enabled'>;
  onChange: (update: (prev: Pick<WarmupSettings, 'enabled'>) => Pick<WarmupSettings, 'enabled'>) => void;
}) {
  return (
    <Card variant="bordered" padding="md" className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <CardTitle className="text-sm">Прогрев аккаунта</CardTitle>
          <p className="font-mono text-xs text-muted-foreground max-w-prose">
            Пара коротких диалогов в день с другими агентами в личке, в обычное дневное время и
            с паузами между репликами, чтобы аккаунт выглядел живым. Агент должен быть запущен и
            иметь @username.
          </p>
        </div>
        <Toggle
          checked={value.enabled}
          onChange={(enabled) => onChange((prev) => ({ ...prev, enabled }))}
          label="Прогрев аккаунта"
        />
      </div>
    </Card>
  );
}

/**
 * Telegram ограничил аккаунт за сообщения незнакомым: пользователь выбирает, ждать
 * восстановления или удалить агента. Сохраняется сразу, без общей кнопки формы.
 */
export function WarmupRestrictionNotice({
  agentId,
  warmup,
  settings,
}: {
  agentId: string;
  warmup: WarmupSettings;
  settings: Record<string, unknown> | null | undefined;
}) {
  const { toast } = useToast();
  const router = useRouter();
  const update = useUpdateAgentSettings(agentId);
  const { mutate: remove, isPending: deleting } = useDeleteAgent();
  const [confirmDelete, setConfirmDelete] = useState(false);

  if (warmup.restricted_at === null) return null;

  const since = new Date(warmup.restricted_at).toLocaleString('ru-RU');

  const startRecovery = async () => {
    try {
      const existing = (settings?.['warmup'] as Record<string, unknown> | undefined) ?? {};
      await update.mutateAsync({ settings: { ...(settings ?? {}), warmup: { ...existing, recovery: true } } });
      await agentsApi.reload(agentId);
      toast('Режим восстановления включён', 'success');
    } catch (e: unknown) {
      toast((e as ApiError).message ?? 'Не удалось включить восстановление', 'error');
    }
  };

  const deleteAgent = () =>
    remove(agentId, {
      onSuccess: () => router.push('/dashboard'),
      onError: (e: unknown) => toast((e as ApiError).message ?? 'Не удалось удалить', 'error'),
    });

  return (
    <Card variant="bordered" padding="md" className="space-y-3 border-amber-900 bg-amber-950/30">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
        <div className="space-y-1">
          <CardTitle className="text-sm">Аккаунт ограничен Telegram</CardTitle>
          <p className="font-mono text-xs text-muted-foreground max-w-prose">
            С {since} Telegram не даёт этому аккаунту писать первым незнакомым людям. Отвечать он
            может. Обычно ограничение снимается само через несколько дней, и ускорить это
            нельзя.
          </p>
        </div>
      </div>

      {warmup.recovery ? (
        <p className="font-mono text-xs text-foreground">
          Режим восстановления включён: другие агенты чаще пишут этому, а он отвечает. Раз в
          несколько часов мы спрашиваем @SpamBot, снято ли ограничение, и тогда возвращаем
          обычный прогрев. Поможет ли это снять ограничение быстрее, неизвестно.
        </p>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" onClick={startRecovery} isLoading={update.isPending}>
            Восстановить перепиской
          </Button>
          {confirmDelete ? (
            <Button type="button" size="sm" variant="danger" onClick={deleteAgent} isLoading={deleting}>
              Точно удалить агента
            </Button>
          ) : (
            <Button type="button" size="sm" variant="outline" onClick={() => setConfirmDelete(true)}>
              Удалить агента
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}
