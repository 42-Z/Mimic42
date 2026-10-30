import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { adminApi } from '@/lib/adminApi';
import { AdminAccessContext, type AdminAccess } from '@/hooks/useAdminAccess';
import { AdminUsers } from '@/components/admin/AdminUsers';
import type { AdminPage, AdminUserDetail, AdminUserSummary } from '@/types/admin';

const adminId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const noAgentUserId = '11111111-1111-4111-8111-111111111111';
const multiAgentUserId = '22222222-2222-4222-8222-222222222222';
const initialUrl = window.location.href;

const access: AdminAccess = {
  userId: adminId,
  isLoading: false,
  isAdmin: true,
  isDenied: false,
  error: null,
  retry: () => undefined,
};

const now = '2026-10-18T12:00:00Z';

function userSummary(
  userId: string,
  overrides: Partial<AdminUserSummary> = {},
): AdminUserSummary {
  return {
    user_id: userId,
    email: null,
    display_name: null,
    created_at: now,
    agents_total: 0,
    states: {},
    ...overrides,
  };
}

function userPage(
  items: AdminUserSummary[],
  page = 1,
  total = items.length,
  pageSize = 25,
): AdminPage<AdminUserSummary> {
  return { items, total, page, page_size: pageSize };
}

function userDetail(
  profile: AdminUserSummary,
  agents: AdminUserDetail['agents'] = { items: [], total: 0, page: 1, page_size: 5 },
): AdminUserDetail {
  return { profile, agents };
}

function setUrl(search = '') {
  const happyDomWindow = window as Window & { happyDOM?: { setURL: (url: string) => void } };
  happyDomWindow.happyDOM?.setURL(`http://localhost:3000/admin/users${search}`);
}

function renderUsers() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <AdminAccessContext.Provider value={access}>
        <AdminUsers />
      </AdminAccessContext.Provider>
    </QueryClientProvider>,
  );
  return { queryClient, ...view };
}

const originalUsers = adminApi.users;
const originalUser = adminApi.user;
let listCalls: Array<{ q: string; page: number; page_size?: number }>;
let detailCalls: Array<{ userId: string; page: number; page_size?: number }>;
let loadUsers: (params: {
  q: string;
  page: number;
  page_size?: number;
}) => Promise<AdminPage<AdminUserSummary>>;
let loadUser: (
  userId: string,
  params: { page: number; page_size?: number },
) => Promise<AdminUserDetail>;

beforeEach(() => {
  listCalls = [];
  detailCalls = [];
  setUrl();
  loadUsers = async () => userPage([]);
  loadUser = async () => userDetail(userSummary(noAgentUserId));
  adminApi.users = async (params) => {
    listCalls.push(params);
    return loadUsers(params);
  };
  adminApi.user = async (userId, params) => {
    detailCalls.push({ userId, ...params });
    return loadUser(userId, params);
  };
});

afterEach(() => {
  cleanup();
  adminApi.users = originalUsers;
  adminApi.user = originalUser;
  const happyDomWindow = window as Window & { happyDOM?: { setURL: (url: string) => void } };
  happyDomWindow.happyDOM?.setURL(initialUrl);
});

