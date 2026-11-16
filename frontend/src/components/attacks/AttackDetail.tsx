'use client';

import { useState } from 'react';
import {
  Ban,
  Bot,
  ExternalLink,
  Pencil,
  Play,
  Plus,
  RotateCcw,
  Square,
  UserPlus,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, Spinner } from '@/components/ui/card';
import { ConfirmDialog, Modal } from '@/components/ui/modal';
import { AgentStatusBadge } from '@/components/agents/AgentStatusBadge';
import { cn } from '@/lib/utils';
import {
  attackLimitLabel,
  attackTitle,
  isArchiveStatus,
  isEditableStatus,
  targetHref,
} from '@/lib/attacks/display';
import { mimicAvailability } from '@/lib/attacks/availability';
import { AttackAgentChips } from './AttackAgentChips';
import { AttackErrors } from './AttackErrors';
import { AttackMediaStrip } from './AttackMediaStrip';
import { AttackProgress } from './AttackProgress';
import { AttackStats } from './AttackStats';
import { AttackStatusBadge } from './AttackStatusBadge';
import type {
  AttackAgent,
  AttackAgentAvailability,
  AttackDetail as AttackDetailData,
} from '@/types';

export interface AttackDetailProps {
  attack: AttackDetailData;
  availableAgents: AttackAgentAvailability[];
  agentsLoading?: boolean;
  pendingAction?: 'start' | 'cancel' | 'repeat' | null;
  addingAgentId?: string | null;
  removingAgentId?: string | null;
  onStart: () => void;
  onCancel: () => void;
  onRepeat: () => void;
  onEdit: () => void;
  onAddAgent: (agentId: string) => void;
  onRemoveAgent: (agent: AttackAgent) => void;
}

