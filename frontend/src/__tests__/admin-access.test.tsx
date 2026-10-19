import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState, type ReactNode } from 'react';
import type {
  AdminIdentity,
  AdminPage,
  AdminPresetDetail,
  AdminUserSummary,
} from '@/types/admin';

interface FakeSession {
  access_token: string;
  user: { id: string };
}

type AuthListener = (event: string, session: FakeSession | null) => void;

const authListeners = new Set<AuthListener>();
let activeSession: FakeSession | null = null;
let initialAdmin = true;

const fakeSupabase = {
  auth: {
    getSession: async () => ({ data: { session: activeSession }, error: null }),
    onAuthStateChange: (callback: AuthListener) => {
      authListeners.add(callback);
      queueMicrotask(() => callback('INITIAL_SESSION', activeSession));
      return {
        data: {
          subscription: {
            unsubscribe: () => authListeners.delete(callback),
          },
        },
      };
    },
  },
};

// Mock the browser client before loading modules that capture its singleton.
mock.module('@/lib/supabase/client', () => ({
  getSupabaseClient: () => fakeSupabase,
}));

const { adminApi } = await import('@/lib/adminApi');
const { AdminAccessProvider, useAdminAccess } = await import('@/hooks/useAdminAccess');
const { useAdminActions, useAdminUsers } = await import('@/hooks/useAdmin');
const { queryKeys } = await import('@/lib/queryClient');

const userA = '11111111-1111-1111-1111-111111111111';
const userB = '22222222-2222-2222-2222-222222222222';

function session(userId: string): FakeSession {
  return { access_token: `token-${userId}`, user: { id: userId } };
}

function emptyPage(): AdminPage<AdminUserSummary> {
  return { items: [], total: 0, page: 1, page_size: 25 };
}

function Probe() {
  const access = useAdminAccess();
  const users = useAdminUsers('', 1);
  return (
    <>
      <output data-testid="access">
        {`${access.userId ?? 'none'}:${access.isLoading ? 'loading' : access.isAdmin ? 'admin' : 'denied'}`}
      </output>
      <output data-testid="users">{users.isFetching ? 'fetching' : users.data ? 'loaded' : 'idle'}</output>
    </>
  );
}

function WriteProbe() {
  const actions = useAdminActions();
  const access = useAdminAccess();
  const [saved, setSaved] = useState(false);
  return (
    <>
      <output data-testid="access">
        {`${access.userId ?? 'none'}:${access.isLoading ? 'loading' : access.isAdmin ? 'admin' : 'denied'}`}
      </output>
      <button
        type="button"
        onClick={() => {
          void actions
            .saveTelegramSettings({ api_id: 12345, api_hash: 'write-only-test-hash' })
            .then(() => setSaved(true));
        }}
      >
        Save Telegram settings
      </button>
      <output data-testid="write-state">{saved ? 'saved' : 'idle'}</output>
    </>
  );
}

function PresetWriteProbe() {
  const actions = useAdminActions();
  const access = useAdminAccess();
  const [saved, setSaved] = useState(false);
  return (
    <>
      <output data-testid="access">
        {`${access.userId ?? 'none'}:${access.isLoading ? 'loading' : access.isAdmin ? 'admin' : 'denied'}`}
      </output>
      <button
        type="button"
        onClick={() => {
          void actions
            .createPreset({ title: 'Preset', summary: 'Summary', body: 'Private body' })
            .then(() => setSaved(true));
        }}
      >
        Create preset
      </button>
      <output data-testid="preset-write-state">{saved ? 'saved' : 'idle'}</output>
    </>
  );
}

function renderProbe(children: ReactNode = <Probe />) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <AdminAccessProvider>
        {children}
      </AdminAccessProvider>
    </QueryClientProvider>,
  );
  return { queryClient, ...view };
}

function emitAuth(event: string, nextSession: FakeSession | null) {
  activeSession = nextSession;
  for (const listener of [...authListeners]) listener(event, nextSession);
}

