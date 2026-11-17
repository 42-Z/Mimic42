import { cn } from '@/lib/utils';
import { attackProgress } from '@/lib/attacks/display';
import type { AttackSummary } from '@/types';

function barClasses(status: AttackSummary['status']): string {
  switch (status) {
    case 'draft':
      return 'bg-muted-foreground/40';
    case 'running':
      return 'bg-gradient-to-r from-primary to-plasma-300 shadow-plasma-sm';
    case 'finished':
      return 'bg-success';
    case 'cancelled':
      return 'bg-warning';
  }
}

export function AttackProgress({
  attack,
  className,
}: {
  attack: AttackSummary;
  className?: string;
}) {
  const progress = attackProgress(attack);

  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex items-baseline justify-between gap-3 font-mono">
        <span className="text-sm font-medium text-foreground">{progress.label}</span>
        <span className="text-xs tabular-nums text-muted-foreground">{progress.value}%</span>
      </div>
      <div
        role="progressbar"
        aria-label="Прогресс атаки"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress.value}
        aria-valuetext={progress.label}
        className="h-1.5 w-full overflow-hidden rounded-full border border-border/60 bg-muted"
      >
        <div
          className={cn('h-full rounded-full transition-[width] duration-500', barClasses(attack.status))}
          style={{ width: `${progress.value}%` }}
        />
      </div>
      <p className="font-mono text-[11px] text-muted-foreground">{progress.detail}</p>
    </div>
  );
}
