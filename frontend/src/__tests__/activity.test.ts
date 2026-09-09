import { describe, expect, test } from 'bun:test';
import { buildActivityFeed, type EventLike, type MessageLike } from '@/lib/activity/normalize';

const msg = (over: Partial<MessageLike>): MessageLike => ({
  id: 'm1',
  role: 'user',
  content: 'привет',
  created_at: '2026-09-09T10:00:00Z',
  ...over,
});

const evt = (over: Partial<EventLike>): EventLike => ({
  id: 'e1',
  event_type: 'tool.send_text_message',
  status: 'succeeded',
  created_at: '2026-09-09T10:00:05Z',
  ...over,
});

describe('buildActivityFeed', () => {
  test('groups a turn: incoming, actions and response by turn_id', () => {
    const items = buildActivityFeed(
      [
        msg({ id: 'in', payload: { turn_id: 't1', peer: '123' } }),
        msg({
          id: 'out',
          role: 'assistant',
          direction: 'agent_response',
          content: 'ответ',
          created_at: '2026-09-09T10:00:10Z',
          payload: { turn_id: 't1', peer: '123' },
        }),
      ],
      [
        evt({ id: 'a1', payload: { turn_id: 't1' } }),
        evt({
          id: 'a2',
          event_type: 'tool.pin_message',
          status: 'failed',
          error: 'No admin rights',
          payload: { turn_id: 't1', error_code: 'ChatAdminRequiredError' },
          result: { success: false, error_code: 'ChatAdminRequiredError' },
        }),
      ],
    );

    expect(items).toHaveLength(1);
    expect(items[0]?.kind).toBe('turn');
    expect(items[0]?.failed).toBe(true);
    expect(items[0]?.incoming?.content).toBe('привет');
    expect(items[0]?.response?.content).toBe('ответ');
    expect(items[0]?.actions.map((a) => a.status)).toEqual(['succeeded', 'failed']);
  });

  test('drops tool_call/tool_result transcript rows', () => {
    const items = buildActivityFeed(
      [
        msg({ direction: 'tool_call', content: '[]', payload: { turn_id: 't1' } }),
        msg({ direction: 'tool_result', content: '{}', payload: { turn_id: 't1' } }),
      ],
      [],
    );
    expect(items).toHaveLength(0);
  });

  test('lifecycle events without turn_id render standalone', () => {
    const items = buildActivityFeed(
      [],
      [evt({ id: 'life', event_type: 'agent.started', status: 'succeeded', payload: null })],
    );
    expect(items).toHaveLength(1);
    expect(items[0]?.kind).toBe('lifecycle');
    expect(items[0]?.actions[0]?.label).toBe('Агент запущен');
  });

  test('failed tool maps error code to a human phrase', () => {
    const items = buildActivityFeed(
      [],
      [
        evt({
          id: 'err',
          status: 'failed',
          error: 'An invalid Peer was used',
          payload: { turn_id: 't9', error_code: 'FloodWaitError' },
        }),
      ],
    );
    expect(items[0]?.actions[0]?.hint).toBe('Telegram просит подождать');
  });
});
