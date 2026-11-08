import { afterEach, expect, mock, spyOn, test } from 'bun:test';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createClient, type Session, type SupabaseClient } from '@supabase/supabase-js';
import { navigationMock } from './next-navigation-mock';

let client: SupabaseClient;
mock.module('@/lib/supabase/client', () => ({ getSupabaseClient: () => client }));
const { AccountProvider, useAccount } = await import('@/hooks/useAccount');
const { Sidebar } = await import('@/components/layout/Sidebar');
const { AdminAccessContext } = await import('@/hooks/useAdminAccess');
const { apiClient } = await import('@/lib/api');
const originalAdapter = apiClient.defaults.adapter;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

test.each(['success', 'rejected', 'network-error'] as const)(
  'sidebar logout clears A locally before a late %s and cannot affect B',
  async (outcome) => {
    const storageKey = `auth-logout-${crypto.randomUUID()}`;
    const storage = new Map<string, string>();
    const logoutStarted = deferred<void>();
    const logoutResponse = deferred<Response>();
    client = createClient('https://auth-race.example.com', 'test-public-key', {
      auth: {
        storageKey,
        storage: {
          getItem: (key) => storage.get(key) ?? null,
          setItem: (key, value) => { storage.set(key, value); },
          removeItem: (key) => { storage.delete(key); },
        },
        autoRefreshToken: false,
        persistSession: true,
        detectSessionInUrl: false,
      },
      global: {
        fetch: Object.assign(async (input: RequestInfo | URL, init?: RequestInit) => {
          const url = new URL(String(input));
          if (url.pathname.endsWith('/logout')) {
            expect(url.searchParams.get('scope')).toBe('local');
            expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${logoutToken}`);
            logoutStarted.resolve();
            await logoutResponse.promise;
            if (outcome === 'network-error') throw new TypeError('Offline');
            return logoutResponse.promise;
          }
          if (url.searchParams.get('grant_type') === 'password') {
            const { email } = JSON.parse(String(init?.body));
            return Response.json(authSession(email.split('@')[0]));
          }
          throw new Error(`Unexpected auth request: ${url.pathname}`);
        }, { preconnect: () => undefined }),
      },
    });
    await client.auth.initialize();
    const logoutToken = (await client.auth.signInWithPassword({ email: 'A@example.com', password: 'test' })).data.session?.access_token;
    navigationMock.pathname = '/dashboard';
    const signOut = spyOn(client.auth, 'signOut');
    apiClient.defaults.adapter = async (config) => ({
      config, data: [], headers: {}, status: 200, statusText: 'OK',
    });
    render(<AccountProvider>
      <AdminAccessContext.Provider value={{ userId: 'A', isAdmin: false, isLoading: false, isDenied: false, error: null, retry: () => {} }}>
        <Sidebar /><AccountProbe />
      </AdminAccessContext.Provider>
    </AccountProvider>);
    await waitFor(() => expect(screen.queryByText('A@example.com')).not.toBeNull());

    fireEvent.click(screen.getByRole('button', { name: 'Выйти' }));
    await act(async () => { await logoutStarted.promise; });
    expect(storage.has(storageKey)).toBe(false);
    expect(screen.queryByText('A@example.com')).toBeNull();
    expect(navigationMock.replace).toHaveBeenCalledWith('/login?redirect=%2Fdashboard');

    await act(async () => {
      await client.auth.signInWithPassword({ email: 'B@example.com', password: 'test' });
    });
    expect(screen.queryByText('B@example.com')).not.toBeNull();
    navigationMock.replace.mockClear();
    navigationMock.push.mockClear();

    await act(async () => {
      logoutResponse.resolve(outcome === 'success'
        ? new Response(null, { status: 204 })
        : Response.json({ message: 'Unavailable' }, { status: 503 }));
      await signOut.mock.results[0]?.value;
    });

    expect(JSON.parse(storage.get(storageKey)!).user.id).toBe('B');
    expect((await client.auth.getSession()).data.session?.user.id).toBe('B');
    expect(screen.queryByText('B@example.com')).not.toBeNull();
    expect(navigationMock.replace).not.toHaveBeenCalled();
    expect(navigationMock.push).not.toHaveBeenCalled();
    signOut.mockRestore();
  },
);

function authSession(id: string, refreshToken = `refresh-${id}`): Session {
  const expiresAt = Math.floor(Date.now() / 1000) + 3600;
  const payload = btoa(JSON.stringify({ sub: id, exp: expiresAt, session_id: `session-${id}` }));
  return {
    access_token: `eyJhbGciOiJIUzI1NiJ9.${payload}.c2lnbmF0dXJl`,
    refresh_token: refreshToken,
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: expiresAt,
    user: {
      id,
      email: `${id}@example.com`,
      aud: 'authenticated',
      app_metadata: {},
      user_metadata: {},
      created_at: '2026-01-01T00:00:00Z',
    },
  };
}

function AccountProbe() {
  const account = useAccount();
  return <output>{account?.user?.email}</output>;
}

afterEach(() => {
  cleanup();
  client?.auth.dispose();
  apiClient.defaults.adapter = originalAdapter;
});

for (const mode of ['getSession', 'refreshSession'] as const) {
  test.each(['success', 'rejected'] as const)(
    `${mode}: late %s of A cannot replace or remove B in storage or UI`,
    async (outcome) => {
      const storageKey = `auth-refresh-${crypto.randomUUID()}`;
      const storage = new Map<string, string>();
      const refreshStarted = deferred<void>();
      const refreshResponse = deferred<Response>();
      const events: string[] = [];
      client = createClient('https://auth-race.example.com', 'test-public-key', {
        auth: {
          storageKey,
          storage: {
            getItem: (key) => storage.get(key) ?? null,
            setItem: (key, value) => { storage.set(key, value); },
            removeItem: (key) => { storage.delete(key); },
          },
          autoRefreshToken: false,
          persistSession: true,
          detectSessionInUrl: false,
        },
        global: {
          fetch: Object.assign(async (input: RequestInfo | URL, init?: RequestInit) => {
            const url = new URL(String(input));
            if (url.searchParams.get('grant_type') === 'refresh_token') {
              refreshStarted.resolve();
              return refreshResponse.promise;
            }
            if (url.searchParams.get('grant_type') === 'password') {
              const { email } = JSON.parse(String(init?.body));
              return Response.json(authSession(email.split('@')[0]));
            }
            throw new Error(`Unexpected auth request: ${url.pathname}`);
          }, { preconnect: () => undefined }),
        },
      });
      await client.auth.initialize();
      expect((await client.auth.signInWithPassword({ email: 'A@example.com', password: 'test' })).error).toBeNull();
      client.auth.onAuthStateChange((event, session) => { events.push(`${event}:${session?.user.id}`); });
      navigationMock.pathname = '/dashboard';
      render(<AccountProvider><AccountProbe /></AccountProvider>);
      await waitFor(() => expect(screen.queryByText('A@example.com')).not.toBeNull());

      if (mode === 'getSession') {
        const expired = { ...authSession('A'), expires_at: Math.floor(Date.now() / 1000) - 1 };
        storage.set(storageKey, JSON.stringify(expired));
      }
      const refreshing = mode === 'getSession' ? client.auth.getSession() : client.auth.refreshSession();
      await refreshStarted.promise;
      await act(async () => {
        expect((await client.auth.signInWithPassword({ email: 'B@example.com', password: 'test' })).error).toBeNull();
      });
      expect(screen.queryByText('B@example.com')).not.toBeNull();
      events.length = 0;

      await act(async () => {
        refreshResponse.resolve(outcome === 'success'
          ? Response.json(authSession('A', 'rotated-refresh-A'))
          : Response.json({ code: 'refresh_token_not_found', msg: 'Revoked refresh token' }, { status: 400 }));
        await refreshing;
      });

      expect(JSON.parse(storage.get(storageKey)!).user.id).toBe('B');
      expect((await client.auth.getSession()).data.session?.user.id).toBe('B');
      expect(screen.queryByText('B@example.com')).not.toBeNull();
      expect(screen.queryByText('A@example.com')).toBeNull();
      expect(events).not.toContain('TOKEN_REFRESHED:A');
      expect(events).not.toContain('SIGNED_OUT:undefined');
    },
  );
}
