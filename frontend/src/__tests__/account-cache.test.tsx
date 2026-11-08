import { afterEach, beforeEach, expect, mock, spyOn, test } from 'bun:test';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { StrictMode, useState } from 'react';
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useToast } from '@/components/ui/toast';
import { navigationMock } from './next-navigation-mock';

type Session = { access_token: string; user: { id: string } };
type Listener = (event: string, session: Session | null) => void;
const listeners = new Set<Listener>();
const subscriptions: Listener[] = [];
let session: Session | null = null;
let bootstrap: Promise<{ data: { session: Session | null }; error: Error | null }>;
mock.module('@/lib/supabase/client', () => ({
  getSupabaseClient: () => ({ auth: {
    getSession: () => bootstrap,
    onAuthStateChange: (listener: Listener) => {
      listeners.add(listener);
      subscriptions.push(listener);
      return { data: { subscription: { unsubscribe: () => listeners.delete(listener) } } };
    },
  } }),
}));
const { adminApi } = await import('@/lib/adminApi');
const { Providers } = await import('@/app/providers');
const { useStartAgent } = await import('@/hooks/useAgents');
const { apiClient } = await import('@/lib/api');
const originalAdapter = apiClient.defaults.adapter;
adminApi.me = async () => ({ user_id: session!.user.id, is_admin: false });

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
let clients: QueryClient[];
let pending: ReturnType<typeof deferred<string>>;
let mutation: ReturnType<typeof deferred<string>>;
let signals: AbortSignal[];
function Probe() {
  const { toast } = useToast();
  const client = useQueryClient();
  if (!clients.includes(client)) clients.push(client);
  const [draft, setDraft] = useState('');
  const query = useQuery({
    queryKey: ['private-probe'],
    queryFn: ({ signal }) => { signals.push(signal); return pending.promise; },
    retry: false,
  });
  const write = useMutation({
    mutationFn: () => mutation.promise,
    onSuccess: (value) => client.setQueryData(['private-probe'], value),
  });
  return <>
    <input aria-label="draft" value={draft} onChange={(event) => setDraft(event.target.value)} />
    <output>{query.data ?? (query.isError ? 'failed' : 'pending')}</output>
    <button onClick={() => write.mutate()}>save</button>
    <button onClick={() => toast('A private notification', 'info', 0)}>notify</button>
  </>;
}
async function change(userId: string | null, event = 'SIGNED_IN') {
  session = userId ? { access_token: `token-${userId}`, user: { id: userId } } : null;
  await act(async () => { listeners.forEach((listener) => listener(event, session)); });
}
beforeEach(() => {
  navigationMock.pathname = '/dashboard';
  subscriptions.length = 0;
  session = { access_token: 'token-A', user: { id: 'A' } };
  bootstrap = Promise.resolve({ data: { session }, error: null });
  clients = []; signals = []; pending = deferred(); mutation = deferred();
});
afterEach(() => { cleanup(); clients.forEach((client) => client.clear()); listeners.clear(); apiClient.defaults.adapter = originalAdapter; });

test('account switch removes old DOM and aborts pending queries; late mutations cannot enter B or A2', async () => {
  render(<Providers><Probe /></Providers>);
  await waitFor(() => expect(screen.queryByLabelText('draft')).not.toBeNull());
  await act(async () => { pending.resolve('A private data'); });
  await waitFor(() => expect(screen.queryByText('A private data')).not.toBeNull());
  fireEvent.change(screen.getByLabelText('draft'), { target: { value: 'A secret draft' } });
  fireEvent.click(screen.getByText('save'));
  fireEvent.click(screen.getByText('notify'));
  const a1 = clients.at(-1)!;
  pending = deferred();
  await act(async () => { void a1.refetchQueries(); });
  const pendingSignal = signals.at(-1)!;
  await change('B');
  expect(screen.queryByText('A private data')).toBeNull();
  expect(screen.queryByText('A private notification')).toBeNull();
  expect((screen.getByLabelText('draft') as HTMLInputElement).value).toBe('');
  expect(pendingSignal.aborted).toBe(true);
  expect(a1.getQueryCache().getAll()).toHaveLength(0);
  const b = clients.at(-1)!;
  expect(b).not.toBe(a1);
  await change('A');
  const a2 = clients.at(-1)!;
  expect(a2).not.toBe(a1);
  expect(a2).not.toBe(b);
  await act(async () => { mutation.resolve('late A1 mutation'); });
  expect(screen.queryByText('late A1 mutation')).toBeNull();
  expect(a2.getQueryData(['private-probe'])).toBeUndefined();
});

test('same-user refresh retains cache and draft', async () => {
  render(<Providers><Probe /></Providers>);
  await waitFor(() => expect(screen.queryByLabelText('draft')).not.toBeNull());
  fireEvent.change(screen.getByLabelText('draft'), { target: { value: 'keep draft' } });
  const client = clients.at(-1);
  await change('A', 'TOKEN_REFRESHED');
  expect(clients.at(-1)).toBe(client);
  expect((screen.getByLabelText('draft') as HTMLInputElement).value).toBe('keep draft');
});

