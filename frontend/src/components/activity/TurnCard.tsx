'use client';

import { useState } from 'react';
import { ChevronDown, CornerDownRight, MessageSquarePlus } from 'lucide-react';
import type { ActivityItem } from '@/lib/activity/normalize';
import { ActionRow } from './ActionRow';
import { ActivityDetails } from './ActivityDetails';
import { sanitizeText } from '@/lib/sanitize';
import { cn } from '@/lib/utils';
import { Bot } from 'lucide-react';
import { getEventMeta } from '@/lib/activity/eventCatalog';

/** Extract the human-readable part of the wrapped incoming message prompt. */
function incomingBody(content: string): string {
  const match = content.match(/Содержимое: ([\s\S]*)$/);
  const senderMatch = content.match(/Отправитель: (.*)$/m);
  const body = match?.[1] ?? content;
  const sender = senderMatch?.[1]?.trim() ?? null;
  return sender ? `${body} — ${sender}` : body;
}

export function TurnCard({ item, defaultOpen = false }: { item: ActivityItem; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const time = new Date(item.createdAt).toLocaleTimeString('ru-RU', { hour12: false });
  const peerLabel = item.peerTitle ?? (item.peer ? `ID ${item.peer}` : null);

  // Lifecycle rows (start/stop/timer events) render as a single compact line.
  if (item.kind === 'lifecycle') {
    const action = item.actions[0];
    if (!action) return null;
    const Icon = getEventMeta(action.eventType)?.icon ?? Bot;
    const failed = action.status === 'failed';
    return (
      <div className={cn('flex items-center gap-2.5 px-3 py-2', failed ? 'bg-crimson-950/25' : 'bg-void-900/40')}>
        <span className="font-mono text-[10px] text-void-600 w-16 shrink-0 tabular-nums">{time}</span>
        <Icon className={cn('h-3.5 w-3.5 shrink-0', failed ? 'text-crimson-400' : 'text-plasma-400')} />
        <span className={cn('text-xs font-medium', failed ? 'text-crimson-300' : 'text-void-200')}>
          {action.label}
        </span>
        {action.hint && <span className="text-[11px] text-crimson-400 truncate">{action.hint}</span>}
      </div>
    );
  }

  const hasBody = item.incoming || item.response || item.trigger;

  return (
    <div
      className={cn(
        'border-b border-void-800/70 last:border-b-0',
        item.failed && 'bg-crimson-950/15',
      )}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-3 py-2.5 hover:bg-void-800/30 transition-colors"
      >
        <div className="flex items-center gap-2 mb-1.5">
          <span className="font-mono text-[10px] text-void-600 w-16 shrink-0 tabular-nums">{time}</span>
          {peerLabel && (
            <span className="font-mono text-[10px] text-plasma-400 truncate max-w-[180px]">
              {sanitizeText(peerLabel)}
            </span>
          )}
          {item.actions.some((a) => a.status === 'failed') && (
            <span className="font-mono text-[9px] uppercase text-crimson-500 border border-crimson-900 px-1 rounded-[2px]">
              ошибка
            </span>
          )}
          <ChevronDown
            className={cn('h-3.5 w-3.5 ml-auto text-void-600 transition-transform shrink-0', open && 'rotate-180')}
          />
        </div>

        {item.incoming && (
          <p className="text-xs text-void-100 leading-relaxed line-clamp-2">
            <CornerDownRight className="h-3 w-3 inline mr-1.5 text-plasma-500 -mt-0.5" />
            {sanitizeText(incomingBody(item.incoming.content))}
          </p>
        )}
        {!item.incoming && item.trigger && (
          <p className="text-xs text-void-400 leading-relaxed line-clamp-2 italic">
            {sanitizeText(item.trigger.content)}
          </p>
        )}

        {item.actions.length > 0 && (
          <div className="mt-1.5 space-y-0.5">
            {item.actions.map((action) => (
              <ActionRow key={action.id} action={action} />
            ))}
          </div>
        )}

        {item.response && (
          <p className="mt-1.5 text-xs text-neon-300/90 leading-relaxed line-clamp-2">
            {sanitizeText(item.response.content)}
          </p>
        )}

        {!hasBody && item.actions.length === 0 && (
          <p className="text-xs text-void-600 italic">Пустой ход</p>
        )}
      </button>

      {open && (
        <div className="px-3 pb-3 pt-1 space-y-3 border-t border-void-800/50">
          {item.incoming && (
            <section>
              <h4 className="font-mono text-[10px] text-void-600 uppercase tracking-wider mb-1 flex items-center gap-1.5">
                <MessageSquarePlus className="h-3 w-3" /> Входящее
              </h4>
              <p className="text-xs text-void-300 whitespace-pre-wrap break-words bg-void-900/50 rounded-[2px] p-2">
                {sanitizeText(item.incoming.content)}
              </p>
            </section>
          )}

          {item.actions.length > 0 && (
            <section>
              <h4 className="font-mono text-[10px] text-void-600 uppercase tracking-wider mb-1.5">
                Действия
              </h4>
              {item.actions.map((action) => (
                <div key={`d-${action.id}`}>
                  <ActionRow action={action} />
                  <ActivityDetails action={action} />
                </div>
              ))}
            </section>
          )}

          {item.response && (
            <section>
              <h4 className="font-mono text-[10px] text-void-600 uppercase tracking-wider mb-1">
                Ответ
              </h4>
              <p className="text-xs text-void-200 whitespace-pre-wrap break-words bg-void-900/50 rounded-[2px] p-2">
                {sanitizeText(item.response.content)}
              </p>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
