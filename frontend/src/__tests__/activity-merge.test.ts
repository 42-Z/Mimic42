import { describe, expect, test } from 'bun:test';
import {
  buildActivityFeed,
  mergeActivityItems,
  turnToActivityItem,
  type ActivityItem,
  type EventLike,
} from '@/lib/activity/normalize';
import type { ConversationTurn, ToolCallRecord } from '@/types';

const START = '2026-11-07T10:00:00.000Z';
const TOOL_TIME = '2026-11-07T10:00:05.000Z';
const END = '2026-11-07T10:00:10.000Z';

const history = (over: Partial<ConversationTurn> = {}): ConversationTurn => ({
  id: 'incoming-1',
  agent_id: 'agent-1',
  timestamp: START,
  peer_id: '123',
  peer_name: 'Алиса',
  agent_name: 'Мимик',
  incoming: 'Посмотри фото',
  outgoing: '',
  direction: 'incoming',
  turn_id: 't1',
  incoming_media: [],
  tools: [],
  ...over,
});

const tool = (over: Partial<ToolCallRecord> = {}): ToolCallRecord => ({
  id: 'action-1',
  name: 'tool.get_me',
  status: 'succeeded',
  payload: { turn_id: 't1', args: { peer: '123' } },
  result: { success: true },
  error: null,
  duration_ms: 1000,
  created_at: TOOL_TIME,
  ...over,
});

const event = (over: Partial<EventLike> = {}): EventLike => ({
  id: 'action-1',
  agent_id: 'agent-1',
  event_type: 'tool.get_me',
  status: 'running',
  created_at: TOOL_TIME,
  started_at: '2026-11-07T10:00:04.000Z',
  payload: { turn_id: 't1', peer: '123', args: {} },
  ...over,
});

function live(events: EventLike[] = []): ActivityItem[] {
  return buildActivityFeed([{
    id: 'incoming-1',
    agent_id: 'agent-1',
    role: 'user',
    direction: 'incoming',
    content: 'Посмотри фото',
    created_at: START,
    payload: { turn_id: 't1', peer: '123' },
  }], events);
}

