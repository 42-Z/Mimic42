'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { AlertTriangle, ArrowLeft } from 'lucide-react';

import { AttackDetail as AttackDetailView } from '@/components/attacks/AttackDetail';
import { AttackForm } from '@/components/attacks/AttackForm';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, Skeleton } from '@/components/ui/card';
import { useToast } from '@/components/ui/toast';
import {
  useAddAttackAgent,
  useAttack,
  useAttackAgents,
  useCancelAttack,
  useRemoveAttackAgent,
  useRepeatAttack,
  useStartAttack,
  useUpdateAttack,
} from '@/hooks/useAttacks';
import { editInitialFromAttack, isEditableStatus } from '@/lib/attacks/display';
import { attackIdSchema } from '@/lib/attacks/validators';
import { cn } from '@/lib/utils';
import type { ApiError, AttackPatch } from '@/types';

function apiMessage(error: unknown): string {
  return (error as ApiError).message ?? 'Не удалось выполнить действие';
}

function loadErrorText(error: unknown): string {
  const status = (error as ApiError).status;
  if (status === 404) return 'Атака не найдена или недоступна.';
  return status
    ? `Сервер ответил ошибкой ${status}. Попробуйте обновить страницу.`
    : 'Сервер не ответил. Попробуйте обновить страницу.';
}

export default function AttackDetailPage() {
  const params = useParams();
  const rawId = typeof params['id'] === 'string' ? params['id'] : '';
  const parsed = attackIdSchema.safeParse(rawId);

  if (!parsed.success) {
    return (
      <div className="flex flex-col gap-4">
        <BackLink />
        <PageTitle />
        <Card variant="bordered" padding="lg" className="text-center">
          <p className="font-mono text-sm text-destructive">Недопустимый ID атаки.</p>
        </Card>
      </div>
    );
  }

  return <AttackDetailContent attackId={parsed.data} />;
}

