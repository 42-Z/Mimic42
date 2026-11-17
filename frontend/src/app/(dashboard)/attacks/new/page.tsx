'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { AlertTriangle, ArrowLeft, Swords } from 'lucide-react';

import { AttackForm } from '@/components/attacks/AttackForm';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/toast';
import {
  useAttackAgents,
  useCreateAndStartAttack,
  useCreateAttack,
} from '@/hooks/useAttacks';
import { cn } from '@/lib/utils';
import type { ApiError, AttackDraft } from '@/types';

function apiMessage(error: unknown): string {
  return (error as ApiError).message ?? 'Не удалось сохранить атаку';
}

export default function NewAttackPage() {
  const router = useRouter();
  const { toast } = useToast();
  const agents = useAttackAgents();
  const create = useCreateAttack();
  const createAndStart = useCreateAndStartAttack();

  const handleCreate = (draft: AttackDraft, intent: 'draft' | 'start') => {
    const mutation = intent === 'start' ? createAndStart : create;
    mutation.mutate(draft, {
      onSuccess: (attack) => {
        toast(intent === 'start' ? 'Атака запущена' : 'Черновик сохранён', 'success');
        router.push(`/attacks/${attack.id}`);
      },
      onError: (error) => toast(apiMessage(error), 'error'),
    });
  };

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 animate-fade-in">
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

      <div className="flex items-center gap-4">
        <div
          className="flex size-10 shrink-0 items-center justify-center rounded-sm border border-primary/20 bg-primary/10"
          aria-hidden="true"
        >
          <Swords className="size-5 text-primary" />
        </div>
        <div>
          <h1 className="font-display text-2xl font-bold text-foreground">Новая атака</h1>
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            Кампания на один пост: тексты, картинки, лимит и мимики. Запуск — отдельной кнопкой.
          </p>
        </div>
      </div>

      {agents.isError && (
        <Alert variant="destructive">
          <AlertTriangle aria-hidden="true" />
          <AlertTitle>Не удалось загрузить мимиков</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
            Форму можно заполнить, но выбрать мимиков пока нельзя.
            <Button variant="outline" size="sm" onClick={() => void agents.refetch()}>
              Повторить
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <AttackForm
        mode="create"
        agents={agents.data ?? []}
        agentsLoading={agents.isLoading}
        submitting={createAndStart.isPending ? 'start' : create.isPending ? 'draft' : null}
        onCreate={handleCreate}
      />
    </div>
  );
}
