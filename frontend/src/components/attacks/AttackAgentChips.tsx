import { AlertTriangle, MessageSquare, X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Spinner } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { attackAgentStatusLabel } from '@/lib/attacks/display';
import type { AttackAgent } from '@/types';

function statusClasses(status: AttackAgent['status']): string {
  switch (status) {
    case 'active':
      return 'border-success/30 bg-success/10 text-foreground';
    case 'assigned':
      return 'border-primary/30 bg-primary/10 text-foreground';
    case 'exited':
      return 'border-border/70 bg-muted/40 text-muted-foreground';
  }
}

function dotClasses(status: AttackAgent['status']): string {
  switch (status) {
    case 'active':
      return 'bg-success animate-status-pulse';
    case 'assigned':
      return 'bg-primary';
    case 'exited':
      return 'bg-muted-foreground/50';
  }
}

export function AttackAgentChips({
  agents,
  onRemove,
  removingId,
  className,
}: {
  agents: AttackAgent[];
  onRemove?: (agent: AttackAgent) => void;
  removingId?: string | null;
  className?: string;
}) {
  if (agents.length === 0) return null;

  return (
    <div className={cn('flex flex-wrap gap-1.5', className)} aria-label="Мимики в атаке">
      {agents.map((agent) => {
        const statusLabel = attackAgentStatusLabel(agent);

        return (
          <Badge
            key={agent.id}
            variant="outline"
            className={cn(
              'max-w-full flex-wrap py-1',
              statusClasses(agent.status),
              agent.last_error && 'border-crimson-800/60 bg-crimson-950/25',
            )}
            title={`${agent.name}: ${statusLabel}`}
          >
            <span
              className={cn('size-1.5 shrink-0 rounded-full', dotClasses(agent.status))}
              aria-hidden="true"
            />
            <span className="max-w-[9rem] truncate">{agent.name}</span>
            <span
              className="inline-flex items-center gap-0.5 tabular-nums text-muted-foreground"
              title="Отправлено комментариев"
            >
              <MessageSquare aria-hidden="true" />
              {agent.sent_count}
            </span>
            {agent.last_error && (
              <span
                role="img"
                className="inline-flex"
                title={agent.last_error}
                aria-label={`Ошибка: ${agent.last_error}`}
              >
                <AlertTriangle className="size-3 text-crimson-400" aria-hidden="true" />
              </span>
            )}
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
              {statusLabel}
            </span>
            {onRemove && agent.status !== 'exited' && (
              <button
                type="button"
                onClick={() => onRemove(agent)}
                disabled={removingId === agent.agent_id}
                aria-label={`Убрать мимика ${agent.name}`}
                className={cn(
                  'ml-0.5 flex size-5 shrink-0 items-center justify-center rounded-sm text-muted-foreground transition-colors',
                  'hover:bg-destructive/10 hover:text-destructive',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                  'disabled:cursor-wait disabled:opacity-50',
                )}
              >
                {removingId === agent.agent_id ? <Spinner size="xs" /> : <X className="size-3" />}
              </button>
            )}
          </Badge>
        );
      })}
    </div>
  );
}
