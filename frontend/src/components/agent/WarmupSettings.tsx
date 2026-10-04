'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { AlertTriangle } from 'lucide-react';

import { Card, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { useToast } from '@/components/ui/toast';
import { useStartWarmupRecovery, useWarmupState } from '@/hooks/useAgent';
import { useDeleteAgent } from '@/hooks/useAgents';
import type { ApiError, WarmupSettings } from '@/types';

export const EMPTY_WARMUP: WarmupSettings = { enabled: false };

/**
 * Прочитать настройку из нетипизированной JSON-колонки `agents.settings`.
 *
 * Чужая форма даёт выключенный прогрев, а не падение формы — как parse_warmup
 * на бэкенде.
 */
export function readWarmup(settings: Record<string, unknown> | null | undefined): WarmupSettings {
  const raw = settings?.['warmup'];
  if (typeof raw !== 'object' || raw === null) return EMPTY_WARMUP;
  return { enabled: (raw as { enabled?: unknown }).enabled === true };
}

export function WarmupSettingsSection({
  value,
  onChange,
}: {
  value: WarmupSettings;
  onChange: (update: (prev: WarmupSettings) => WarmupSettings) => void;
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
        <Switch
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
 * восстановления или удалить агента. Состояние живёт на сервере: выбор уходит отдельным
 * запросом и не зависит от того, что сейчас в форме настроек.
 */
export function WarmupRestrictionNotice({ agentId }: { agentId: string }) {
  const { toast } = useToast();
  const router = useRouter();
  const { data: state } = useWarmupState(agentId);
  const recovery = useStartWarmupRecovery(agentId);
  const { mutate: remove, isPending: deleting } = useDeleteAgent();
  const [confirmDelete, setConfirmDelete] = useState(false);

  if (!state || state.restricted_at === null) return null;

  const since = new Date(state.restricted_at).toLocaleString('ru-RU');

  const startRecovery = () =>
    recovery.mutate(undefined, {
      onSuccess: () => toast('Режим восстановления включён', 'success'),
      onError: (e: unknown) =>
        toast((e as ApiError).message ?? 'Не удалось включить восстановление', 'error'),
    });

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

      {state.recovery ? (
        <p className="font-mono text-xs text-foreground max-w-prose">
          Режим восстановления включён: другие агенты чаще пишут этому, а он отвечает. Раз в
          несколько часов мы спрашиваем @SpamBot, снято ли ограничение, и тогда возвращаем
          обычный прогрев. Поможет ли это снять ограничение быстрее, неизвестно. Работает, даже
          если переключатель прогрева выключен.
        </p>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" onClick={startRecovery} isLoading={recovery.isPending}>
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
