import * as React from 'react';
import { cn } from '@/lib/utils';
import type { AgentState } from '@/types';

interface AgentStatusBadgeProps {
  state: AgentState;
  showLabel?: boolean;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const stateConfig: Record<
  AgentState,
  { label: string; dotClass: string; textClass: string; bgClass: string; borderClass: string }
> = {
  running: {
    label: 'АКТИВЕН',
    dotClass: 'bg-success animate-status-pulse',
    textClass: 'text-success',
    bgClass: 'bg-success/10',
    borderClass: 'border-success/30',
  },
  starting: {
    label: 'ЗАПУСК',
    dotClass: 'bg-primary animate-pulse',
    textClass: 'text-primary',
    bgClass: 'bg-primary/10',
    borderClass: 'border-primary/30',
  },
  stopping: {
    label: 'ОСТАНОВКА',
    dotClass: 'bg-warning animate-pulse',
    textClass: 'text-warning',
    bgClass: 'bg-warning/10',
    borderClass: 'border-warning/30',
  },
  stopped: {
    label: 'ОСТАНОВЛЕН',
    dotClass: 'bg-muted-foreground/50',
    textClass: 'text-muted-foreground',
    bgClass: 'bg-muted',
    borderClass: 'border-border',
  },
  draft: {
    label: 'ЧЕРНОВИК',
    dotClass: 'bg-muted-foreground/50',
    textClass: 'text-muted-foreground',
    bgClass: 'bg-muted',
    borderClass: 'border-border',
  },
  error: {
    label: 'ОШИБКА',
    dotClass: 'bg-destructive animate-pulse',
    textClass: 'text-destructive',
    bgClass: 'bg-destructive/10',
    borderClass: 'border-destructive/30',
  },
};

const sizes = {
  sm: { dot: 'h-1.5 w-1.5', text: 'text-[10px]', padding: 'px-2 py-0.5', gap: 'gap-1.5' },
  md: { dot: 'h-2 w-2', text: 'text-xs', padding: 'px-2.5 py-1', gap: 'gap-2' },
  lg: { dot: 'h-2.5 w-2.5', text: 'text-sm', padding: 'px-3 py-1.5', gap: 'gap-2' },
};

export function AgentStatusBadge({
  state,
  showLabel = true,
  size = 'md',
  className,
}: AgentStatusBadgeProps) {
  // eslint-disable-next-line security/detect-object-injection -- key is typed AgentState union, not user input
  const config = stateConfig[state];
  // eslint-disable-next-line security/detect-object-injection -- key is typed size union, not user input
  const sizeConfig = sizes[size];

  return (
    <span
      className={cn(
        'inline-flex items-center rounded-sm border font-mono font-medium',
        sizeConfig.padding,
        sizeConfig.gap,
        config.bgClass,
        config.borderClass,
        config.textClass,
        className
      )}
      aria-label={`Статус агента: ${config.label}`}
    >
      <span
        className={cn('rounded-full shrink-0', sizeConfig.dot, config.dotClass)}
        aria-hidden="true"
      />
      {showLabel && (
        <span className={cn('uppercase tracking-widest', sizeConfig.text)}>
          {config.label}
        </span>
      )}
    </span>
  );
}

/**
 * Dot-only indicator for compact contexts.
 */
export function StatusDot({ state, className }: { state: AgentState; className?: string }) {
  // eslint-disable-next-line security/detect-object-injection -- key is typed AgentState union, not user input
  const config = stateConfig[state];

  return (
    <span
      className={cn('inline-block rounded-full h-2 w-2 shrink-0', config.dotClass, className)}
      aria-label={config.label}
      title={config.label}
    />
  );
}