test('external sign-out hides private state and redirects to login', async () => {
  navigationMock.pathname = '/agents/private-agent';
  render(<Providers><Probe /></Providers>);
  await waitFor(() => expect(screen.queryByLabelText('draft')).not.toBeNull());
  const outgoing = clients.at(-1)!;
  fireEvent.change(screen.getByLabelText('draft'), { target: { value: 'private draft' } });

  await change(null, 'SIGNED_OUT');

  expect(screen.queryByLabelText('draft')).toBeNull();
  expect(outgoing.getQueryCache().getAll()).toHaveLength(0);
  expect(navigationMock.replace).toHaveBeenCalledWith('/login?redirect=%2Fagents%2Fprivate-agent');
});

test('confirmed anonymous bootstrap redirects private routes without mounting them', async () => {
  session = null;
  bootstrap = Promise.resolve({ data: { session }, error: null });
  render(<Providers><Probe /></Providers>);
  await waitFor(() => expect(navigationMock.replace).toHaveBeenCalledWith('/login?redirect=%2Fdashboard'));
  expect(screen.queryByLabelText('draft')).toBeNull();
});

test('bootstrap gates private UI and ignores stale bootstrap after an auth event in StrictMode', async () => {
  const initial = deferred<Awaited<typeof bootstrap>>();
  bootstrap = initial.promise;
  render(<StrictMode><Providers><Probe /></Providers></StrictMode>);
  expect(screen.queryByLabelText('draft')).toBeNull();
  await change('B');
  await act(async () => { subscriptions[0]?.('SIGNED_IN', { access_token: 'obsolete', user: { id: 'A' } }); });
  await act(async () => { initial.resolve({ data: { session: { access_token: 'old', user: { id: 'A' } } }, error: null }); });
  expect(clients).toHaveLength(1);
});

test('bootstrap failure never mounts private UI', async () => {
  bootstrap = Promise.resolve({ data: { session: null }, error: new Error('offline') });
  render(<Providers><Probe /></Providers>);
  await act(async () => {});
  expect(screen.queryByLabelText('draft')).toBeNull();
});

test('a failed B request cannot fall back to A cached data', async () => {
  render(<Providers><Probe /></Providers>);
  await waitFor(() => expect(screen.queryByLabelText('draft')).not.toBeNull());
  await act(async () => { pending.resolve('A private data'); });
  await waitFor(() => expect(screen.queryByText('A private data')).not.toBeNull());
  pending = deferred();
  await change('B');
  await act(async () => { pending.reject(new Error('B is offline')); });
  await waitFor(() => expect(screen.queryByText('failed')).not.toBeNull());
  expect(screen.queryByText('A private data')).toBeNull();
});

test('a start mutation paused in onMutate cannot dispatch under the next account', async () => {
  let client: QueryClient | undefined;
  let result: Promise<unknown> | undefined;
  function StartProbe() {
    client = useQueryClient();
    const start = useStartAgent();
    return <button onClick={() => { result = start.mutateAsync('agent-A').catch((error: unknown) => error); }}>start</button>;
  }
  const dispatch = mock(async (config: Parameters<NonNullable<import('axios').AxiosAdapter>>[0]) => ({
    config, data: {}, headers: {}, status: 200, statusText: 'OK',
  }));
  apiClient.defaults.adapter = dispatch;
  render(<Providers><StartProbe /></Providers>);
  await waitFor(() => expect(client).toBeDefined());
  const pause = deferred<void>();
  const cancel = spyOn(client!, 'cancelQueries').mockImplementationOnce(() => pause.promise);
  fireEvent.click(screen.getByText('start'));
  await waitFor(() => expect(cancel).toHaveBeenCalledTimes(1));
  await change('B');
  await act(async () => { pause.resolve(); });
  expect(await result).toMatchObject({ code: 'ERR_CANCELED' });
  expect(dispatch).not.toHaveBeenCalled();
  cancel.mockRestore();
});

test.each(['/login', '/register', '/reset-password'])('anonymous visitors can use %s', async (path) => {
  navigationMock.pathname = path;
  session = null;
  bootstrap = Promise.resolve({ data: { session }, error: null });
  render(<Providers><span>public form</span></Providers>);
  await waitFor(() => expect(screen.queryByText('public form')).not.toBeNull());
});

test('a pending or failed session lookup does not block the login form', async () => {
  navigationMock.pathname = '/login';
  const initial = deferred<Awaited<typeof bootstrap>>();
  bootstrap = initial.promise;
  render(<Providers><input aria-label="login email" /></Providers>);
  expect(screen.queryByLabelText('login email')).not.toBeNull();
  fireEvent.change(screen.getByLabelText('login email'), { target: { value: 'user@example.com' } });
  await act(async () => {
    initial.resolve({ data: { session: null }, error: new Error('Session lookup failed') });
  });
  expect((screen.getByLabelText('login email') as HTMLInputElement).value).toBe('user@example.com');
});
