import { getToolMeta } from './toolCatalog';
import { getEventMeta } from './eventCatalog';
import { describeError } from './errorCatalog';
import type { ConversationTurn, MediaItem, ToolCallRecord } from '@/types';

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
  media?: MediaItem[];
  reply?: { message_id: number; preview?: string | null } | null;
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
  incomingMedia?: MediaItem[];
  responseReplyTo?: number | null;
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

function peerNameOf(message: MessageLike | undefined): string {
  const value = message?.payload?.peer_name;
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

function structuredTextOf(message: MessageLike | undefined): string {
  const structured = message?.payload?.structured_response;
  if (structured && typeof structured === 'object') {
    const text = (structured as { text?: unknown }).text;
    if (typeof text === 'string') return text;
  }
  return '';
}

function mediaOf(message: MessageLike | undefined): MediaItem[] {
  const media = message?.payload?.media;
  return Array.isArray(media) ? (media as MediaItem[]) : [];
}

function replyOf(
  message: MessageLike | undefined,
): { message_id: number; preview?: string | null } | null {
  const reply = message?.payload?.reply;
  if (!reply || typeof reply !== 'object') return null;
  const record = reply as Record<string, unknown>;
  const id = record.message_id;
  if (typeof id !== 'number') return null;
  const preview = typeof record.preview === 'string' ? record.preview : null;
  return { message_id: id, preview };
}

function numeric(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && /^\d+$/.test(value)) return Number(value);
  return null;
}

/** Reply target of the agent's answer: structured response or AgentResponse args. */
function responseReplyOf(message: MessageLike | undefined): number | null {
  const payload = message?.payload;
  if (!payload) return null;
  const structured = payload.structured_response;
  if (structured && typeof structured === 'object') {
    const found = numeric((structured as Record<string, unknown>).reply_to);
    if (found !== null) return found;
  }
  const toolCalls = payload.tool_calls;
  if (Array.isArray(toolCalls)) {
    for (const call of toolCalls) {
      if (!call || typeof call !== 'object') continue;
      const args = (call as Record<string, unknown>).args;
      if (args && typeof args === 'object') {
        const found = numeric((args as Record<string, unknown>).reply_to);
        if (found !== null) return found;
      }
    }
  }
  return null;
}

