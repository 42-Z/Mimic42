'use client';

import { useState } from 'react';
import {
  Bot,
  ChevronDown,
  Clock,
  MessageSquarePlus,
  MessagesSquare,
  UserRound,
  type LucideIcon,
} from 'lucide-react';
import type { ActivityItem, ActivityMessagePart } from '@/lib/activity/normalize';
import { incomingBody } from '@/lib/activity/normalize';
import { ActionRow } from './ActionRow';
import { ActivityDetails } from './ActivityDetails';
import { MediaContent } from './MediaContent';
import { sanitizeText } from '@/lib/sanitize';
import { cn } from '@/lib/utils';
import { getEventMeta } from '@/lib/activity/eventCatalog';

const MESSAGE_ICON_BOX = 'mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-[3px] border';
const MESSAGE_META = 'font-mono text-[10px] uppercase tracking-[0.12em]';

type MessageTone = 'agent' | 'peer' | 'trigger';

const TONES: Record<
  MessageTone,
  { box: string; icon: string; name: string; tag: string; text: string }
> = {
  agent: {
    box: 'border-neon-900/80 bg-neon-950/40',
    icon: 'text-neon-400',
    name: 'text-neon-400',
    tag: 'text-neon-800',
    text: 'text-neon-100/85',
  },
  peer: {
    box: 'border-plasma-900/80 bg-plasma-950/40',
    icon: 'text-plasma-400',
    name: 'text-plasma-400',
    tag: 'text-plasma-900',
    text: 'text-void-100',
  },
  trigger: {
    box: 'border-void-800 bg-void-900/50',
    icon: 'text-void-500',
    name: 'text-void-500',
    tag: 'text-void-700',
    text: 'text-void-400 italic',
  },
};

function MessageRow({
  icon: Icon,
  tone,
  name,
  tag,
  text,
  clamp,
}: {
  icon: LucideIcon;
  tone: MessageTone;
  name: string;
  tag: string;
  text: string;
  clamp: boolean;
}) {
  const styles = TONES[tone];
  return (
    <div className="flex gap-2.5">
      <span className={cn(MESSAGE_ICON_BOX, styles.box)}>
        <Icon className={cn('h-3 w-3', styles.icon)} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-1.5">
          <span className={cn(MESSAGE_META, 'truncate', styles.name)}>{sanitizeText(name)}</span>
          <span className={cn(MESSAGE_META, 'shrink-0 text-[9px]', styles.tag)}>{tag}</span>
        </div>
        <p
          className={cn(
            'mt-0.5 text-xs leading-relaxed whitespace-pre-wrap break-words',
            styles.text,
            clamp && 'line-clamp-2',
          )}
        >
          {sanitizeText(text)}
        </p>
      </div>
    </div>
  );
}

