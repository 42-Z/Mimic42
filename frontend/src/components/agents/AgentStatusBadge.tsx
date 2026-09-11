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
    dotClass: 'bg-neon-400 animate-status-pulse',
    textClass: 'text-neon-400',
    bgClass: 'bg-neon-950/50',
    borderClass: 'border-neon-800',
  },
  starting: {
    label: 'ЗАПУСК',
    dotClass: 'bg-plasma-400 animate-pulse',
    textClass: 'text-plasma-400',
    bgClass: 'bg-plasma-950/50',
    borderClass: 'border-plasma-800',
  },
  stopping: {
    label: 'ОСТАНОВКА',
    dotClass: 'bg-amber-400 animate-pulse',
    textClass: 'text-amber-400',
    bgClass: 'bg-amber-950/50',
    borderClass: 'border-amber-800',
  },
  stopped: {
    label: 'ОСТАНОВЛЕН',
    dotClass: 'bg-void-500',
    textClass: 'text-void-400',
    bgClass: 'bg-void-800/50',
    borderClass: 'border-void-700',
  },
  draft: {
    label: 'ЧЕРНОВИК',
    dotClass: 'bg-void-500',
    textClass: 'text-void-400',
    bgClass: 'bg-void-800/50',
    borderClass: 'border-void-700',
  },
  error: {
    label: 'ОШИБКА',
    dotClass: 'bg-crimson-400 animate-pulse',
    textClass: 'text-crimson-400',
    bgClass: 'bg-crimson-950/50',
    borderClass: 'border-crimson-800',
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
        'inline-flex items-center rounded-[2px] border font-mono font-medium',
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