export function AttackDetail({
  attack,
  availableAgents,
  agentsLoading = false,
  pendingAction = null,
  addingAgentId = null,
  removingAgentId = null,
  onStart,
  onCancel,
  onRepeat,
  onEdit,
  onAddAgent,
  onRemoveAgent,
}: AttackDetailProps) {
  const [cancelOpen, setCancelOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<AttackAgent | null>(null);

  const roster = attack.agents.filter((agent) => agent.status !== 'exited');
  const canStart = roster.length > 0;

  const requestRemove = (agent: AttackAgent) => {
    const lastOfRunning =
      attack.status === 'running' &&
      roster.length === 1 &&
      roster[0]?.agent_id === agent.agent_id;
    if (lastOfRunning) {
      setRemoveTarget(agent);
      return;
    }
    onRemoveAgent(agent);
  };

  return (
    <div className="flex flex-col gap-4">
      <Card
        variant="glass"
        padding="md"
        className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between"
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <AttackStatusBadge status={attack.status} />
            <Badge variant="outline">
              {attackLimitLabel(attack.limit_kind, attack.limit_value)}
            </Badge>
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              #{attack.id.slice(0, 8)}
            </span>
          </div>
          <h1 className="mt-2 font-display text-2xl font-bold text-foreground">
            {attackTitle(attack)}
          </h1>
          <a
            href={targetHref(attack.target_link)}
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-flex max-w-full items-center gap-1.5 rounded-sm font-mono text-xs text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            <ExternalLink className="size-3.5 shrink-0" aria-hidden="true" />
            <span className="truncate">{attack.target_link}</span>
          </a>
        </div>

        <div className="flex flex-col gap-2 sm:items-end">
          <div className="flex flex-wrap gap-2">
            {attack.status === 'draft' && (
              <Button
                onClick={onStart}
                disabled={!canStart}
                isLoading={pendingAction === 'start'}
                title={canStart ? undefined : 'Добавьте хотя бы одного мимика'}
                leftIcon={<Play className="size-3.5" aria-hidden="true" />}
              >
                Запустить
              </Button>
            )}
            {isEditableStatus(attack.status) && (
              <Button
                variant="outline"
                onClick={onEdit}
                leftIcon={<Pencil className="size-3.5" aria-hidden="true" />}
              >
                Редактировать
              </Button>
            )}
            {attack.status === 'running' && (
              <Button
                variant="danger"
                onClick={() => setCancelOpen(true)}
                isLoading={pendingAction === 'cancel'}
                leftIcon={<Square className="size-3.5" aria-hidden="true" />}
              >
                Отменить
              </Button>
            )}
            {isArchiveStatus(attack.status) && (
              <Button
                onClick={onRepeat}
                isLoading={pendingAction === 'repeat'}
                leftIcon={<RotateCcw className="size-3.5" aria-hidden="true" />}
              >
                Повторить
              </Button>
            )}
          </div>
          {attack.status === 'draft' && !canStart && (
            <p className="font-mono text-[11px] text-warning">
              Добавьте мимика, чтобы запустить атаку.
            </p>
          )}
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="flex min-w-0 flex-col gap-4">
          <Card variant="glass" padding="md" className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-2">
              <h2 className="font-mono text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Прогресс
              </h2>
              <span className="font-mono text-[10px] text-muted-foreground">
                {attackLimitLabel(attack.limit_kind, attack.limit_value)}
              </span>
            </div>
            <AttackProgress attack={attack} />
          </Card>

          <Card variant="glass" padding="md" className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="font-mono text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Тексты
              </h2>
              <Badge variant="outline">{attack.texts.length}</Badge>
            </div>
            {attack.texts.length === 0 ? (
              <p className="font-mono text-xs text-muted-foreground">Текстов нет.</p>
            ) : (
              <div className="flex flex-col gap-2">
                {attack.texts.map((text, index) => (
                  <div
                    key={index}
                    className="rounded-sm border border-border/70 bg-background/30 p-3"
                  >
                    <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                      Текст {index + 1}
                    </span>
                    <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-foreground/90 [overflow-wrap:anywhere]">
                      {text}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card variant="glass" padding="md" className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="font-mono text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Картинки
              </h2>
              <Badge variant="outline">{attack.media.length}</Badge>
            </div>
            {attack.media.length > 0 ? (
              <AttackMediaStrip
                media={attack.media}
                size="lg"
                max={attack.media.length}
              />
            ) : (
              <p className="font-mono text-xs text-muted-foreground">
                Картинок нет — комментарии уйдут одним текстом.
              </p>
            )}
          </Card>

          <AttackErrors agents={attack.agents} />
        </div>

        <div className="flex flex-col gap-4">
          <Card variant="glass" padding="md" className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-2">
              <h2 className="font-mono text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Мимики
              </h2>
              <Badge variant="outline">{roster.length}</Badge>
            </div>
            <AttackAgentChips
              agents={attack.agents}
              onRemove={requestRemove}
              removingId={removingAgentId}
            />
            {attack.agents.length === 0 && (
              <p className="rounded-sm border border-dashed border-border p-3 font-mono text-xs text-muted-foreground">
                В атаке пока никого нет. Добавьте мимика — он начнёт участвовать сразу.
              </p>
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setAddOpen(true)}
              leftIcon={<UserPlus className="size-3.5" aria-hidden="true" />}
            >
              Добавить мимика
            </Button>
          </Card>

          <Card variant="glass" padding="md" className="flex flex-col gap-3">
            <h2 className="font-mono text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Параметры
            </h2>
            <AttackStats attack={attack} />
          </Card>
        </div>
      </div>

      <Modal
        isOpen={addOpen}
        onClose={() => setAddOpen(false)}
        title="Добавить мимика"
        description="Участие начинается сразу, без отдельного подтверждения."
        size="lg"
      >
        {agentsLoading ? (
          <div className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
            <Spinner size="sm" />
            Загружаем мимиков…
          </div>
        ) : availableAgents.length === 0 ? (
          <p className="rounded-sm border border-dashed border-border p-4 text-center font-mono text-xs text-muted-foreground">
            Все доступные мимики уже в атаке.
          </p>
        ) : (
          <ul className="flex max-h-[26rem] flex-col gap-2 overflow-y-auto pr-1">
            {availableAgents.map((agent) => {
              const availability = mimicAvailability(agent, attack.id);
              const adding = addingAgentId === agent.agent_id;

              return (
                <li key={agent.agent_id}>
                  <button
                    type="button"
                    disabled={availability.disabled || adding}
                    onClick={() => onAddAgent(agent.agent_id)}
                    className={cn(
                      'flex w-full items-center gap-3 rounded-sm border border-border bg-background/40 p-3 text-left transition-colors',
                      'hover:border-primary/40 hover:bg-primary/5',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                      availability.disabled &&
                        'cursor-not-allowed opacity-50 hover:border-border hover:bg-background/40',
                    )}
                  >
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-sm border border-border bg-muted">
                      <Bot className="size-4 text-primary" aria-hidden="true" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-sm text-foreground">{agent.name}</span>
                        <AgentStatusBadge state={agent.state} size="sm" />
                      </span>
                      <span
                        className={cn(
                          'mt-1 block font-mono text-[11px] leading-snug',
                          availability.tone === 'disabled'
                            ? 'text-crimson-400'
                            : availability.tone === 'warning'
                              ? 'text-warning'
                              : 'text-muted-foreground',
                        )}
                      >
                        {availability.note ?? 'Готов к работе'}
                      </span>
                    </span>
                    {adding ? (
                      <Spinner size="sm" />
                    ) : availability.disabled ? (
                      <Ban className="size-4 shrink-0 text-crimson-400" aria-hidden="true" />
                    ) : (
                      <Plus className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Modal>

      <ConfirmDialog
        isOpen={removeTarget !== null}
        onClose={() => setRemoveTarget(null)}
        onConfirm={() => {
          const target = removeTarget;
          setRemoveTarget(null);
          if (target) onRemoveAgent(target);
        }}
        title="Убрать последнего мимика?"
        description="Это последний мимик в идущей атаке. Атака отменится, потому что в ней не останется участников."
        confirmLabel="Убрать"
        variant="danger"
        isLoading={removeTarget ? removingAgentId === removeTarget.agent_id : false}
      />

      <ConfirmDialog
        isOpen={cancelOpen}
        onClose={() => setCancelOpen(false)}
        onConfirm={() => {
          setCancelOpen(false);
          onCancel();
        }}
        title="Отменить атаку?"
        description="Отправки остановятся, а мимики вернутся в обычный режим. Статистика сохранится в архиве."
        confirmLabel="Отменить атаку"
        variant="danger"
        isLoading={pendingAction === 'cancel'}
      />
    </div>
  );
}
