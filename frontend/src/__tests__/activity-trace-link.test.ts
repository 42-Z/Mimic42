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
});
