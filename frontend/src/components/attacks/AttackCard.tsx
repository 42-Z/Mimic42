'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ArrowUpRight, ExternalLink, Gauge, RotateCcw, Square } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ConfirmDialog } from '@/components/ui/modal';
import { cn } from '@/lib/utils';
import {
  attackLimitLabel,
  attackPace,
  attackTitle,
  isArchiveStatus,
  pluralize,
  targetHref,
} from '@/lib/attacks/display';
import { AttackAgentChips } from './AttackAgentChips';
import { AttackMediaStrip } from './AttackMediaStrip';
import { AttackProgress } from './AttackProgress';
import { AttackStatusBadge } from './AttackStatusBadge';
import type { AttackDetail } from '@/types';

export interface AttackCardProps {
  attack: AttackDetail;
  onCancel?: () => void;
  onRepeat?: () => void;
  cancelling?: boolean;
  repeating?: boolean;
}

export function AttackCard({
  attack,
  onCancel,
  onRepeat,
  cancelling = false,
  repeating = false,
}: AttackCardProps) {
  const [confirmCancel, setConfirmCancel] = useState(false);
  const pace = attackPace(attack.slowmode_seconds);
  const inFlight = Math.max(0, attack.claimed_count - attack.sent_count);
  const failedAgents = attack.agents.filter((agent) => Boolean(agent.last_error));
  const canCancel = attack.status === 'running' && onCancel;
  const canRepeat = isArchiveStatus(attack.status) && onRepeat;

  return (
    <Card
      data-testid="attack-card"
      variant="glass"
      padding="none"
      className="flex h-full flex-col transition-colors hover:border-primary/25"
    >
      <div className="flex flex-col gap-3 border-b border-border/60 p-4 sm:flex-row sm:items-start sm:justify-between sm:p-5">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <AttackStatusBadge status={attack.status} />
            <Badge variant="outline">
              {attackLimitLabel(attack.limit_kind, attack.limit_value)}
            </Badge>
          </div>
          <h2 className="mt-2 min-w-0 font-display text-lg font-bold leading-tight text-foreground">
            <Link
              href={`/attacks/${attack.id}`}
              className="rounded-sm hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              {attackTitle(attack)}
            </Link>
          </h2>
          <a
            href={targetHref(attack.target_link)}
            target="_blank"
            rel="noreferrer"
            title={attack.target_link}
            className="mt-1 inline-flex max-w-full items-center gap-1.5 rounded-sm font-mono text-xs text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            <ExternalLink className="size-3.5 shrink-0" aria-hidden="true" />
            <span className="truncate">{attack.target_link}</span>
          </a>
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-3 p-4 sm:p-5">
        <AttackProgress attack={attack} />

        <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <Gauge className="size-3.5 text-primary" aria-hidden="true" />
            Темп: {pace.label}
          </span>
          <span>
            {attack.agents.length}{' '}
            {pluralize(attack.agents.length, 'мимик', 'мимика', 'мимиков')}
          </span>
          {inFlight > 0 && <span>{inFlight} в резерве</span>}
        </div>

        <AttackAgentChips agents={attack.agents} />
        {failedAgents.length > 0 && (
          <ul className="flex flex-col gap-1 rounded-sm border border-crimson-900/40 bg-crimson-950/15 p-2">
            {failedAgents.slice(0, 2).map((agent) => (
              <li
                key={agent.id}
                className="truncate font-mono text-[11px] text-crimson-200/90"
                title={agent.last_error ?? undefined}
              >
                <span className="text-crimson-300">{agent.name}:</span> {agent.last_error}
              </li>
            ))}
            {failedAgents.length > 2 && (
              <li className="font-mono text-[11px] text-crimson-300/80">
                ещё {failedAgents.length - 2}
              </li>
            )}
          </ul>
        )}
        <AttackMediaStrip media={attack.media} textCount={attack.texts.length} />
      </div>

      <div className="mt-auto flex flex-wrap items-center justify-end gap-2 border-t border-border/60 px-4 py-3 sm:px-5">
        <Link
          href={`/attacks/${attack.id}`}
          className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'gap-1.5')}
        >
          <ArrowUpRight className="size-3.5" aria-hidden="true" />
          Открыть
        </Link>
        {canCancel && (
          <Button
            variant="danger"
            size="sm"
            onClick={() => setConfirmCancel(true)}
            isLoading={cancelling}
            leftIcon={<Square className="size-3.5" aria-hidden="true" />}
          >
            Отменить
          </Button>
        )}
        {canRepeat && (
          <Button
            variant="default"
            size="sm"
            onClick={onRepeat}
            isLoading={repeating}
            leftIcon={<RotateCcw className="size-3.5" aria-hidden="true" />}
          >
            Повторить
          </Button>
        )}
      </div>

      <ConfirmDialog
        isOpen={confirmCancel}
        onClose={() => setConfirmCancel(false)}
        onConfirm={() => {
          setConfirmCancel(false);
          onCancel?.();
        }}
        title="Отменить атаку?"
        description="Отправки остановятся, а мимики вернутся в обычный режим. Статистика останется в архиве."
        confirmLabel="Отменить атаку"
        variant="danger"
        isLoading={cancelling}
      />
    </Card>
  );
}
