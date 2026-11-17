'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { AlertTriangle, Plus, Swords } from 'lucide-react';

import { AttackCard } from '@/components/attacks/AttackCard';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, Skeleton } from '@/components/ui/card';
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
import { useToast } from '@/components/ui/toast';
import { useAttacks, useCancelAttack, useRepeatAttack } from '@/hooks/useAttacks';
import { cn } from '@/lib/utils';
import type { ApiError, AttackDetail } from '@/types';

function apiMessage(error: unknown): string {
  return (error as ApiError).message ?? 'Не удалось выполнить действие';
}

function loadErrorText(error: unknown): string {
  const status = (error as ApiError).status;
  return status
    ? `Сервер ответил ошибкой ${status}. Попробуйте обновить список.`
    : 'Сервер не ответил. Попробуйте обновить список.';
}

export default function AttacksPage() {
  const { data, isLoading, isError, error, refetch } = useAttacks();

  const active = data?.active ?? [];
  const archive = data?.archive ?? [];
  const running = active.filter((attack) => attack.status === 'running').length;

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <div
            className="flex size-10 shrink-0 items-center justify-center rounded-sm border border-primary/20 bg-primary/10"
            aria-hidden="true"
          >
            <Swords className="size-5 text-primary" />
          </div>
          <div>
            <h1 className="font-display text-2xl font-bold text-foreground">Атаки</h1>
            <p className="mt-1 font-mono text-xs text-muted-foreground">
              {isLoading
                ? 'Загружаем кампании…'
                : running > 0
                  ? `${running} идёт · ${active.length} активных · ${archive.length} в архиве`
                  : `${active.length} активных · ${archive.length} в архиве`}
            </p>
          </div>
        </div>
        <Link href="/attacks/new" className={buttonVariants({ variant: 'default', size: 'sm' })}>
          <Plus className="size-3.5" aria-hidden="true" />
          Создать атаку
        </Link>
      </div>

      {isLoading ? (
        <AttacksSkeleton />
      ) : isError ? (
        <Alert variant="destructive">
          <AlertTriangle aria-hidden="true" />
          <AlertTitle>Не удалось загрузить атаки</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
            {loadErrorText(error)}
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              Повторить
            </Button>
          </AlertDescription>
        </Alert>
      ) : active.length === 0 && archive.length === 0 ? (
        <Empty className="border-border bg-card/40 py-16">
          <EmptyMedia variant="icon">
            <Swords aria-hidden="true" />
          </EmptyMedia>
          <EmptyHeader>
            <EmptyTitle>Атак пока нет</EmptyTitle>
            <EmptyDescription>
              Создайте кампанию на один пост: назначьте мимиков, добавьте тексты и картинки, а
              затем запустите её.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Link
              href="/attacks/new"
              className={cn(buttonVariants({ variant: 'default', size: 'sm' }), 'gap-1.5')}
            >
              <Plus className="size-3.5" aria-hidden="true" />
              Создать атаку
            </Link>
          </EmptyContent>
        </Empty>
      ) : (
        <div className="flex flex-col gap-6">
          <section aria-labelledby="attacks-active-title" data-testid="active-attacks">
            <div className="mb-3 flex items-center gap-3">
              <h2
                id="attacks-active-title"
                className="font-mono text-xs font-semibold uppercase tracking-wider text-muted-foreground"
              >
                Активные
              </h2>
              <Badge variant="outline">{active.length}</Badge>
              <div className="h-px flex-1 bg-border" aria-hidden="true" />
            </div>
            {active.length === 0 ? (
              <Card
                variant="bordered"
                padding="md"
                className="border-dashed border-border bg-card/30 text-center"
              >
                <p className="font-mono text-xs text-muted-foreground">
                  Активных атак нет. Создайте новую или повторите архивную.
                </p>
              </Card>
            ) : (
              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                {active.map((attack) => (
                  <AttackListItem key={attack.id} attack={attack} />
                ))}
              </div>
            )}
          </section>

          {archive.length > 0 && (
            <section aria-labelledby="attacks-archive-title" data-testid="archive-attacks">
              <div className="mb-3 flex items-center gap-3">
                <h2
                  id="attacks-archive-title"
                  className="font-mono text-xs font-semibold uppercase tracking-wider text-muted-foreground"
                >
                  Архив
                </h2>
                <Badge variant="outline">{archive.length}</Badge>
                <div className="h-px flex-1 bg-border" aria-hidden="true" />
              </div>
              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                {archive.map((attack) => (
                  <AttackListItem key={attack.id} attack={attack} />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

function AttackListItem({ attack }: { attack: AttackDetail }) {
  const router = useRouter();
  const { toast } = useToast();
  const cancel = useCancelAttack(attack.id);
  const repeat = useRepeatAttack(attack.id);

  return (
    <AttackCard
      attack={attack}
      cancelling={cancel.isPending}
      repeating={repeat.isPending}
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
    />
  );
}

function AttacksSkeleton() {
  return (
    <div className="space-y-6">
      {[0, 1].map((section) => (
        <div key={section} className="space-y-3">
          <Skeleton className="h-4 w-28" />
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {[0, 1].map((card) => (
              <Skeleton key={card} className="h-56 rounded-sm" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
