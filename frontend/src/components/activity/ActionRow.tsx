'use client';

import { CheckCircle2, XCircle, Loader2 } from 'lucide-react';
import { getToolMeta } from '@/lib/activity/toolCatalog';
import { getEventMeta } from '@/lib/activity/eventCatalog';
import { describeError } from '@/lib/activity/errorCatalog';
import type { ActivityAction } from '@/lib/activity/normalize';
import { cn } from '@/lib/utils';

function formatDuration(startedAt: string | null, completedAt: string | null): string | null {
  if (!startedAt || !completedAt) return null;
  const ms = new Date(completedAt).getTime() - new Date(startedAt).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  if (ms < 1000) return `${ms} мс`;
  return `${(ms / 1000).toFixed(1)} с`;
}

export function ActionRow({ action }: { action: ActivityAction }) {
  const isTool = action.eventType.startsWith('tool.');
  const meta = isTool
    ? getToolMeta(action.eventType.slice('tool.'.length))
    : getEventMeta(action.eventType);
  const Icon = meta?.icon ?? null;
  const failed = action.status === 'failed';
  const running = action.status === 'running' || action.status === 'pending';
  const duration = formatDuration(action.startedAt, action.completedAt);
  const resultSummary = summarizeResult(action.result);

  return (
    <div
      className={cn(
        'flex items-center gap-2.5 py-1.5 px-2 rounded-[2px]',
        failed ? 'bg-crimson-950/25' : 'hover:bg-void-800/40',
      )}
    >
      {Icon && (
        <Icon
          className={cn('h-3.5 w-3.5 shrink-0', failed ? 'text-crimson-400' : 'text-void-400')}
        />
      )}
      <span className={cn('flex-1 min-w-0 truncate text-xs', failed ? 'text-crimson-300' : 'text-void-300')}>
        {action.label}
      </span>
      {action.hint && (
        <span className="hidden md:inline text-[11px] text-crimson-400 truncate max-w-[45%]">
          {action.hint}
        </span>
      )}
      {!failed && !running && !action.hint && isTool && resultSummary && (
        <span className="hidden md:inline text-[11px] text-void-600 truncate max-w-[40%]">
          {resultSummary}
        </span>
      )}
      {duration && <span className="shrink-0 font-mono text-[10px] text-void-600">{duration}</span>}
      {failed ? (
        <XCircle className="h-3.5 w-3.5 shrink-0 text-crimson-500" />
      ) : running ? (
        <Loader2 className="h-3.5 w-3.5 shrink-0 text-plasma-500 animate-spin" />
      ) : (
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-neon-700" />
      )}
    </div>
  );
}

function summarizeResult(result: Record<string, unknown> | null | undefined): string | null {
  if (!result) return null;
  const text = result.text ?? result.content ?? result.title ?? result.description;
  if (typeof text === 'string' && text.trim()) return text;
  if (result.success === true) return 'готово';
  return null;
}
