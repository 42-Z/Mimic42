import { AlertTriangle } from 'lucide-react';

import { Card } from '@/components/ui/card';
import { exitReasonLabel } from '@/lib/attacks/display';
import type { AttackAgent } from '@/types';

export function AttackErrors({ agents }: { agents: AttackAgent[] }) {
  const failed = agents.filter((agent) => Boolean(agent.last_error));
  if (failed.length === 0) return null;

  return (
    <Card
      variant="bordered"
      padding="md"
      className="flex flex-col gap-3 border-crimson-950/50 bg-crimson-950/10"
      aria-labelledby="attack-errors-title"
    >
      <div className="flex items-center gap-2">
        <AlertTriangle className="size-4 text-crimson-400" aria-hidden="true" />
        <h2
          id="attack-errors-title"
          className="font-mono text-xs font-semibold uppercase tracking-wider text-crimson-200"
        >
          Ошибки мимиков
        </h2>
      </div>
      <ul className="flex flex-col gap-2">
        {failed.map((agent) => {
          const reason = agent.status === 'exited' ? exitReasonLabel(agent.exit_reason) : null;
          return (
            <li
              key={agent.id}
              className="rounded-sm border border-crimson-900/40 bg-background/30 p-3"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-mono text-sm text-foreground">{agent.name}</span>
                {reason && (
                  <span className="font-mono text-[10px] uppercase tracking-wider text-crimson-300">
                    {reason}
                  </span>
                )}
              </div>
              <p className="mt-1 font-mono text-xs leading-relaxed text-crimson-200/90 [overflow-wrap:anywhere]">
                {agent.last_error}
              </p>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