describe('mergeActivityItems', () => {
  test('empty history cannot erase live input and actions from the same turn', () => {
    const historical = turnToActivityItem(history({ incoming: '', timestamp: TOOL_TIME }));
    const [item] = mergeActivityItems([historical], live([event()]));

    expect(item?.incoming?.content).toBe('Посмотри фото');
    expect(item?.createdAt).toBe(START);
    expect(item?.actions.map((action) => action.id)).toEqual(['action-1']);
  });

  test('canonical messages keep rich metadata while live-only tools are added', () => {
    const media = [{
      kind: 'photo' as const,
      name: 'photo.jpg',
      mime_type: 'image/jpeg',
      size: 12,
      storage_path: 'agent-1/photo.jpg',
    }];
    const historical = turnToActivityItem(history({
      incoming: 'Посмотри фото с подписью',
      incoming_media: media,
      incoming_reply: { message_id: 42, preview: 'Предыдущее сообщение' },
      outgoing: 'Уже посмотрел',
      outgoing_reply_id: 99,
      tools: [tool({ result: { success: true, username: 'mimic' } })],
    }));
    const realtime = live([event(), event({
      id: 'action-2',
      event_type: 'tool.get_messages',
      created_at: END,
    })]);
    realtime[0]!.peerTitle = null;
    const before = structuredClone([historical, ...realtime]);
    const merged = mergeActivityItems([historical], realtime);
    const [item] = merged;

    expect(item?.incoming?.content).toBe('Посмотри фото с подписью');
    expect(item?.incoming?.media).toEqual(media);
    expect(item?.incomingMedia).toEqual(media);
    expect(item?.incoming?.reply).toEqual({ message_id: 42, preview: 'Предыдущее сообщение' });
    expect(item?.response?.content).toBe('Уже посмотрел');
    expect(item?.responseReplyTo).toBe(99);
    expect(item?.peerTitle).toBe('Алиса');
    expect(item?.agentId).toBe('agent-1');
    expect(item?.actions.map((action) => action.id)).toEqual(['action-1', 'action-2']);
    expect(item?.actions[0]?.args).toEqual({ peer: '123' });
    expect(item?.actions[0]?.result).toEqual({ success: true, username: 'mimic' });
    expect(item?.actions[0]?.status).toBe('succeeded');
    expect(mergeActivityItems(merged, realtime)).toEqual(merged);
    expect([historical, ...realtime]).toEqual(before);
  });

  test('a tools-only live snapshot retains historical input and reply metadata', () => {
    const historical = turnToActivityItem(history({
      incoming_reply: { message_id: 42, preview: 'Контекст' },
    }));
    const [item] = mergeActivityItems([historical], buildActivityFeed([], [event()]));

    expect(item?.incoming?.content).toBe('Посмотри фото');
    expect(item?.incoming?.reply?.preview).toBe('Контекст');
    expect(item?.actions).toHaveLength(1);
  });

  test('media-only historical input is retained when live events contain no message', () => {
    const media = [{
      kind: 'photo' as const,
      name: 'photo.jpg',
      mime_type: 'image/jpeg',
      size: 12,
      storage_path: 'agent-1/photo.jpg',
    }];
    const historical = turnToActivityItem(history({ incoming: '', incoming_media: media }));
    const [item] = mergeActivityItems([historical], buildActivityFeed([], [event()]));

    expect(item?.incoming?.media).toEqual(media);
    expect(item?.incomingMedia).toEqual(media);
  });

  test('live response and trigger survive a partial historical snapshot', () => {
    const [realtime] = live();
    const response = { id: 'response-1', content: 'Готово', createdAt: END };
    const trigger = { id: 'trigger-1', content: 'Проверить чат', createdAt: START };
    const [item] = mergeActivityItems([turnToActivityItem(history())], [{
      ...realtime!,
      response,
      trigger,
      responseReplyTo: 73,
    }]);

    expect(item?.response).toEqual(response);
    expect(item?.trigger).toEqual(trigger);
    expect(item?.responseReplyTo).toBe(73);
  });

  test('a terminal live action advances stale history without losing its args', () => {
    const historical = turnToActivityItem(history({ tools: [tool({
      status: 'running',
      result: null,
    })] }));
    const realtime = live([event({
      status: 'failed',
      error: 'Недоступно',
      result: { success: false, error_code: 'FloodWaitError' },
      completed_at: END,
    })]);
    const [item] = mergeActivityItems([historical], realtime);

    expect(item?.failed).toBe(true);
    expect(item?.actions).toHaveLength(1);
    expect(item?.actions[0]?.status).toBe('failed');
    expect(item?.actions[0]?.hint).toBe('Telegram просит подождать');
    expect(item?.actions[0]?.args).toEqual({ peer: '123' });
    expect(item?.actions[0]?.completedAt).toBe(END);
  });

  test('actions deduplicate by id and keep chronological order with equal timestamps', () => {
    const historical = turnToActivityItem(history({ tools: [
      tool({ id: 'first', created_at: START }),
      tool({ id: 'second' }),
    ] }));
    const realtime = live([
      event({ id: 'last', created_at: END }),
      event({ id: 'second' }),
      event({ id: 'same-time', created_at: TOOL_TIME }),
    ]);
    const [item] = mergeActivityItems([historical, historical], realtime);

    expect(item?.actions.map((action) => action.id)).toEqual([
      'first', 'same-time', 'second', 'last',
    ]);
    expect(mergeActivityItems([], [...realtime, historical])[0]?.actions.map((action) => action.id))
      .toEqual(item?.actions.map((action) => action.id));
  });

  test('equal-time items keep the same order across snapshot arrival order', () => {
    const [first] = live();
    const second = { ...first!, id: 'turn:t2', turnId: 't2' };
    expect(mergeActivityItems([first!], [second]).map((item) => item.id))
      .toEqual(['turn:t2', 'turn:t1']);
    expect(mergeActivityItems([second], [first!]).map((item) => item.id))
      .toEqual(['turn:t2', 'turn:t1']);
  });

  test('timer dispatch stays below its turn by timestamp, without event-specific priority', () => {
    const timer = buildActivityFeed([], [event({
      id: 'timer-1',
      event_type: 'timer.fired',
      status: 'succeeded',
      created_at: '2026-11-07T09:59:59.000Z',
      payload: { description: 'Проверить обсуждение' },
    })]);
    const later = buildActivityFeed([], [event({
      id: 'stop-1',
      event_type: 'agent.stopped',
      status: 'succeeded',
      created_at: END,
      payload: null,
    })]);
    const historical = turnToActivityItem(history({ incoming: '', timestamp: TOOL_TIME }));
    const merged = mergeActivityItems([historical, ...timer], [...live(), ...later]);

    expect(merged.map((item) => item.id)).toEqual(['evt:stop-1', 'turn:t1', 'evt:timer-1']);
    expect(merged[1]?.createdAt).toBe(START);
  });
});

describe('terminal-only turn normalization', () => {
  test.each([
    ['turn.completed', 'succeeded', false],
    ['turn.failed', 'failed', true],
    ['turn.cancelled', 'cancelled', false],
  ] as const)('%s stays a turn in history and realtime', (name, status, failed) => {
    const historical = turnToActivityItem(history({
      incoming: '',
      timestamp: END,
      tools: [tool({ id: 'terminal-1', name, status, created_at: END })],
    }));
    const realtime = buildActivityFeed([], [event({
      id: 'terminal-1',
      event_type: name,
      status,
      created_at: END,
    })]);
    const merged = mergeActivityItems([historical], realtime);

    expect(historical.kind).toBe('turn');
    expect(historical.id).toBe('turn:t1');
    expect(realtime[0]?.kind).toBe('turn');
    expect(merged).toHaveLength(1);
    expect(merged[0]?.actions).toHaveLength(1);
    expect(merged[0]?.failed).toBe(failed);
  });

  test('cancellation preserves input and is neutral unless a tool actually failed', () => {
    const terminal = event({
      id: 'terminal-1',
      event_type: 'turn.cancelled',
      status: 'cancelled',
      created_at: END,
      payload: { turn_id: 't1', trace_url: 'https://braintrust.dev/app/p/demo/t/turn-1' },
    });
    const cancelled = mergeActivityItems([], live([terminal]))[0];
    expect(cancelled?.incoming?.content).toBe('Посмотри фото');
    expect(cancelled?.failed).toBe(false);
    expect(cancelled?.actions[0]?.label).toBe('Ход отменён');
    expect(cancelled?.actions[0]?.status).toBe('cancelled');
    expect(cancelled?.actions[0]?.traceUrl).toBe('https://braintrust.dev/app/p/demo/t/turn-1');

    const [withError] = mergeActivityItems(
      [turnToActivityItem(history({ tools: [tool({ status: 'failed' })] }))],
      live([terminal]),
    );
    expect(withError?.failed).toBe(true);
    expect(withError?.actions).toHaveLength(2);
  });
});
