import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { AdminProxies } from '@/components/admin/AdminProxies';
import { ToastProvider } from '@/components/ui/toast';
import { AdminAccessContext, type AdminAccess } from '@/hooks/useAdminAccess';
import { adminApi } from '@/lib/adminApi';
import type {
  AdminPage,
  AdminProxyDetail,
  AdminProxyInput,
  AdminProxySummary,
  UpdateAdminProxy,
} from '@/types/admin';

const adminId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const now = '2026-10-30T12:00:00Z';

const access: AdminAccess = {
  userId: adminId,
  isLoading: false,
  isAdmin: true,
  isDenied: false,
  error: null,
  retry: () => undefined,
};

function proxySummary(overrides: Partial<AdminProxySummary> = {}): AdminProxySummary {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    label: 'Основной',
    protocol: 'socks5',
    host: 'proxy.example.test',
    port: 1080,
    username: 'mimic',
    has_password: true,
    is_active: true,
    agents_total: 0,
    onboarding_total: 0,
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

function proxyPage(proxies: AdminProxySummary[]): AdminPage<AdminProxySummary> {
  return { items: proxies, total: proxies.length, page: 1, page_size: 25 };
}

function renderProxies() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AdminAccessContext.Provider value={access}>
          <AdminProxies />
        </AdminAccessContext.Provider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

const originalProxies = adminApi.proxies;
const originalCreate = adminApi.createProxy;
const originalUpdate = adminApi.updateProxy;
const originalDelete = adminApi.deleteProxy;
const originalCheck = adminApi.checkProxy;
let listCalls: Array<{ page: number; page_size?: number }>;
let createCalls: AdminProxyInput[];
let updateCalls: Array<{ proxyId: string; values: UpdateAdminProxy }>;
let deleteCalls: string[];
let checkCalls: string[];
let loadProxies: () => Promise<AdminPage<AdminProxySummary>>;
let deleteError: unknown;

beforeEach(() => {
  listCalls = [];
  createCalls = [];
  updateCalls = [];
  deleteCalls = [];
  checkCalls = [];
  deleteError = null;
  loadProxies = async () => proxyPage([]);
  adminApi.proxies = async (params) => {
    listCalls.push(params);
    return loadProxies();
  };
  adminApi.createProxy = async (values) => {
    createCalls.push(values);
    return { ...proxySummary(), ...values, created_by: adminId } as AdminProxyDetail;
  };
  adminApi.updateProxy = async (proxyId, values) => {
    updateCalls.push({ proxyId, values });
    return { ...proxySummary({ id: proxyId }), ...values, created_by: adminId } as AdminProxyDetail;
  };
  adminApi.deleteProxy = async (proxyId) => {
    deleteCalls.push(proxyId);
    if (deleteError) throw deleteError;
    return undefined as never;
  };
  adminApi.checkProxy = async (proxyId) => {
    checkCalls.push(proxyId);
    return { ok: true, latency_ms: 12, error: null };
  };
});

afterEach(() => {
  cleanup();
  adminApi.proxies = originalProxies;
  adminApi.createProxy = originalCreate;
  adminApi.updateProxy = originalUpdate;
  adminApi.deleteProxy = originalDelete;
  adminApi.checkProxy = originalCheck;
});

describe('AdminProxies', () => {
  test('shows the empty pool explanation without inventing a proxy', async () => {
    renderProxies();

    expect(await screen.findByText('Прокси пока нет')).toBeTruthy();
    expect(screen.getByText(/подключаются к Telegram напрямую/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Новый прокси' })).toBeTruthy();
  });

  test('renders proxy rows without password material', async () => {
    loadProxies = async () =>
      proxyPage([
        proxySummary(),
        proxySummary({
          id: '22222222-2222-4222-8222-222222222222',
          label: 'Резервный',
          protocol: 'http',
          host: 'backup.example.test',
          port: 3128,
          agents_total: 3,
          is_active: false,
        }),
      ]);
    renderProxies();

    expect(await screen.findByText('Основной')).toBeTruthy();
    expect(screen.getByText('SOCKS5')).toBeTruthy();
    expect(screen.getByText('HTTP')).toBeTruthy();
    expect(screen.getByText('proxy.example.test:1080')).toBeTruthy();
    expect(screen.getByText('Активен')).toBeTruthy();
    expect(screen.getByText('Отключён')).toBeTruthy();
    expect(screen.getByText('3')).toBeTruthy();
    expect(document.body.textContent).not.toContain('password');
    expect(document.body.textContent).not.toContain('secret');
    expect(listCalls[0]).toMatchObject({ page: 1, page_size: 25 });
  });

  test('creates a proxy from the modal with a password', async () => {
    renderProxies();
    fireEvent.click(await screen.findByRole('button', { name: 'Новый прокси' }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый прокси' });

    fireEvent.change(within(dialog).getByLabelText('Название'), {
      target: { value: '  Основной  ' },
    });
    fireEvent.change(within(dialog).getByLabelText('Адрес'), {
      target: { value: '  proxy.example.test  ' },
    });
    fireEvent.change(within(dialog).getByLabelText('Порт'), { target: { value: '1080' } });
    fireEvent.change(within(dialog).getByLabelText('Логин'), { target: { value: ' mimic ' } });
    fireEvent.change(within(dialog).getByLabelText('Пароль'), { target: { value: 'secret' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Добавить' }));

    await waitFor(() =>
      expect(createCalls).toEqual([
        {
          label: 'Основной',
          protocol: 'socks5',
          host: 'proxy.example.test',
          port: 1080,
          username: 'mimic',
          password: 'secret',
          is_active: true,
        },
      ]),
    );
    expect(await screen.findByText('Прокси добавлен в пул.')).toBeTruthy();
  });

  test('edits a proxy without pre-filling or sending the stored password', async () => {
    loadProxies = async () => proxyPage([proxySummary()]);
    renderProxies();

    fireEvent.click(await screen.findByRole('button', { name: 'Изменить прокси Основной' }));
    const dialog = await screen.findByRole('dialog', { name: 'Изменить прокси' });
    const password = within(dialog).getByLabelText('Пароль') as HTMLInputElement;
    expect(password.value).toBe('');
    expect(password.placeholder).toBe('Оставить прежний');

    fireEvent.change(within(dialog).getByLabelText('Название'), {
      target: { value: 'Обновлённый' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    await waitFor(() =>
      expect(updateCalls).toEqual([
        {
          proxyId: proxySummary().id,
          values: {
            label: 'Обновлённый',
            protocol: 'socks5',
            host: 'proxy.example.test',
            port: 1080,
            username: 'mimic',
            is_active: true,
          },
        },
      ]),
    );
  });

  test('rejects a password without a username before calling the API', async () => {
    renderProxies();
    fireEvent.click(await screen.findByRole('button', { name: 'Новый прокси' }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый прокси' });

    fireEvent.change(within(dialog).getByLabelText('Название'), { target: { value: 'Прокси' } });
    fireEvent.change(within(dialog).getByLabelText('Адрес'), {
      target: { value: 'proxy.example.test' },
    });
    fireEvent.change(within(dialog).getByLabelText('Порт'), { target: { value: '1080' } });
    fireEvent.change(within(dialog).getByLabelText('Пароль'), { target: { value: 'secret' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Добавить' }));

    expect(await within(dialog).findByText('Для пароля укажите логин прокси.')).toBeTruthy();
    expect(createCalls).toEqual([]);
  });

  test('shows the conflict message when deleting an assigned proxy', async () => {
    loadProxies = async () => proxyPage([proxySummary({ agents_total: 2 })]);
    deleteError = { status: 409, message: 'conflict' };
    renderProxies();

    fireEvent.click(await screen.findByRole('button', { name: 'Удалить прокси Основной' }));
    const dialog = await screen.findByRole('dialog', { name: 'Удалить «Основной»?' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Удалить' }));

    expect(
      await screen.findByText(
        'Прокси используют мимики или незавершённый онбординг. Сначала снимите его.',
      ),
    ).toBeTruthy();
    expect(deleteCalls).toEqual([proxySummary().id]);
  });

  test('reports a successful proxy check', async () => {
    loadProxies = async () => proxyPage([proxySummary()]);
    renderProxies();

    fireEvent.click(await screen.findByRole('button', { name: 'Проверить прокси Основной' }));

    expect(await screen.findByText('Прокси отвечает за 12 мс.')).toBeTruthy();
    expect(checkCalls).toEqual([proxySummary().id]);
  });
});
