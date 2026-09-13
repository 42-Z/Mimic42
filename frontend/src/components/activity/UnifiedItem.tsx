'use client';

import { useMemo, useState } from 'react';
import {
  ChevronDown,
  CornerDownRight,
  Bot,
  AlertTriangle,
} from 'lucide-react';
import type { ActivityItem } from '@/lib/activity/normalize';
import { incomingBody, countActions } from '@/lib/activity/normalize';
import { ActionRow } from './ActionRow';
import { sanitizeText } from '@/lib/sanitize';
import { cn } from '@/lib/utils';
import { getEventMeta } from '@/lib/activity/eventCatalog';

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('ru-RU', { hour12: false });
}

function LifecycleRow({ item }: { item: ActivityItem }) {
  const action = item.actions[0];
  if (!action) return null;
  const Icon = getEventMeta(action.eventType)?.icon ?? Bot;
  const failed = action.status === 'failed';
  return (
    <div
      className={cn(
        'flex items-center gap-2.5 px-3 py-2',
        failed ? 'bg-crimson-950/25' : 'bg-void-900/40',
      )}
    >
      <span className="font-mono text-[10px] text-void-600 w-16 shrink-0 tabular-nums">
        {formatTime(item.createdAt)}
      </span>
      <Icon
        className={cn(
          'h-3.5 w-3.5 shrink-0',
          failed ? 'text-crimson-400' : 'text-plasma-400',
        )}
      />
      <span
        className={cn(
          'text-xs font-medium',
          failed ? 'text-crimson-300' : 'text-void-200',
        )}
      >
        {action.label}
      </span>
      {action.hint && (
        <span className="text-[11px] text-crimson-400 truncate">
          {action.hint}
        </span>
      )}
    </div>
  );
}

function TurnBlock({
  item,
  showTools,
}: {
  item: ActivityItem;
  showTools: boolean;
}) {
  const [open, setOpen] = useState(false);
  const time = formatTime(item.createdAt);
  const peerLabel = item.peerTitle ?? (item.peer ? `ID ${item.peer}` : null);
  const toolCount = countActions(item);

  // P2 #6: memoize body to avoid recomputing incomingBody() on every render.
  // Must be before conditional return to satisfy rules-of-hooks.
  const body = useMemo(
    () =>
      item.incoming
        ? incomingBody(item.incoming.content)
        : item.trigger
          ? incomingBody(item.trigger.content)
          : '',
    [item.incoming, item.trigger],
  );

  const hasContent =
    Boolean(item.incoming || item.trigger || item.response) ||
    (showTools && toolCount > 0);

  if (!hasContent) return null;

  return (
    <div
      className={cn(
        'border-b border-void-800/60 transition-colors',
        item.failed && 'bg-crimson-950/10',
        open ? 'bg-void-900/20' : 'hover:bg-void-900/20',
      )}
    >
      {/* Header — always visible */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2.5 w-full px-3 py-2.5 text-left select-none"
      >
        <span className="font-mono text-[10px] text-void-600 w-16 shrink-0 tabular-nums">
          {time}
        </span>

        {/* Peer */}
        {peerLabel && (
          <span className="font-mono text-[11px] text-void-400 shrink-0 max-w-[140px] truncate">
            {peerLabel}
          </span>
        )}

        {/* Error badge */}
        {item.failed && (
          <AlertTriangle className="h-3 w-3 text-crimson-400 shrink-0" />
        )}

        {/* Incoming preview */}
        {body && (
          <span className="flex-1 min-w-0 truncate text-xs text-void-300">
            <CornerDownRight className="inline h-3 w-3 text-void-500 mr-1 -mt-0.5" />
            {body}
          </span>
        )}

        {/* Tool count badge */}
        {showTools && toolCount > 0 && (
          <span className="shrink-0 font-mono text-[10px] px-1.5 py-0.5 rounded bg-amber-950/60 text-amber-400 border border-amber-900/40">
            {toolCount} tools
          </span>
        )}

        {/* Response indicator */}
        {item.response && (
          <Bot className="h-3.5 w-3.5 text-neon-400 shrink-0" />
        )}

        {/* Expand chevron */}
        <ChevronDown
          className={cn(
            'h-3.5 w-3.5 text-void-500 shrink-0 transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>

      {/* Expanded content */}
      {open && (
        <div className="px-3 pb-3 space-y-2.5">
          {/* Incoming message (full) */}
          {(item.incoming || item.trigger) && (
            <div className="rounded-[2px] bg-void-800/30 border border-void-800 p-3">
              <p className="font-mono text-[10px] text-void-500 uppercase tracking-wider mb-1.5">
                {item.trigger ? 'Триггер' : 'Входящее'}
              </p>
              <p className="text-sm text-void-200 whitespace-pre-wrap break-words leading-relaxed">
                {sanitizeText(
                  item.trigger ? item.trigger.content : item.incoming!.content,
                )}
              </p>
            </div>
          )}

          {/* Tool calls */}
          {showTools && item.actions.length > 0 && (
            <div className="rounded-[2px] bg-void-800/20 border border-void-800/60 divide-y divide-void-800/40">
              <p className="font-mono text-[10px] text-void-500 uppercase tracking-wider px-3 pt-2 pb-1">
                Действия ({item.actions.length})
              </p>
              {item.actions.map((action) => (
                <ActionRow key={action.id} action={action} />
              ))}
            </div>
          )}

          {/* Agent response */}
          {item.response && (
            <div className="rounded-[2px] bg-neon-950/20 border border-neon-900/30 p-3">
              <p className="font-mono text-[10px] text-neon-500 uppercase tracking-wider mb-1.5">
                Ответ
              </p>
              <p className="text-sm text-void-100 whitespace-pre-wrap break-words leading-relaxed">
                {sanitizeText(item.response.content)}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function UnifiedItem({
  item,
  showTools,
}: {
  item: ActivityItem;
  showTools: boolean;
}) {
  if (item.kind === 'lifecycle') {
    return <LifecycleRow item={item} />;
  }
  return <TurnBlock item={item} showTools={showTools} />;
}
