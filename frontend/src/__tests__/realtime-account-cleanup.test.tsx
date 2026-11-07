import { afterEach, expect, mock, spyOn, test } from 'bun:test';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';

let onEvent: ((payload: { new: Record<string, unknown> }) => void) | undefined;
const removeChannel = mock(() => Promise.resolve());
const channel = {
  on: (_kind: string, filter: { table: string }, callback: typeof onEvent) => {
    if (filter.table === 'agent_events') onEvent = callback;
    return channel;
  },
  subscribe: () => channel,
};
mock.module('@/lib/supabase/client', () => ({
  getSupabaseClient: () => ({
    getChannels: () => [],
    channel: () => channel,
    removeChannel,
  }),
}));
const { useRealtimeFeed } = await import('@/hooks/useRealtimeFeed');
afterEach(() => { cleanup(); mock.restore(); });

test('unmount cancels a queued realtime refresh and ignores callbacks from the old channel', () => {
  const client = new QueryClient();
  const clear = spyOn(globalThis, 'clearTimeout');
  const schedule = spyOn(globalThis, 'setTimeout');
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const view = renderHook(() => useRealtimeFeed('agent'), { wrapper });
  act(() => onEvent?.({ new: { id: 'event', event_type: 'turn.completed', created_at: '2026-11-08T00:00:00Z' } }));
  const timer = schedule.mock.results.at(-1)?.value;
  view.unmount();
  expect(clear).toHaveBeenCalledWith(timer);
  expect(removeChannel).toHaveBeenCalledWith(channel);
  const calls = schedule.mock.calls.length;
  act(() => onEvent?.({ new: { id: 'late-event', event_type: 'turn.completed' } }));
  expect(schedule.mock.calls.length).toBe(calls);
  client.clear();
});
