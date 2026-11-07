import { afterEach, beforeEach, describe, expect, setSystemTime, spyOn, test } from 'bun:test';
import { createClient } from '@supabase/supabase-js';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { useAnalyticsData } from '@/hooks/useTelegramSession';
import * as supabaseClient from '@/lib/supabase/client';
import type { Database } from '@/types/supabase';

interface AnalyticsRow {
  id: string;
  agent_id: string;
  created_at: string;
  direction?: string;
  event_type?: string;
  status?: string;
}

type AnalyticsTable = 'agent_messages' | 'agent_events';
type AnalyticsDatabase = Record<AnalyticsTable, AnalyticsRow[]>;

const AGENT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const OTHER_AGENT_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const TIMESTAMP = '2026-11-05T12:00:00.000Z';
const originalTimezone = process.env.TZ;
const clients: QueryClient[] = [];
let restoreClient: (() => void) | undefined;

function row(index: number, values: Partial<AnalyticsRow> = {}): AnalyticsRow {
  return {
    id: `00000000-0000-4000-8000-${index.toString(16).padStart(12, '0')}`,
    agent_id: AGENT_ID,
    created_at: TIMESTAMP,
    ...values,
  };
}

function splitFilters(value: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < value.length; i += 1) {
    if (value[i] === '(') depth += 1;
    if (value[i] === ')') depth -= 1;
    if (value[i] === ',' && depth === 0) {
      parts.push(value.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(value.slice(start));
  return parts;
}

function compareTimestamps(left: string, right: string): number {
  function microseconds(value: string): bigint {
    const match = /^(.*T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
    if (!match) throw new Error(`Invalid timestamp: ${value}`);
    return BigInt(Date.parse(`${match[1]}${match[3]}`)) * BigInt(1000)
      + BigInt((match[2] ?? '').padEnd(6, '0').slice(0, 6));
  }

  const a = microseconds(left);
  const b = microseconds(right);
  return a === b ? 0 : a < b ? -1 : 1;
}

function matchesFilter(record: AnalyticsRow, expression: string): boolean {
  for (const operator of ['and', 'or']) {
    if (expression.startsWith(`${operator}(`)) {
      const matches = splitFilters(expression.slice(operator.length + 1, -1))
        .map((part) => matchesFilter(record, part));
      return operator === 'and' ? matches.every(Boolean) : matches.some(Boolean);
    }
  }

  const [column, operator, ...parts] = expression.split('.');
  const value = parts.join('.');
  const actual = record[column as keyof AnalyticsRow];
  if (actual === undefined) throw new Error(`Unsupported test filter: ${expression}`);
  const comparison = column === 'created_at'
    ? compareTimestamps(actual, value)
    : actual === value ? 0 : actual < value ? -1 : 1;
  switch (operator) {
    case 'eq':
      return comparison === 0;
    case 'gt':
      return comparison > 0;
    case 'gte':
      return comparison >= 0;
    case 'lt':
      return comparison < 0;
    case 'lte':
      return comparison <= 0;
    case 'in':
      return value.slice(1, -1).split(',').includes(actual);
    case 'like':
      return actual.startsWith(value.replace(/[%*]$/, ''));
    default:
      throw new Error(`Unsupported test filter: ${expression}`);
  }
}

function installDatabase(
  database: AnalyticsDatabase,
  { serverCap = 1000, failedRow, pendingTable }: {
    serverCap?: number;
    failedRow?: AnalyticsRow;
    pendingTable?: AnalyticsTable;
  } = {},
) {
  const requests = { agent_messages: 0, agent_events: 0 };
  const abortedTables: AnalyticsTable[] = [];
  const client = createClient<Database>('https://analytics.example.test', 'test-key', {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: false,
      storageKey: crypto.randomUUID(),
    },
    global: {
      fetch: Object.assign(async (
        input: Parameters<typeof fetch>[0],
        init?: Parameters<typeof fetch>[1],
      ) => {
        const url = new URL(input instanceof Request ? input.url : String(input));
        const table = url.pathname.split('/').at(-1) as AnalyticsTable;
        if (!(table in database)) throw new Error(`Unexpected analytics request: ${url}`);
        requests[table] += 1;
        if (table === pendingTable) {
          await new Promise<never>((_, reject) => {
            const abort = () => {
              abortedTables.push(table);
              reject(init?.signal?.reason);
            };
            if (init?.signal?.aborted) abort();
            else init?.signal?.addEventListener('abort', abort, { once: true });
          });
        }

        const filters = [...url.searchParams].filter(([key]) =>
          !['select', 'order', 'limit', 'offset'].includes(key),
        );
        const matching = database[table].filter((record) =>
          filters.every(([key, value]) => matchesFilter(
            record,
            key === 'and' || key === 'or' ? `${key}${value}` : `${key}.${value}`,
          )),
        );
        const ordering = (url.searchParams.get('order') ?? '').split(',').filter(Boolean);
        const sorted = [...matching].sort((left, right) => {
          for (const order of ordering) {
            const [column, direction] = order.split('.');
            const a = left[column as keyof AnalyticsRow] ?? '';
            const b = right[column as keyof AnalyticsRow] ?? '';
            const comparison = column === 'created_at'
              ? compareTimestamps(a, b)
              : a === b ? 0 : a < b ? -1 : 1;
            if (comparison !== 0) return comparison * (direction === 'desc' ? -1 : 1);
          }
          // SQL does not promise a consistent order within timestamp ties.
          return left.id.localeCompare(right.id) * (requests[table] % 2 === 1 ? 1 : -1);
        });
        const offset = Number(url.searchParams.get('offset') ?? 0);
        const limit = Math.min(Number(url.searchParams.get('limit') ?? serverCap), serverCap);
        const page = sorted.slice(offset, offset + limit);
        if (failedRow && page.some((record) => record === failedRow)) {
          return Response.json(
            { message: 'analytics page unavailable', code: '42501' },
            { status: 403 },
          );
        }

        const selected = url.searchParams.get('select');
        const data = !selected || selected === '*' ? page : page.map((record) =>
          Object.fromEntries(selected.split(',').map((column) => [
            column,
            record[column as keyof AnalyticsRow],
          ])),
        );
        const headers = new Headers({ 'Content-Type': 'application/json' });
        const count = new Headers(init?.headers).get('prefer')?.includes('count=exact')
          ? matching.length : '*';
        headers.set('Content-Range', page.length
          ? `${offset}-${offset + page.length - 1}/${count}`
          : `*/${count}`);
        return new Response(init?.method === 'HEAD' ? null : JSON.stringify(data), { headers });
      }, { preconnect: () => undefined }),
    },
  });
  const spy = spyOn(supabaseClient, 'getSupabaseClient').mockReturnValue(client);
  restoreClient = () => spy.mockRestore();
  return { abortedTables };
}

async function loadAnalytics(days: 7 | 30 = 7) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  clients.push(client);
  const { result } = renderHook(() => useAnalyticsData(AGENT_ID, days), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
  await waitFor(() => expect(result.current.isPending).toBe(false));
  return result.current;
}

beforeEach(() => {
  process.env.TZ = 'America/Los_Angeles';
  setSystemTime(new Date('2026-11-07T00:30:00.000Z'));
});

afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  restoreClient?.();
  restoreClient = undefined;
  setSystemTime();
  if (originalTimezone === undefined) delete process.env.TZ;
  else process.env.TZ = originalTimezone;
});