export function TurnCard({
  item,
  defaultOpen = false,
  chatOnly = false,
  agentName,
}: {
  item: ActivityItem;
  defaultOpen?: boolean;
  chatOnly?: boolean;
  agentName?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const time = new Date(item.createdAt).toLocaleTimeString('ru-RU', { hour12: false });
  const chatLabel = item.peerTitle ?? null;
  const senderLabel = item.peerTitle?.split(' (')[0]?.trim() || null;
  const agentLabel = agentName?.trim() || 'агент';
  const hasBody = item.incoming || item.response || item.trigger;

  const renderMessage = (
    icon: LucideIcon,
    tone: MessageTone,
    name: string,
    tag: string,
    part: ActivityMessagePart,
    content: string,
    clamp: boolean,
  ) => (
    <>
      <MessageRow icon={icon} tone={tone} name={name} tag={tag} text={content} clamp={clamp} />
      {part.media && part.media.length > 0 && item.agentId && (
        <div className="mt-1.5 pl-[30px]">
          <MediaContent agentId={item.agentId} items={part.media} />
        </div>
      )}
    </>
  );

  // Lifecycle rows (start/stop/timer events) render as a single compact line.
  if (item.kind === 'lifecycle') {
    const action = item.actions[0];
    if (!action) return null;
    const Icon = getEventMeta(action.eventType)?.icon ?? Bot;
    const failed = action.status === 'failed';
    return (
      <div
        className={cn(
          'flex items-center gap-2.5 px-3.5 py-2',
          failed ? 'bg-crimson-950/25' : 'bg-void-900/40',
        )}
      >
        <Clock className="h-3 w-3 shrink-0 text-void-700" />
        <span className="w-14 shrink-0 font-mono text-[10px] tabular-nums text-void-600">
          {time}
        </span>
        <span
          className={cn(MESSAGE_ICON_BOX, 'mt-0', failed ? 'border-crimson-900/80' : 'border-void-800')}
        >
          <Icon className={cn('h-3 w-3', failed ? 'text-crimson-400' : 'text-plasma-400')} />
        </span>
        <span className={cn('text-xs font-medium', failed ? 'text-crimson-300' : 'text-void-200')}>
          {action.label}
        </span>
        {action.hint && <span className="truncate text-[11px] text-crimson-400">{action.hint}</span>}
      </div>
    );
  }

  return (
    <div
      className={cn(
        'border-b border-void-800/70 last:border-b-0',
        item.failed && 'bg-crimson-950/15',
      )}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-3.5 py-2.5 hover:bg-void-800/25 transition-colors"
      >
        {/* Meta: time · chat — with the raw peer id pinned, never truncated. */}
        <div className="flex items-center gap-2">
          <Clock className="h-3 w-3 shrink-0 text-void-700" />
          <span className="w-14 shrink-0 font-mono text-[10px] tabular-nums text-void-500">
            {time}
          </span>
          <span className="flex min-w-0 flex-1 items-center gap-1.5">
            <MessagesSquare className="h-3 w-3 shrink-0 text-plasma-600" />
            <span className="truncate font-mono text-[10px] text-plasma-400">
              {chatLabel ? sanitizeText(chatLabel) : item.peer ? `ID ${item.peer}` : 'неизвестный чат'}
            </span>
          </span>
          {item.peer && (
            <span className="shrink-0 rounded-[2px] border border-void-800 bg-void-900/40 px-1.5 py-px font-mono text-[9px] tabular-nums text-void-500">
              #{sanitizeText(item.peer)}
            </span>
          )}
          {item.actions.some((a) => a.status === 'failed') && (
            <span className="shrink-0 rounded-[2px] border border-crimson-900 px-1.5 py-px font-mono text-[9px] uppercase text-crimson-500">
              ошибка
            </span>
          )}
          <ChevronDown
            className={cn(
              'h-3.5 w-3.5 shrink-0 text-void-600 transition-transform',
              open && 'rotate-180',
            )}
          />
        </div>

        {/* Newest first inside a block: response → tools → incoming. */}
        <div className="mt-2.5 space-y-2">
          {item.response &&
            renderMessage(Bot, 'agent', agentLabel, 'ответ', item.response, item.response.content, true)}

          {!chatOnly && item.actions.length > 0 && (
            <div className="space-y-0.5 pl-[30px]">
              {[...item.actions].reverse().map((action) => (
                <ActionRow key={action.id} action={action} />
              ))}
            </div>
          )}

          {item.incoming &&
            renderMessage(
              UserRound,
              'peer',
              senderLabel ?? (item.peer ? `ID ${item.peer}` : 'собеседник'),
              'входящее',
              item.incoming,
              incomingBody(item.incoming.content),
              true,
            )}

          {!item.incoming &&
            item.trigger &&
            renderMessage(
              MessageSquarePlus,
              'trigger',
              'дашборд',
              'триггер',
              item.trigger,
              item.trigger.content,
              true,
            )}

          {!hasBody && item.actions.length === 0 && (
            <p className="pl-[30px] font-mono text-[10px] uppercase tracking-[0.12em] text-void-700">
              пустой ход
            </p>
          )}
        </div>
      </button>

      {open && (
        <div className="border-t border-void-800/50 px-3.5 py-2.5 space-y-2.5">
          {item.response &&
            renderMessage(Bot, 'agent', agentLabel, 'ответ', item.response, item.response.content, false)}

          {!chatOnly && item.actions.length > 0 && (
            <div className="space-y-0.5 pl-[30px]">
              {[...item.actions].reverse().map((action) => (
                <div key={`d-${action.id}`}>
                  <ActionRow action={action} />
                  <ActivityDetails action={action} agentId={item.agentId} />
                </div>
              ))}
            </div>
          )}

          {item.incoming &&
            renderMessage(
              UserRound,
              'peer',
              senderLabel ?? (item.peer ? `ID ${item.peer}` : 'собеседник'),
              'входящее',
              item.incoming,
              item.incoming.content,
              false,
            )}

          {!item.incoming &&
            item.trigger &&
            renderMessage(
              MessageSquarePlus,
              'trigger',
              'дашборд',
              'триггер',
              item.trigger,
              item.trigger.content,
              false,
            )}
        </div>
      )}
    </div>
  );
}
