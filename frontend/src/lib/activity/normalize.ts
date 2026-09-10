import { getToolMeta } from './toolCatalog';
import { getEventMeta } from './eventCatalog';
import { describeError } from './errorCatalog';

/** Loose row shapes accepted from both the REST API and the realtime channel. */
export interface MessageLike {
  id: string;
  agent_id?: string;
  peer?: string;
  role: string;
  content: string;
  created_at: string;
  direction?: string | null;
  payload?: Record<string, unknown> | null;
}

export interface EventLike {
  id?: string;
  agent_id?: string;
  event_type: string;
  status: string;
  created_at: string;
  error?: string | null;
  payload?: Record<string, unknown> | null;
  result?: Record<string, unknown> | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface ActivityAction {
  id: string;
  eventType: string;
  status: string;
  label: string;
  hint: string | null;
  args: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  startedAt: string | null;
  completedAt: string | null;
}

export interface ActivityMessagePart {
  id: string;
  content: string;
  createdAt: string;
}

export type ActivityItemKind = 'turn' | 'lifecycle';

export interface ActivityItem {
  kind: ActivityItemKind;
  id: string;
  agentId?: string;
  turnId: string | null;
  peer: string;
  peerTitle: string | null;
  createdAt: string;
  endedAt: string | null;
  failed: boolean;
  incoming: ActivityMessagePart | null;
  response: ActivityMessagePart | null;
  trigger: ActivityMessagePart | null;
  actions: ActivityAction[];
}

/** Raw LangChain transcript rows — replaced by typed tool.* events. */
const TRANSCRIPT_DIRECTIONS = new Set(['tool_call', 'tool_result']);

function turnIdOf(payload: Record<string, unknown> | null | undefined): string | null {
  const value = payload?.turn_id;
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function peerOf(message: MessageLike): string {
  if (typeof message.peer === 'string' && message.peer) return message.peer;
  const value = message.payload?.peer;
  return typeof value === 'string' ? value : '';
}

function toAction(event: EventLike): ActivityAction {
  const isTool = event.event_type.startsWith('tool.');
  const payload = event.payload ?? null;
  // The failure identity lives in the tool result ({"success": false,
  // "error_code": ...}) or, for runtime exceptions, in the payload.
  const errorCode =
    typeof payload?.error_code === 'string'
      ? payload.error_code
      : typeof event.result?.error_code === 'string'
        ? event.result.error_code
        : null;
  const meta = isTool ? getToolMeta(event.event_type.slice('tool.'.length)) : null;
  const lifecycle = getEventMeta(event.event_type);
  const label = meta ? meta.ru : lifecycle ? lifecycle.ru : event.event_type;
  return {
    id: event.id ?? event.created_at,
    eventType: event.event_type,
    status: event.status,
    label,
    hint:
      event.status === 'failed'
        ? describeError(errorCode, event.error ?? null)
        : lifecycle && typeof payload?.description === 'string'
          ? (payload.description as string)
          : null,
    args: isTool && payload ? (payload.args as Record<string, unknown> | undefined) ?? null : null,
    result: event.result ?? null,
    startedAt: event.started_at ?? null,
    completedAt: event.completed_at ?? null,
  };
}

function buildTurn(
  key: string,
  messages: MessageLike[],
  events: EventLike[],
  kind: ActivityItemKind = 'turn',
): ActivityItem {
  const incomingMsg = messages.find(
    (m) => m.direction === 'incoming' || m.role === 'user' || m.role === 'human',
  );
  const responseMsg = [...messages]
    .reverse()
    .find((m) => m.direction === 'agent_response' || m.role === 'assistant');
  const triggerMsg = messages.find((m) => m.direction === 'dashboard_trigger');

  const sortedEvents = [...events].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  );

  const timestamps = [
    ...messages.map((m) => new Date(m.created_at).getTime()),
    ...events.map((e) => new Date(e.created_at).getTime()),
  ].filter((t) => Number.isFinite(t));
  const createdAt = timestamps.length ? new Date(Math.min(...timestamps)).toISOString() : key;
  const endedAt = sortedEvents.at(-1)?.completed_at ?? responseMsg?.created_at ?? null;

  const peer =
    (incomingMsg ? peerOf(incomingMsg) : '') ||
    (triggerMsg ? peerOf(triggerMsg) : '') ||
    (sortedEvents[0]?.payload?.peer as string | undefined) ||
    '';

  return {
    kind,
    id: key,
    agentId: messages[0]?.agent_id ?? events[0]?.agent_id,
    turnId: turnIdOf(messages[0]?.payload ?? events[0]?.payload ?? null),
    peer,
    peerTitle: null,
    createdAt,
    endedAt,
    failed: sortedEvents.some((e) => e.status === 'failed'),
    incoming: incomingMsg
      ? { id: incomingMsg.id, content: incomingMsg.content, createdAt: incomingMsg.created_at }
      : null,
    response: responseMsg
      ? { id: responseMsg.id, content: responseMsg.content, createdAt: responseMsg.created_at }
      : null,
    trigger: triggerMsg
      ? { id: triggerMsg.id, content: triggerMsg.content, createdAt: triggerMsg.created_at }
      : null,
    actions: sortedEvents.map(toAction),
  };
}

/**
 * Normalize raw messages and events into human-facing activity items.
 *
 * Tool transcripts (`tool_call` / `tool_result` message rows) are dropped —
 * they are replaced by typed `tool.*` events. Rows without a turn_id
 * (legacy data and lifecycle events) render as standalone items.
 */
export function buildActivityFeed(
  messages: MessageLike[],
  events: EventLike[],
  peerNames?: Map<string, string>,
): ActivityItem[] {
  const visibleMessages = messages.filter(
    (m) => !TRANSCRIPT_DIRECTIONS.has(m.direction ?? ''),
  );
  const turnGroups = new Map<string, { messages: MessageLike[]; events: EventLike[] }>();
  const standalone: ActivityItem[] = [];

  const groupOf = (key: string) => {
    let group = turnGroups.get(key);
    if (!group) {
      group = { messages: [], events: [] };
      turnGroups.set(key, group);
    }
    return group;
  };

  for (const message of visibleMessages) {
    const turnId = turnIdOf(message.payload);
    if (turnId) groupOf(`turn:${turnId}`).messages.push(message);
    else standalone.push(buildTurn(`msg:${message.id}`, [message], [], 'turn'));
  }

  for (const event of events) {
    const turnId = turnIdOf(event.payload);
    if (turnId) groupOf(`turn:${turnId}`).events.push(event);
    else standalone.push(buildTurn(`evt:${event.id ?? event.created_at}`, [], [event], 'lifecycle'));
  }

  const items: ActivityItem[] = [...standalone];
  for (const [key, group] of turnGroups) {
    items.push(buildTurn(key, group.messages, group.events, 'turn'));
  }

  items.sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime());

  if (peerNames) {
    for (const item of items) {
      item.peerTitle = peerNames.get(item.peer) ?? null;
    }
  }
  return items;
}

/** Total count of tool actions inside an item. */
export function countActions(item: ActivityItem): number {
  return item.actions.filter((a) => a.eventType.startsWith('tool.')).length;
}

/** Extract the human-readable part of the wrapped incoming message prompt. */
export function incomingBody(content: string): string {
  const match = content.match(/Содержимое: ([\s\S]*)$/);
  const senderMatch = content.match(/Отправитель: (.*)$/m);
  const body = match?.[1] ?? content;
  const sender = senderMatch?.[1]?.trim() ?? null;
  return sender ? `${body} — ${sender}` : body;
}
