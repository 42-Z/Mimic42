import { describe, expect, test } from 'bun:test';
import {
  buildActivityFeed,
  turnToActivityItem,
  type EventLike,
  type MessageLike,
} from '@/lib/activity/normalize';
import type { ConversationTurn } from '@/types';

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
          payload: { turn_id: 't9' },
          result: { success: false, error: 'An invalid Peer was used', error_code: 'FloodWaitError' },
        }),
      ],
    );
    expect(items[0]?.actions[0]?.hint).toBe('Telegram просит подождать');
  });

  test('runtime failures carry error_code in the payload', () => {
    const items = buildActivityFeed(
      [],
      [
        evt({
          id: 'mfail',
          event_type: 'model.failed',
          status: 'failed',
          error: 'provider down',
          payload: { turn_id: 't2', peer: '123', error_code: 'APIStatusError' },
        }),
      ],
    );
    expect(items[0]?.actions[0]?.hint).toBe('provider down');
  });

  test('resolves structured_response text as the response', () => {
    const items = buildActivityFeed(
      [
        msg({
          id: 's1',
          role: 'assistant',
          direction: 'agent_response',
          content: '',
          payload: { turn_id: 't1', structured_response: { text: 'Привет!' } },
        }),
      ],
      [],
    );
    expect(items[0]?.response?.content).toBe('Привет!');
  });

  test('falls back to a successful send_text_message tool call', () => {
    const items = buildActivityFeed(
      [msg({ id: 'in', payload: { turn_id: 't2' } })],
      [
        evt({
          id: 'sent',
          payload: { turn_id: 't2', args: { message: 'Ответ тулзой' } },
        }),
      ],
    );
    expect(items[0]?.response?.content).toBe('Ответ тулзой');
  });

  test('realtime turns carry the interlocutor name from payload', () => {
    const items = buildActivityFeed(
      [
        msg({
          id: 'in',
          payload: {
            turn_id: 't-name',
            peer: '6121153070',
            peer_name: 'Miqqil⁴² 5opka - MAGNUM (@miqqil, ID: 6121153070)',
          },
        }),
      ],
      [],
    );
    expect(items[0]?.peer).toBe('6121153070');
    expect(items[0]?.peerTitle).toBe('Miqqil⁴² 5opka - MAGNUM (@miqqil, ID: 6121153070)');
  });

  test('carries incoming media from payload', () => {
    const items = buildActivityFeed(
      [
        msg({
          id: 'media',
          content: '[Фото id=photo:1:2:aa:5]',
          payload: {
            turn_id: 't3',
            media: [
              {
                kind: 'photo',
                name: 'photo.jpeg',
                mime_type: 'image/jpeg',
                size: 3,
                storage_path: 'ag/1/p.jpeg',
              },
            ],
          },
        }),
      ],
      [],
    );
    expect(items[0]?.incomingMedia?.length).toBe(1);
    expect(items[0]?.incomingMedia?.[0]?.storage_path).toBe('ag/1/p.jpeg');
  });
});

describe('turnToActivityItem', () => {
  test('maps a backend turn preserving media and turn identity', () => {
    const turn = {
      id: 'm1',
      agent_id: 'agent-1',
      timestamp: '2026-01-01T00:00:00Z',
      turn_id: 't9',
      peer_id: '1',
      peer_name: 'Аня',
      agent_name: 'Мими',
      incoming: 'Привет',
      outgoing: 'Привет-привет',
      direction: 'both',
      tools: [],
      incoming_media: [
        {
          kind: 'photo',
          name: 'p.jpeg',
          mime_type: 'image/jpeg',
          size: 3,
          storage_path: 'ag/1/p.jpeg',
        },
      ],
    } as unknown as ConversationTurn;

    const item = turnToActivityItem(turn);

    expect(item.id).toBe('turn:t9');
    expect(item.agentId).toBe('agent-1');
    expect(item.incomingMedia?.[0]?.storage_path).toBe('ag/1/p.jpeg');
    expect(item.response?.content).toBe('Привет-привет');
    expect(item.peerTitle).toBe('Аня');
  });

  test('maps tool records to actions with human labels', () => {
    const turn = {
      id: 'm2',
      agent_id: 'agent-1',
      timestamp: '2026-01-01T00:00:00Z',
      turn_id: 't10',
      peer_id: '1',
      peer_name: '',
      agent_name: '',
      incoming: 'Привет',
      outgoing: '',
      direction: 'incoming',
      incoming_media: [],
      tools: [
        {
          id: 'ev1',
          name: 'tool.send_text_message',
          status: 'succeeded',
          payload: { args: { peer: '1', message: 'hi' } },
          result: { success: true },
          error: null,
          duration_ms: 100,
          created_at: '2026-01-01T00:00:05Z',
        },
      ],
    } as unknown as ConversationTurn;

    const item = turnToActivityItem(turn);

    expect(item.actions).toHaveLength(1);
    expect(item.actions[0]?.eventType).toBe('tool.send_text_message');
    expect(item.actions[0]?.status).toBe('succeeded');
    expect(item.actions[0]?.label).not.toContain('<');
  });
});
