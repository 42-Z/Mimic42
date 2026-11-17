'use client';

import { AlertTriangle, Bot, Check, Plus } from 'lucide-react';

import { Spinner } from '@/components/ui/card';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { cn } from '@/lib/utils';
import { mimicAvailability } from '@/lib/attacks/availability';
import { AgentStatusBadge } from '@/components/agents/AgentStatusBadge';
import type { AttackAgentAvailability } from '@/types';

export function AttackMimicPicker({
  agents,
  value,
  onChange,
  currentAttackId,
  isLoading = false,
  error,
}: {
  agents: AttackAgentAvailability[];
  value: string[];
  onChange: (agentIds: string[]) => void;
  currentAttackId?: string | null;
  isLoading?: boolean;
  error?: string;
}) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-sm border border-border bg-muted/30 p-3 font-mono text-xs text-muted-foreground">
        <Spinner size="sm" />
        Загружаем мимиков…
      </div>
    );
  }

  if (agents.length === 0) {
    return (
      <p className="rounded-sm border border-dashed border-border p-3 font-mono text-xs text-muted-foreground">
        Нет доступных мимиков. Создайте агента, чтобы назначить его в атаку.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <ToggleGroup
        type="multiple"
        value={value}
        onValueChange={onChange}
        variant="outline"
        aria-label="Мимики для атаки"
        className="flex w-full flex-col items-stretch gap-2"
      >
        {agents.map((agent) => {
          const availability = mimicAvailability(agent, currentAttackId);
          const selected = value.includes(agent.agent_id);

          return (
            <ToggleGroupItem
              key={agent.agent_id}
              value={agent.agent_id}
              disabled={availability.disabled}
              className={cn(
                'h-auto w-full justify-start gap-3 whitespace-normal px-3 py-2 text-left',
                selected && 'border-primary/50 bg-primary/10',
                availability.disabled && 'cursor-not-allowed opacity-50',
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
                {availability.note && (
                  <span
                    className={cn(
                      'mt-1 block font-mono text-[11px] leading-snug',
                      availability.tone === 'disabled'
                        ? 'text-crimson-400'
                        : 'text-warning',
                    )}
                  >
                    {availability.note}
                  </span>
                )}
              </span>
              {selected ? (
                <Check className="size-4 shrink-0 text-primary" aria-hidden="true" />
              ) : availability.tone === 'warning' ? (
                <AlertTriangle className="size-4 shrink-0 text-warning" aria-hidden="true" />
              ) : (
                <Plus className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              )}
            </ToggleGroupItem>
          );
        })}
      </ToggleGroup>
      <p className="font-mono text-[11px] text-muted-foreground">
        Остановленные мимики запустятся вместе с атакой. Мимик может быть только в одной атаке —
        при добавлении он переносится из прежней.
      </p>
      {error && <p className="font-mono text-xs text-crimson-400">{error}</p>}
    </div>
  );
}