function AttackDetailContent({ attackId }: { attackId: string }) {
  const router = useRouter();
  const { toast } = useToast();
  const [editing, setEditing] = useState(false);

  const attackQuery = useAttack(attackId);
  const agentsQuery = useAttackAgents();
  const start = useStartAttack(attackId);
  const cancel = useCancelAttack(attackId);
  const repeat = useRepeatAttack(attackId);
  const update = useUpdateAttack(attackId);
  const addAgent = useAddAttackAgent(attackId);
  const removeAgent = useRemoveAttackAgent(attackId);

  const attack = attackQuery.data;

  useEffect(() => {
    if (editing && attack && !isEditableStatus(attack.status)) setEditing(false);
  }, [attack, editing]);

  const handleUpdate = (patch: AttackPatch) => {
    update.mutate(patch, {
      onSuccess: () => {
        setEditing(false);
        toast('Изменения сохранены', 'success');
      },
      onError: (error) => toast(apiMessage(error), 'error'),
    });
  };

  const rosterIds = new Set(
    (attack?.agents ?? [])
      .filter((agent) => agent.status !== 'exited')
      .map((agent) => agent.agent_id),
  );
  const availableAgents = (agentsQuery.data ?? []).filter(
    (agent) => !rosterIds.has(agent.agent_id),
  );

  const pendingAction = start.isPending
    ? 'start'
    : cancel.isPending
      ? 'cancel'
      : repeat.isPending
        ? 'repeat'
        : null;

  return (
    <div className="flex flex-col gap-4 animate-fade-in">
      <BackLink />

      {attackQuery.isLoading ? (
        <div className="flex flex-col gap-4">
          <PageTitle />
          <AttackDetailSkeleton />
        </div>
      ) : attackQuery.isError ? (
        <div className="flex flex-col gap-4">
          <PageTitle />
          <Alert variant="destructive">
            <AlertTriangle aria-hidden="true" />
            <AlertTitle>Не удалось загрузить атаку</AlertTitle>
            <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
              {loadErrorText(attackQuery.error)}
              <Button variant="outline" size="sm" onClick={() => void attackQuery.refetch()}>
                Повторить
              </Button>
            </AlertDescription>
          </Alert>
        </div>
      ) : !attack ? (
        <div className="flex flex-col gap-4">
          <PageTitle />
          <Alert variant="destructive">
            <AlertTriangle aria-hidden="true" />
            <AlertTitle>Атака не найдена</AlertTitle>
            <AlertDescription>
              Возможно, её удалили или у вас нет доступа к этому владельцу.
            </AlertDescription>
          </Alert>
        </div>
      ) : editing ? (
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
          <div>
            <h1 className="font-display text-2xl font-bold text-foreground">
              Редактирование атаки
            </h1>
            <p className="mt-1 font-mono text-xs text-muted-foreground">
              Ссылка на пост заблокирована. Тексты, картинки и лимит применятся после сохранения.
            </p>
          </div>
          <AttackForm
            mode="edit"
            targetLink={attack.target_link}
            editInitial={editInitialFromAttack(attack)}
            slowmodeSeconds={attack.slowmode_seconds}
            sentCount={attack.sent_count}
            submitting={update.isPending ? 'save' : null}
            onUpdate={handleUpdate}
            onCancel={() => setEditing(false)}
          />
        </div>
      ) : (
        <AttackDetailView
          attack={attack}
          availableAgents={availableAgents}
          agentsLoading={agentsQuery.isLoading}
          pendingAction={pendingAction}
          addingAgentId={addAgent.isPending ? (addAgent.variables ?? null) : null}
          removingAgentId={removeAgent.isPending ? (removeAgent.variables ?? null) : null}
          onStart={() =>
            start.mutate(undefined, {
              onSuccess: () => toast('Атака запущена', 'success'),
              onError: (error) => toast(apiMessage(error), 'error'),
            })
          }
          onCancel={() =>
            cancel.mutate(undefined, {
              onSuccess: () => toast('Атака отменена', 'warning'),
              onError: (error) => toast(apiMessage(error), 'error'),
            })
          }
          onRepeat={() =>
            repeat.mutate(undefined, {
              onSuccess: (created) => {
                toast('Создан новый черновик', 'success');
                router.push(`/attacks/${created.id}`);
              },
              onError: (error) => toast(apiMessage(error), 'error'),
            })
          }
          onEdit={() => setEditing(true)}
          onAddAgent={(agentId) =>
            addAgent.mutate(agentId, {
              onSuccess: () => toast('Мимик добавлен в атаку', 'success'),
              onError: (error) => toast(apiMessage(error), 'error'),
            })
          }
          onRemoveAgent={(agent) =>
            removeAgent.mutate(agent.agent_id, {
              onSuccess: () => toast('Мимик убран из атаки', 'warning'),
              onError: (error) => toast(apiMessage(error), 'error'),
            })
          }
        />
      )}
    </div>
  );
}

function PageTitle() {
  return <h1 className="font-display text-2xl font-bold text-foreground">Атака</h1>;
}

function BackLink() {
  return (
    <Link
      href="/attacks"
      className={cn(
        'inline-flex w-fit items-center gap-1.5 rounded-sm font-mono text-xs text-muted-foreground transition-colors hover:text-foreground',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
      )}
    >
      <ArrowLeft className="size-3.5" aria-hidden="true" />
      Все атаки
    </Link>
  );
}

function AttackDetailSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-32 rounded-sm" />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="flex flex-col gap-4">
          <Skeleton className="h-28 rounded-sm" />
          <Skeleton className="h-48 rounded-sm" />
          <Skeleton className="h-40 rounded-sm" />
        </div>
        <div className="flex flex-col gap-4">
          <Skeleton className="h-40 rounded-sm" />
          <Skeleton className="h-56 rounded-sm" />
        </div>
      </div>
    </div>
  );
}