describe('AdminUsers', () => {
  test('shows missing profile values and users without agents without inventing actions', async () => {
    loadUsers = async () =>
      userPage([
        userSummary(noAgentUserId),
        userSummary('33333333-3333-4333-8333-333333333333', {
          email: 'active@example.test',
          display_name: 'Рабочий профиль',
          agents_total: 2,
          states: { running: 1, stopped: 1 },
        }),
      ]);
    loadUser = async () => userDetail(userSummary(noAgentUserId));
    renderUsers();

    expect(await screen.findByText('Без имени')).toBeTruthy();
    expect(screen.getByText('Не указан')).toBeTruthy();
    expect(screen.getByText('АКТИВЕН')).toBeTruthy();
    expect(screen.getByText('ОСТАНОВЛЕН')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Мимики (0)' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Запустить|Остановить|Удалить/ })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Мимики (0)' }));
    expect(await screen.findByText('У пользователя пока нет мимиков')).toBeTruthy();
    expect(detailCalls).toEqual([{ userId: noAgentUserId, page: 1, page_size: 5 }]);
  });

  test('debounces search, hides old results, resets pagination, and persists q/page in the URL', async () => {
    setUrl('?q=old&page=3');
    expect(window.location.search).toBe('?q=old&page=3');
    loadUsers = async ({ q, page, page_size = 25 }) => {
      if (q === 'old') {
        return userPage(
          [userSummary(noAgentUserId, { display_name: 'Старая запись' })],
          page,
          60,
          page_size,
        );
      }
      return userPage(
        [userSummary(multiAgentUserId, { display_name: 'Новая запись' })],
        page,
        1,
        page_size,
      );
    };
    renderUsers();

    expect(await screen.findByText('Старая запись')).toBeTruthy();
    expect(listCalls[0]).toMatchObject({ q: 'old', page: 3 });
    const input = screen.getByRole('searchbox', { name: 'Поиск пользователей' });
    fireEvent.change(input, { target: { value: 'new' } });

    expect(screen.queryByText('Старая запись')).toBeNull();
    expect(listCalls).toHaveLength(1);
    await waitFor(() => expect(listCalls.some((call) => call.q === 'new' && call.page === 1)).toBe(true));
    expect(await screen.findByText('Новая запись')).toBeTruthy();
    expect(new URLSearchParams(window.location.search).get('q')).toBe('new');
    expect(new URLSearchParams(window.location.search).get('page')).toBeNull();
  });

  test('shows a recoverable error without rendering a false zero count', async () => {
    let fail = true;
    loadUsers = async () => {
      if (fail) throw new Error('private query details');
      return userPage([]);
    };
    renderUsers();

    expect((await screen.findByRole('alert')).textContent).toContain('Не удалось загрузить пользователей');
    expect(screen.queryByText('Всего: 0')).toBeNull();
    expect(screen.getByRole('alert').textContent).not.toContain('private query details');

    fail = false;
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByText('Пользователей пока нет')).toBeTruthy();
  });

  test('opens minimal user details and paginates agents without exposing private settings', async () => {
    const profile = userSummary(multiAgentUserId, {
      email: 'owner@example.test',
      display_name: 'Владелец',
      agents_total: 6,
      states: { stopped: 5, running: 1 },
    });
    const agentRecords = Array.from({ length: 6 }, (_, index) => ({
      agent_id: `agent-${index + 1}`,
      name: `Мимик ${index + 1}`,
      llm_model: 'openrouter/test-model',
      state: index === 5 ? ('running' as const) : ('stopped' as const),
    }));
    loadUsers = async () => userPage([profile]);
    loadUser = async (_userId, params) =>
      userDetail(profile, {
        items: params.page === 1 ? agentRecords.slice(0, 5) : agentRecords.slice(5),
        total: agentRecords.length,
        page: params.page,
        page_size: params.page_size ?? 5,
      });
    renderUsers();

    expect(await screen.findByRole('button', { name: 'Мимики (6)' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Мимики (6)' }));
    const dialog = await screen.findByRole('dialog', { name: 'Мимики пользователя' });
    expect(within(dialog).getByText('Владелец')).toBeTruthy();
    expect(within(dialog).getByText('owner@example.test')).toBeTruthy();
    expect(within(dialog).getByText('Мимик 1')).toBeTruthy();
    expect(within(dialog).queryByText('Мимик 6')).toBeNull();
    expect(detailCalls[0]).toMatchObject({ userId: multiAgentUserId, page: 1, page_size: 5 });

    fireEvent.click(within(dialog).getByRole('button', { name: 'Следующая страница' }));
    expect(await within(dialog).findByText('Мимик 6')).toBeTruthy();
    expect(detailCalls.at(-1)).toMatchObject({ userId: multiAgentUserId, page: 2, page_size: 5 });
    expect(document.body.textContent).not.toContain('soul_prompt');
    expect(document.body.textContent).not.toContain('session_string');
    expect(document.body.textContent).not.toContain('api_hash');
    expect(screen.queryByRole('button', { name: /Запустить|Остановить|Удалить/ })).toBeNull();
    expect(screen.queryByRole('link', { name: /Управлять агентом/ })).toBeNull();
  });
});
