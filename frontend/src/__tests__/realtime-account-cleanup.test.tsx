import { afterEach, beforeEach, expect, mock, spyOn, test } from 'bun:test';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { navigationMock } from './next-navigation-mock';

let onEvent: ((payload: { new: Record<string, unknown> }) => void) | undefined;
const removeChannel = mock(() => Promise.resolve());
const subscribe = mock(() => channel);
const refreshHead = mock(async (_client: QueryClient, _userId: string | null) => {});
type Session = { user: { id: string; email: string } };
let onAuth: ((event: string, session: Session | null) => void) | undefined;
const channel: {
  on: (kind: string, filter: { table: string }, callback: typeof onEvent) => typeof channel;
  subscribe: () => typeof channel;
} = {
  on: (_kind: string, filter: { table: string }, callback: typeof onEvent) => {
    if (filter.table === 'agent_events') onEvent = callback;
    return channel;
  },
  subscribe,
};
mock.module('@/lib/supabase/client', () => ({
  getSupabaseClient: () => ({
    getChannels: () => [],
    channel: () => channel,
    removeChannel,
    from: () => {
      const query = {
        select: () => query,
        abortSignal: () => query,
        in: () => query,
        order: () => query,
        limit: () => query,
        then: (resolve: (value: { data: never[]; error: null }) => unknown) =>
          Promise.resolve({ data: [], error: null }).then(resolve),
      };
      return query;
    },
    auth: {
      getSession: async () => ({ data: { session: { user: { id: 'A', email: 'A@example.com' } } }, error: null }),
      onAuthStateChange: (callback: typeof onAuth) => {
        onAuth = callback;
        return { data: { subscription: { unsubscribe: () => { onAuth = undefined; } } } };
      },
    },
  }),
}));
const activityFeed = await import('@/hooks/useActivityFeed');
const { AccountProvider, useAccount } = await import('@/hooks/useAccount');
const { useRealtimeFeed, useMultiAgentRealtimeFeed } = await import('@/hooks/useRealtimeFeed');
function useSingleFeed() { return useRealtimeFeed('agent'); }
function useMultiFeed() { return useMultiAgentRealtimeFeed(['agent']); }
beforeEach(() => {
  removeChannel.mockClear();
  subscribe.mockClear();
  refreshHead.mockClear();
  spyOn(activityFeed, 'refreshActivityFeedHead').mockImplementation(refreshHead);
});
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

test.each(['single', 'multi'] as const)('same-user auth events preserve %s realtime items and subscriptions', async (mode) => {
  navigationMock.pathname = '/dashboard';
  const wrapper = ({ children }: { children: ReactNode }) => <AccountProvider>{children}</AccountProvider>;
  const useFeed = mode === 'single' ? useSingleFeed : useMultiFeed;
  const view = renderHook(() => {
    const feed = useFeed();
    return { feed, email: useAccount()?.user?.email };
  }, { wrapper });
  await waitFor(() => expect(subscribe).toHaveBeenCalledTimes(1));
  act(() => onEvent?.({ new: { id: 'event', event_type: 'turn.completed', status: 'succeeded', created_at: '2026-11-08T00:00:00Z' } }));
  const items = view.result.current.feed.items;
  expect(items).toHaveLength(1);

  for (const event of ['TOKEN_REFRESHED', 'USER_UPDATED', 'SIGNED_IN']) {
    act(() => onAuth?.(event, { user: { id: 'A', email: 'updated@example.com' } }));
    expect(view.result.current.email).toBe('updated@example.com');
    expect(view.result.current.feed.items).toEqual(items);
    expect(subscribe).toHaveBeenCalledTimes(1);
    expect(removeChannel).not.toHaveBeenCalled();
  }

  if (mode === 'single') {
    await waitFor(() => expect(refreshHead).toHaveBeenCalledTimes(1), { timeout: 2000 });
    expect(refreshHead.mock.calls[0]?.[1]).toBe('A');
  }
});