let meCalls = 0;
let usersCalls = 0;
let usersSignals: (AbortSignal | undefined)[];
let meBehavior: () => Promise<AdminIdentity>;
let usersBehavior: () => Promise<AdminPage<AdminUserSummary>>;
const originalMe = adminApi.me;
const originalUsers = adminApi.users;
const originalSaveTelegramSettings = adminApi.saveTelegramSettings;
const originalCreatePreset = adminApi.createPreset;

beforeEach(() => {
  activeSession = null;
  initialAdmin = true;
  authListeners.clear();
  meCalls = 0;
  usersCalls = 0;
  usersSignals = [];
  meBehavior = async () => ({
    user_id: activeSession?.user.id ?? userA,
    is_admin: initialAdmin,
  });
  usersBehavior = async () => emptyPage();
  adminApi.me = async () => {
    meCalls += 1;
    return meBehavior();
  };
  adminApi.users = async (_params, options) => {
    usersCalls += 1;
    usersSignals.push(options?.signal);
    return usersBehavior();
  };
  adminApi.saveTelegramSettings = originalSaveTelegramSettings;
  adminApi.createPreset = originalCreatePreset;
});

afterEach(() => {
  cleanup();
  adminApi.me = originalMe;
  adminApi.users = originalUsers;
  adminApi.saveTelegramSettings = originalSaveTelegramSettings;
  adminApi.createPreset = originalCreatePreset;
  authListeners.clear();
});

afterAll(() => mock.restore());

