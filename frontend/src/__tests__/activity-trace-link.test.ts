import { describe, expect, test } from 'bun:test';
import { buildActivityFeed, type EventLike } from '@/lib/activity/normalize';
import { getEventMeta } from '@/lib/activity/eventCatalog';

const evt = (over: Partial<EventLike>): EventLike => ({
  id: 'e1',
  event_type: 'turn.completed',
  status: 'succeeded',
  created_at: '2026-09-26T10:00:05Z',
  ...over,
});

describe('trace links', () => {
  test('turn.completed has a Russian label', () => {
    expect(getEventMeta('turn.completed')?.ru).toBe('Ход завершён');
  });

  test('payload.trace_url becomes action.traceUrl', () => {
    const [item] = buildActivityFeed(
      [],
      [
        evt({
          payload: {
            turn_id: 't1',
            peer: '123',
            trace_url: 'https://braintrust.dev/app/p/mimic42/t/turn-1',
          },
        }),
      ],
    );

    expect(item?.actions[0]?.traceUrl).toBe('https://braintrust.dev/app/p/mimic42/t/turn-1');
  });

  test('actions without trace_url have traceUrl null', () => {
    const [item] = buildActivityFeed([], [evt({ payload: { turn_id: 't1', peer: '123' } })]);

    expect(item?.actions[0]?.traceUrl).toBeNull();
  });

  test('trace_url не http(s) и пустые значения отбрасываются', () => {
    for (const trace_url of ['javascript:alert(1)', 'data:text/html,x', '   ', '']) {
      const [item] = buildActivityFeed(
        [],
        [evt({ payload: { turn_id: 't1', peer: '123', trace_url } })],
      );

      expect(item?.actions[0]?.traceUrl).toBeNull();
    }
  });

  test('http:// тоже принимается, пробелы по краям срезаются', () => {
    const [item] = buildActivityFeed(
      [],
      [
        evt({
          payload: {
            turn_id: 't1',
            peer: '123',
            trace_url: '  http://braintrust.local/t/turn-1  ',
          },
        }),
      ],
    );

    expect(item?.actions[0]?.traceUrl).toBe('http://braintrust.local/t/turn-1');
  });

  test('turn.failed несёт и hint, и trace_url', () => {
    const [item] = buildActivityFeed(
      [],
      [
        evt({
          event_type: 'turn.failed',
          status: 'failed',
          error: 'boom',
          payload: {
            turn_id: 't1',
            peer: '123',
            error_code: 'SessionRevokedError',
            trace_url: 'https://braintrust.dev/app/p/mimic42/t/turn-1',
          },
        }),
      ],
    );

    expect(item?.actions[0]?.hint).toBe('Сессия отозвана, требуется переподключение');
    expect(item?.actions[0]?.traceUrl).toBe('https://braintrust.dev/app/p/mimic42/t/turn-1');
  });
});