/** Reply target carried by a successful send_text_message tool event. */
function toolReplyOf(event: EventLike | undefined): number | null {
  const args = event?.payload?.args;
  if (!args || typeof args !== 'object') return null;
  return numeric((args as Record<string, unknown>).reply_to_msg_id);
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

  // The visible reply: a stored response row, the structured text of a realtime
  // row with empty content, or the message a successful send_text_message
  // tool call actually delivered (tool-only turns have no response row).
  let responseContent = responseMsg ? responseMsg.content : '';
  if (!responseContent && responseMsg) responseContent = structuredTextOf(responseMsg);
  let responseCreatedAt = responseMsg?.created_at ?? null;
  if (!responseContent) {
    const sentTool = sortedEvents.find(
      (e) => e.event_type === 'tool.send_text_message' && e.status === 'succeeded',
    );
    const args = sentTool?.payload?.args as Record<string, unknown> | undefined;
    if (args && typeof args.message === 'string') {
      responseContent = args.message;
      responseCreatedAt = sentTool?.completed_at ?? sentTool?.created_at ?? null;
    }
  }

  const timestamps = [
    ...messages.map((m) => new Date(m.created_at).getTime()),
    ...events.map((e) => new Date(e.created_at).getTime()),
  ].filter((t) => Number.isFinite(t));
  const createdAt = timestamps.length ? new Date(Math.min(...timestamps)).toISOString() : key;
  const endedAt = sortedEvents.at(-1)?.completed_at ?? responseCreatedAt ?? null;

  const peer =
    (incomingMsg ? peerOf(incomingMsg) : '') ||
    (triggerMsg ? peerOf(triggerMsg) : '') ||
    (sortedEvents[0]?.payload?.peer as string | undefined) ||
    '';

  const responseId = responseMsg?.id ?? `${key}:response`;

  // The answer's reply target: structured response, AgentResponse args, or the
  // message a successful send_text_message tool call replied to.
  let responseReplyTo = responseReplyOf(responseMsg);
  if (responseReplyTo === null) {
    const sentTool = sortedEvents.find(
      (e) => e.event_type === 'tool.send_text_message' && e.status === 'succeeded',
    );
    responseReplyTo = toolReplyOf(sentTool);
  }

  return {
    kind,
    id: key,
    agentId: messages[0]?.agent_id ?? events[0]?.agent_id,
    turnId: turnIdOf(messages[0]?.payload ?? events[0]?.payload ?? null),
    peer,
    peerTitle: peerNameOf(incomingMsg) || peerNameOf(triggerMsg) || null,
    createdAt,
    endedAt,
    failed: sortedEvents.some((e) => e.status === 'failed'),
    incoming: incomingMsg
      ? {
          id: incomingMsg.id,
          content: incomingMsg.content,
          createdAt: incomingMsg.created_at,
          media: mediaOf(incomingMsg),
          reply: replyOf(incomingMsg),
        }
      : null,
    response: responseContent
      ? {
          id: responseId,
          content: responseContent,
          createdAt: responseCreatedAt ?? createdAt,
        }
      : null,
    trigger: triggerMsg
      ? { id: triggerMsg.id, content: triggerMsg.content, createdAt: triggerMsg.created_at }
      : null,
    incomingMedia: mediaOf(incomingMsg),
    responseReplyTo,
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

/**
 * Maps a backend conversation turn (cursor page) into the feed item shape.
 * Tool records reuse `toAction`, so labels/statuses match the realtime path.
 */
export function turnToActivityItem(turn: ConversationTurn): ActivityItem {
  const createdAt = new Date(turn.timestamp).toISOString();
  const toActionRow = (tool: ToolCallRecord) => {
    // History stores the duration, not the start/end pair: restore the start so
    // ActionRow can show the real duration instead of "0 мс".
    const completedAt = tool.created_at;
    const durationMs = typeof tool.duration_ms === 'number' ? tool.duration_ms : 0;
    const startedAt =
      durationMs > 0
        ? new Date(new Date(completedAt).getTime() - durationMs).toISOString()
        : completedAt;
    return toAction({
      id: tool.id,
      event_type: tool.name,
      status: tool.status,
      created_at: tool.created_at,
      error: tool.error,
      payload: (tool.payload ?? null) as Record<string, unknown> | null,
      result: (tool.result ?? null) as Record<string, unknown> | null,
      started_at: startedAt,
      completed_at: completedAt,
    } as unknown as EventLike);
  };

  const actions = turn.tools.map(toActionRow);
  const firstAction = actions[0];

  // A turn made of a single lifecycle event (agent.started, timer.fired, …)
  // renders as one compact line — same shape and id as the realtime feed, so
  // the two sources deduplicate instead of showing the event twice.
  if (
    !turn.incoming &&
    !turn.outgoing &&
    actions.length === 1 &&
    firstAction !== undefined &&
    !firstAction.eventType.startsWith('tool.')
  ) {
    return {
      kind: 'lifecycle',
      id: `evt:${firstAction.id}`,
      agentId: turn.agent_id,
      turnId: turn.turn_id ?? null,
      peer: turn.peer_id,
      peerTitle: turn.peer_name || null,
      createdAt,
      endedAt: null,
      failed: firstAction.status === 'failed',
      incoming: null,
      response: null,
      trigger: null,
      incomingMedia: [],
      actions,
    };
  }

  return {
    kind: 'turn',
    id: turn.turn_id ? `turn:${turn.turn_id}` : `msg:${turn.id}`,
    agentId: turn.agent_id,
    turnId: turn.turn_id ?? null,
    peer: turn.peer_id,
    peerTitle: turn.peer_name || null,
    createdAt,
    endedAt: null,
    failed: actions.some((a) => a.status === 'failed'),
    incoming: turn.incoming
      ? {
          id: turn.id,
          content: turn.incoming,
          createdAt,
          media: turn.incoming_media ?? [],
          reply: turn.incoming_reply ?? null,
        }
      : null,
    response: turn.outgoing
      ? { id: `${turn.id}-out`, content: turn.outgoing, createdAt }
      : null,
    trigger: null,
    incomingMedia: turn.incoming_media ?? [],
    responseReplyTo: turn.outgoing_reply_id ?? null,
    actions,
  };
}

/** Extract the human-readable part of the wrapped incoming message prompt. */
export function incomingBody(content: string): string {
  const match = content.match(/Содержимое: ([\s\S]*)$/);
  const senderMatch = content.match(/Отправитель: (.*)$/m);
  const body = match?.[1] ?? content;
  const sender = senderMatch?.[1]?.trim() ?? null;
  return sender ? `${body} — ${sender}` : body;
}