describe('admin access boundary state', () => {
  test('uses user-scoped keys and writes do not enter the mutation cache', async () => {
    activeSession = session(userA);
    meBehavior = async () => ({ user_id: userA, is_admin: true });
    const saved: Array<{ api_id: number; api_hash: string }> = [];
    adminApi.saveTelegramSettings = async (values) => {
      saved.push(values);
      return {
        api_id: values.api_id,
        has_api_hash: true,
        source: 'database',
        updated_at: null,
        updated_by: userA,
      };
    };
    const view = renderProbe(<WriteProbe />);
    const telegramKey = queryKeys.admin.telegram(userA);
    view.queryClient.setQueryData(telegramKey, {
      api_id: 1,
      has_api_hash: true,
      source: 'environment',
      updated_at: null,
      updated_by: null,
    });

    await waitFor(() => expect(screen.getByTestId('access').textContent).toBe(`${userA}:admin`));
    fireEvent.click(screen.getByRole('button', { name: 'Save Telegram settings' }));
    await waitFor(() => expect(screen.getByTestId('write-state').textContent).toBe('saved'));

    expect(saved).toEqual([{ api_id: 12345, api_hash: 'write-only-test-hash' }]);
    expect(view.queryClient.getQueryCache().find({ queryKey: telegramKey })?.state.isInvalidated).toBe(
      true,
    );
    expect(view.queryClient.getMutationCache().getAll()).toEqual([]);
    expect(
      JSON.stringify(view.queryClient.getQueryCache().getAll().map((query) => query.state.data)),
    ).not.toContain('write-only-test-hash');
    expect(queryKeys.admin.scope(userA)).not.toEqual(queryKeys.admin.scope(userB));
  });

  test('preset writes invalidate user-scoped admin and catalog queries directly', async () => {
    activeSession = session(userA);
    meBehavior = async () => ({ user_id: userA, is_admin: true });
    const preset: AdminPresetDetail = {
      id: 'preset-id',
      owner_id: null,
      owner_name: null,
      title: 'Preset',
      summary: 'Summary',
      sort_order: 0,
      is_active: true,
      published_at: null,
      updated_at: '2026-10-19T10:00:00Z',
      body: 'Private body',
      settings: null,
    };
    adminApi.createPreset = async () => preset;
    const view = renderProbe(<PresetWriteProbe />);
    const adminUsersKey = queryKeys.admin.users(userA, '', 1, 25);
    const catalogKey = queryKeys.presets.list();
    view.queryClient.setQueryData(adminUsersKey, { total: 0 });
    view.queryClient.setQueryData(catalogKey, []);

    await waitFor(() => expect(screen.getByTestId('access').textContent).toBe(`${userA}:admin`));
    fireEvent.click(screen.getByRole('button', { name: 'Create preset' }));
    await waitFor(() => expect(screen.getByTestId('preset-write-state').textContent).toBe('saved'));

    expect(view.queryClient.getQueryCache().find({ queryKey: adminUsersKey })?.state.isInvalidated).toBe(
      true,
    );
    expect(view.queryClient.getQueryCache().find({ queryKey: catalogKey })?.state.isInvalidated).toBe(
      true,
    );
    expect(view.queryClient.getMutationCache().getAll()).toEqual([]);
    expect(JSON.stringify(view.queryClient.getQueryCache().getAll())).not.toContain('Private body');
  });

  test('does not run protected reads until /me confirms the role', async () => {
    activeSession = session(userA);
    let resolveIdentity: ((identity: AdminIdentity) => void) | undefined;
    meBehavior = () => new Promise<AdminIdentity>((resolve) => (resolveIdentity = resolve));
    renderProbe();

    await waitFor(() => expect(meCalls).toBe(1));
    expect(usersCalls).toBe(0);

    await act(async () => {
      resolveIdentity?.({ user_id: userA, is_admin: false });
    });

    await waitFor(() => expect(screen.getByTestId('access').textContent).toBe(`${userA}:denied`));
    expect(usersCalls).toBe(0);
  });

  test('cancels and removes the previous user data on sign-out and account switch', async () => {
    activeSession = session(userA);
    meBehavior = async () => ({
      user_id: activeSession?.user.id ?? userA,
      is_admin: true,
    });
    const view = renderProbe();
    const oldUsersKey = queryKeys.admin.users(userA, '', 1, 25);
    const oldPresetKey = queryKeys.admin.preset(userA, 'cached-preset');

    await waitFor(() =>
      expect(view.queryClient.getQueryData<AdminPage<AdminUserSummary>>(oldUsersKey)).toEqual(
        emptyPage(),
      ),
    );
    view.queryClient.setQueryData(oldPresetKey, { body: 'old private prompt' });
    expect(usersCalls).toBe(1);
    expect(typeof usersSignals[0]?.addEventListener).toBe('function');

    act(() => emitAuth('SIGNED_OUT', null));
    await waitFor(() => expect(screen.getByTestId('access').textContent).toBe('none:denied'));
    await waitFor(() => expect(view.queryClient.getQueryData(oldUsersKey)).toBeUndefined());
    expect(view.queryClient.getQueryData(oldPresetKey)).toBeUndefined();
    expect(view.queryClient.getQueryData(queryKeys.identity(userA))).toBeUndefined();

    act(() => emitAuth('SIGNED_IN', session(userB)));
    await waitFor(() => expect(screen.getByTestId('access').textContent).toBe(`${userB}:admin`));
    await waitFor(() =>
      expect(
        view.queryClient.getQueryData<AdminPage<AdminUserSummary>>(
          queryKeys.admin.users(userB, '', 1, 25),
        ),
      ).toEqual(emptyPage()),
    );
    expect(view.queryClient.getQueryData(oldUsersKey)).toBeUndefined();
    expect(meCalls).toBe(2);
    expect(usersCalls).toBe(2);
  });

  test('a 403 revokes access, clears protected cache, and is not retried', async () => {
    activeSession = session(userA);
    meBehavior = async () => ({ user_id: userA, is_admin: true });
    usersBehavior = async () => {
      throw { status: 403, message: 'forbidden' };
    };
    const view = renderProbe();

    await waitFor(() => expect(screen.getByTestId('access').textContent).toBe(`${userA}:denied`));

    expect(usersCalls).toBe(1);
    expect(view.queryClient.getQueryData(queryKeys.admin.users(userA, '', 1, 25))).toBeUndefined();
    expect(view.queryClient.getQueryData(queryKeys.identity(userA))).toMatchObject({
      user_id: userA,
      is_admin: false,
    });
  });
});
