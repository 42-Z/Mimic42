import { afterEach, beforeEach, expect, mock, spyOn, test } from 'bun:test';
import { updateAccountPassword } from '@/lib/updatePassword';

type Session = { access_token: string; user: { id: string } };
const ownerSession: Session = { access_token: 'A-token', user: { id: 'A' } };
const nextSession: Session = { access_token: 'B-token', user: { id: 'B' } };
const previousUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const previousKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function authState() {
  const storage = { session: ownerSession };
  const events: string[] = [];
  const auth = {
    getSession: mock(async () => ({ data: { session: storage.session }, error: null })),
    updateUser: mock(async () => {
      storage.session = ownerSession;
      events.push('USER_UPDATED');
      return { data: { user: ownerSession.user }, error: null };
    }),
  };
  return { auth, storage, events };
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://project.supabase.co/';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'public-anon-key';
});

afterEach(() => {
  mock.restore();
  if (previousUrl === undefined) delete process.env.NEXT_PUBLIC_SUPABASE_URL;
  else process.env.NEXT_PUBLIC_SUPABASE_URL = previousUrl;
  if (previousKey === undefined) delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  else process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = previousKey;
});

test('late A response cannot overwrite B auth storage or emit USER_UPDATED', async () => {
  const { auth, storage, events } = authState();
  const controller = new AbortController();
  const entered = deferred<void>();
  const response = deferred<Response>();
  const request = spyOn(globalThis, 'fetch').mockImplementation(Object.assign(
    async (_url: RequestInfo | URL, options?: RequestInit) => {
      expect(options?.signal).toBe(controller.signal);
      entered.resolve();
      return response.promise;
    },
    { preconnect: () => undefined },
  ));
  const result = updateAccountPassword('new-password', {
    userId: 'A', signal: controller.signal,
  }, auth);
  await entered.promise;
  storage.session = nextSession;
  events.push('SIGNED_IN');
  controller.abort();
  response.resolve(Response.json({ ...ownerSession.user, updated_at: 'later' }));
  await expect(result).rejects.toMatchObject({ name: 'AbortError' });
  expect(storage.session).toBe(nextSession);
  expect(events).toEqual(['SIGNED_IN']);
  expect(auth.updateUser).not.toHaveBeenCalled();
  expect(request).toHaveBeenCalledTimes(1);
});

test('B credentials returned during async lookup are never sent for owner A', async () => {
  const controller = new AbortController();
  const lookup = deferred<{ data: { session: Session }; error: null }>();
  const request = spyOn(globalThis, 'fetch');
  const result = updateAccountPassword('new-password', {
    userId: 'A', signal: controller.signal,
  }, { getSession: () => lookup.promise });
  lookup.resolve({ data: { session: nextSession }, error: null });
  await expect(result).rejects.toMatchObject({ name: 'AbortError' });
  expect(request).not.toHaveBeenCalled();
});

test('retired generation cannot send even if lookup returns the same owner', async () => {
  const controller = new AbortController();
  const lookup = deferred<{ data: { session: Session }; error: null }>();
  const request = spyOn(globalThis, 'fetch');
  const result = updateAccountPassword('new-password', {
    userId: 'A', signal: controller.signal,
  }, { getSession: () => lookup.promise });
  controller.abort();
  lookup.resolve({ data: { session: ownerSession }, error: null });
  await expect(result).rejects.toMatchObject({ name: 'AbortError' });
  expect(request).not.toHaveBeenCalled();
});

test('already aborted scope does not look up a session', async () => {
  const { auth } = authState();
  const controller = new AbortController();
  controller.abort();
  await expect(updateAccountPassword('new-password', {
    userId: 'A', signal: controller.signal,
  }, auth)).rejects.toMatchObject({ name: 'AbortError' });
  expect(auth.getSession).not.toHaveBeenCalled();
});

test('password change sends only the captured owner token and leaves auth untouched', async () => {
  const { auth, storage, events } = authState();
  const controller = new AbortController();
  const request = spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ id: 'A' }));
  await updateAccountPassword('new-password', { userId: 'A', signal: controller.signal }, auth);
  expect(request).toHaveBeenCalledWith('https://project.supabase.co/auth/v1/user', {
    method: 'PUT',
    headers: {
      apikey: 'public-anon-key',
      Authorization: 'Bearer A-token',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ password: 'new-password' }),
    signal: controller.signal,
    credentials: 'omit',
    redirect: 'error',
  });
  expect(storage.session).toBe(ownerSession);
  expect(events).toEqual([]);
  expect(auth.updateUser).not.toHaveBeenCalled();
});

test('Supabase password rejection is reported without auth changes', async () => {
  const { auth, storage, events } = authState();
  spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({
    code: 422, error_code: 'weak_password', msg: 'Password is too weak',
  }, { status: 422 }));
  await expect(updateAccountPassword('new-password', {
    userId: 'A', signal: new AbortController().signal,
  }, auth)).rejects.toThrow('Password is too weak');
  expect(storage.session).toBe(ownerSession);
  expect(events).toEqual([]);
});

test('non-JSON gateway failure has a safe password error', async () => {
  const { auth } = authState();
  spyOn(globalThis, 'fetch').mockResolvedValue(new Response('<html>Bad Gateway</html>', {
    status: 502, headers: { 'content-type': 'text/html' },
  }));
  await expect(updateAccountPassword('new-password', {
    userId: 'A', signal: new AbortController().signal,
  }, auth)).rejects.toThrow('Не удалось обновить пароль. Попробуйте снова.');
});

test('missing session cannot dispatch a password request', async () => {
  const request = spyOn(globalThis, 'fetch');
  await expect(updateAccountPassword('new-password', {
    userId: 'A', signal: new AbortController().signal,
  }, { getSession: async () => ({ data: { session: null }, error: null }) }))
    .rejects.toMatchObject({ name: 'AbortError' });
  expect(request).not.toHaveBeenCalled();
});

test('session lookup error cannot dispatch a password request', async () => {
  const request = spyOn(globalThis, 'fetch');
  await expect(updateAccountPassword('new-password', {
    userId: 'A', signal: new AbortController().signal,
  }, {
    getSession: async () => ({ data: { session: null }, error: { message: 'Session expired' } }),
  })).rejects.toThrow('Session expired');
  expect(request).not.toHaveBeenCalled();
});

test('network failure is returned to the password form without modifying auth', async () => {
  const { auth, storage, events } = authState();
  spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));
  await expect(updateAccountPassword('new-password', {
    userId: 'A', signal: new AbortController().signal,
  }, auth)).rejects.toThrow('Failed to fetch');
  expect(storage.session).toBe(ownerSession);
  expect(events).toEqual([]);
  expect(auth.updateUser).not.toHaveBeenCalled();
});