describe('useAnalyticsData', () => {
  test('preserves microsecond cursors and equivalent timezone offsets across pages', async () => {
    const timestamps = [
      '2026-11-05T12:00:00.123456+00:00',
      '2026-11-05T12:00:00.123457+00:00',
      '2026-11-05T07:00:00.123456-05:00',
      '2026-11-05T12:00:00.123455Z',
      '2026-11-05T12:00:00.123458Z',
    ];
    installDatabase({
      agent_messages: timestamps.map((created_at, index) => row(index, {
        created_at, direction: 'incoming',
      })),
      agent_events: timestamps.map((created_at, index) => row(index, {
        created_at, event_type: 'tool.failed', status: 'failed',
      })),
    }, { serverCap: 2 });

    const result = await loadAnalytics();

    expect(result.error).toBeNull();
    expect(result.data?.find((day) => day.date === '2026-11-05')).toEqual({
      date: '2026-11-05', messages: 5, actions: 5, errors: 5,
    });
  });

  test('a read failure cancels the other table without replacing the original error', async () => {
    const failedRow = row(0, { direction: 'incoming' });
    const { abortedTables } = installDatabase({
      agent_messages: [failedRow], agent_events: [],
    }, { failedRow, pendingTable: 'agent_events' });

    const result = await loadAnalytics();

    expect(result.error).toMatchObject({ message: 'analytics page unavailable' });
    expect(result.data).toBeUndefined();
    await waitFor(() => expect(abortedTables).toEqual(['agent_events']));
  });

  test.each([1000, 37])('counts all tied rows with a server cap of %i', async (serverCap) => {
    const messages = Array.from({ length: 1251 }, (_, index) => row(index, {
      direction: index % 2 === 0 ? 'incoming' : 'agent_response',
    }));
    const events = Array.from({ length: 1301 }, (_, index) => row(index, {
      event_type: index < 1001 ? 'tool.completed' : 'turn.completed',
      status: index >= 1201 ? 'failed' : 'success',
    }));
    installDatabase({
      agent_messages: [
        ...messages,
        row(2000, { direction: 'system' }),
        row(2001, { agent_id: OTHER_AGENT_ID, direction: 'incoming' }),
      ],
      agent_events: [...events, row(2000, {
        agent_id: OTHER_AGENT_ID, event_type: 'tool.failed', status: 'failed',
      })],
    }, { serverCap });

    const result = await loadAnalytics();

    expect(result.error).toBeNull();
    expect(result.data?.find((day) => day.date === '2026-11-05')).toEqual({
      date: '2026-11-05', messages: 1251, actions: 1001, errors: 100,
    });
    expect(result.data?.filter((day) => day.date !== '2026-11-05').every((day) =>
      day.messages === 0 && day.actions === 0 && day.errors === 0,
    )).toBe(true);
  });

  test.each(['agent_messages', 'agent_events'] as const)('a failed final %s page rejects partial analytics', async (table) => {
    const records = Array.from({ length: 1001 }, (_, index) => row(index, {
      direction: 'incoming', event_type: 'tool.failed', status: 'failed',
    }));
    installDatabase({ agent_messages: [], agent_events: [], [table]: records }, {
      failedRow: records.at(-1),
    });

    const result = await loadAnalytics();

    expect(result.isError).toBe(true);
    expect(result.error).toMatchObject({ message: 'analytics page unavailable' });
    expect(result.data).toBeUndefined();
  });

  test.each([
    [7, '2026-11-01'],
    [30, '2026-10-09'],
  ] as const)('returns %i UTC calendar days including midnight boundaries', async (days, firstDate) => {
    const timestamps = [
      new Date(Date.parse(`${firstDate}T00:00:00.000Z`) - 1).toISOString(),
      `${firstDate}T00:00:00.000Z`,
      '2026-11-06T23:59:59.999Z',
      '2026-11-07T00:00:00.000Z',
      '2026-11-07T00:29:59.999Z',
      '2026-11-07T23:59:59.999Z',
      '2026-11-08T00:00:00.000Z',
    ];
    installDatabase({
      agent_messages: timestamps.map((created_at, index) => row(index, {
        created_at, direction: 'incoming',
      })),
      agent_events: timestamps.map((created_at, index) => row(index, {
        created_at, event_type: 'tool.failed', status: 'failed',
      })),
    });

    const result = await loadAnalytics(days);

    expect(result.error).toBeNull();
    expect(result.data).toHaveLength(days);
    expect(result.data?.at(0)).toEqual({ date: firstDate, messages: 1, actions: 1, errors: 1 });
    expect(result.data?.at(-2)).toEqual({ date: '2026-11-06', messages: 1, actions: 1, errors: 1 });
    expect(result.data?.at(-1)).toEqual({ date: '2026-11-07', messages: 2, actions: 2, errors: 2 });
    expect(result.data?.slice(1, -2).every((day) =>
      day.messages === 0 && day.actions === 0 && day.errors === 0,
    )).toBe(true);
  });

  test('an initial read error is not presented as a period with zero activity', async () => {
    const failedRow = row(0, { direction: 'incoming' });
    installDatabase({ agent_messages: [failedRow], agent_events: [] }, { failedRow });

    const result = await loadAnalytics();

    expect(result.isError).toBe(true);
    expect(result.data).toBeUndefined();
  });
});
