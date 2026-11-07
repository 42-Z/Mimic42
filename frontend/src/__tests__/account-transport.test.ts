import { afterEach, expect, mock, test } from 'bun:test';
import { AxiosError, type InternalAxiosRequestConfig } from 'axios';

type Session = { access_token: string; user: { id: string } };
let session: Session = { access_token: 'A-token', user: { id: 'A' } };
let lookup: (() => Promise<{ data: { session: Session }; error: null }>) | undefined;
mock.module('@/lib/supabase/client', () => ({
  getSupabaseClient: () => ({ auth: {
    getSession: () => lookup ? lookup() : Promise.resolve({ data: { session }, error: null }),
  } }),
}));
const { apiClient, createAccountApi, setApiAccountScope } = await import('@/lib/api');
const originalAdapter = apiClient.defaults.adapter;
afterEach(() => {
  apiClient.defaults.adapter = originalAdapter;
  setApiAccountScope(undefined);
  lookup = undefined;
  session = { access_token: 'A-token', user: { id: 'A' } };
});

test('an A1 operation dispatched after awaited onMutate cannot acquire B or A2 credentials', async () => {
  const outgoing = new AbortController();
  const oldApi = createAccountApi({ userId: 'A', signal: outgoing.signal });
  let dispatches = 0;
  apiClient.defaults.adapter = async (config) => {
    dispatches++;
    return { config, data: {}, headers: {}, status: 200, statusText: 'OK' };
  };
  for (const userId of ['B', 'A']) {
    outgoing.abort();
    session = { access_token: `${userId}-new-token`, user: { id: userId } };
    setApiAccountScope({ userId, signal: new AbortController().signal });
    await expect(oldApi.agents.start('agent-A')).rejects.toMatchObject({ code: 'ERR_CANCELED' });
  }
  expect(dispatches).toBe(0);
});

test('an account change during token lookup aborts before network dispatch', async () => {
  const outgoing = new AbortController();
  const oldApi = createAccountApi({ userId: 'A', signal: outgoing.signal });
  let resolve!: (value: { data: { session: Session }; error: null }) => void;
  let entered!: () => void;
  const started = new Promise<void>((done) => { entered = done; });
  lookup = () => { entered(); return new Promise((done) => { resolve = done; }); };
  let dispatches = 0;
  apiClient.defaults.adapter = async (config) => {
    dispatches++;
    return { config, data: {}, headers: {}, status: 200, statusText: 'OK' };
  };
  const result = oldApi.agents.list();
  await started;
  outgoing.abort();
  session = { access_token: 'B-token', user: { id: 'B' } };
  resolve({ data: { session }, error: null });
  await expect(result).rejects.toMatchObject({ code: 'ERR_CANCELED' });
  expect(dispatches).toBe(0);
});

test('a late A 401 cannot navigate the active B session', async () => {
  const outgoing = new AbortController();
  let fail!: () => void;
  let entered!: () => void;
  const started = new Promise<void>((done) => { entered = done; });
  apiClient.defaults.adapter = (config: InternalAxiosRequestConfig) => {
    entered();
    return new Promise((_resolve, reject) => {
      fail = () => reject(new AxiosError('unauthorized', '401', config, undefined, {
        config, data: {}, headers: {}, status: 401, statusText: 'Unauthorized',
      }));
    });
  };
  const before = window.location.href;
  const result = createAccountApi({ userId: 'A', signal: outgoing.signal }).agents.list();
  await started;
  outgoing.abort();
  session = { access_token: 'B-token', user: { id: 'B' } };
  setApiAccountScope({ userId: 'B', signal: new AbortController().signal });
  fail();
  await expect(result).rejects.toMatchObject({ code: 'ERR_CANCELED' });
  expect(window.location.href).toBe(before);
});
