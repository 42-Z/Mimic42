import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { attackStatusLabel } from '@/lib/attacks/display';
import type { AttackStatus } from '@/types';

function statusClasses(status: AttackStatus): { badge: string; dot: string } {
  switch (status) {
    case 'draft':
      return {
        badge: 'border-border bg-muted/60 text-muted-foreground',
        dot: 'bg-muted-foreground/50',
      };
    case 'running':
      return {
        badge: 'border-success/30 bg-success/10 text-success',
        dot: 'bg-success animate-status-pulse',
      };
    case 'finished':
      return {
        badge: 'border-border bg-muted/50 text-muted-foreground',
        dot: 'bg-muted-foreground/70',
      };
    case 'cancelled':
      return {
        badge: 'border-warning/30 bg-warning/10 text-warning',
        dot: 'bg-warning',
      };
  }
}

export function AttackStatusBadge({
  status,
  className,
}: {
  status: AttackStatus;
  className?: string;
}) {
  const style = statusClasses(status);
  const label = attackStatusLabel(status);

  return (
    <Badge
      variant="outline"
      className={cn('uppercase tracking-widest', style.badge, className)}
      aria-label={`Статус атаки: ${label}`}
    >
      <span className={cn('size-1.5 shrink-0 rounded-full', style.dot)} aria-hidden="true" />
      {label}
    </Badge>
  );
}
