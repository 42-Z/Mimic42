import Link from 'next/link';
import { Play, Square, Link2 } from 'lucide-react';
import { Button, buttonVariants } from '@/components/ui/button';
import type { AgentState } from '@/types';

// ── Agent Toggle Button ───────────────────────────────────────────────────────
// Одна кнопка управления агентом вместо пары «Запустить»/«Стоп»: её подпись,
// цвет и действие определяются текущим статусом рантайма.

export interface AgentToggleButtonProps {
  agentId: string;
  state?: AgentState;
  /** Telegram-сессия отозвана — управление запуском бессмысленно до перепривязки. */
  needsRebind?: boolean;
  onStart: () => void;
  onStop: () => void;
  isStarting?: boolean;
  isStopping?: boolean;
  size?: 'sm' | 'md';
  className?: string;
}

export function AgentToggleButton({
  agentId,
  state,
  needsRebind = false,
  onStart,
  onStop,
  isStarting = false,
  isStopping = false,
  size = 'sm',
  className,
}: AgentToggleButtonProps) {
  if (needsRebind) {
    return (
      <Link
        href={`/agent/${agentId}/rebind`}
        aria-label="Перепривязать Telegram"
        className={buttonVariants({ variant: 'outline', size, className })}
      >
        <Link2 className="h-3.5 w-3.5" />
        Перепривязать
      </Link>
    );
  }

  if (state === 'running') {
    return (
      <Button
        variant="danger"
        size={size}
        onClick={onStop}
        disabled={isStopping}
        isLoading={isStopping}
        leftIcon={<Square className="h-3.5 w-3.5" />}
        className={className}
      >
        Остановить
      </Button>
    );
  }

  if (state === 'starting') {
    return (
      <Button variant="success" size={size} disabled isLoading leftIcon={<Play className="h-3.5 w-3.5" />} className={className}>
        Запускается…
      </Button>
    );
  }

  if (state === 'stopping') {
    return (
      <Button variant="secondary" size={size} disabled isLoading leftIcon={<Square className="h-3.5 w-3.5" />} className={className}>
        Останавливается…
      </Button>
    );
  }

  return (
    <Button
      variant="success"
      size={size}
      onClick={onStart}
      disabled={state === undefined || isStarting}
      isLoading={isStarting}
      leftIcon={<Play className="h-3.5 w-3.5" />}
      className={className}
    >
      Запустить
    </Button>
  );
}
