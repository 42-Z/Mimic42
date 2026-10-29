import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useContext, type ReactNode } from 'react';
import { ToastProvider } from '@/components/ui/toast';
import { AdminAccessContext, type AdminAccess } from '@/hooks/useAdminAccess';
import { adminApi } from '@/lib/adminApi';
import { queryKeys } from '@/lib/queryClient';
import type { PublicTelegramSettings, SaveTelegramSettings } from '@/types/admin';

const adminId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const publicSettings: PublicTelegramSettings = {
  api_id: 12345,
  api_hash: 'saved-api-hash',
  has_api_hash: true,
  source: 'database',
  updated_at: '2026-10-18T12:00:00Z',
  updated_by: adminId,
};

const access: AdminAccess = {
  userId: adminId,
  isLoading: false,
  isAdmin: true,
  isDenied: false,
  error: null,
  retry: () => undefined,
};

let settingsResult: PublicTelegramSettings;
let settingsCalls = 0;
let saveCalls: SaveTelegramSettings[];
let saveImplementation: (values: SaveTelegramSettings) => Promise<PublicTelegramSettings>;

const originalTelegramSettings = adminApi.telegramSettings;
const originalSaveTelegramSettings = adminApi.saveTelegramSettings;

function CacheBackedAccessProvider({ children }: { children: ReactNode }) {
  const identityQuery = useQuery({
    queryKey: queryKeys.identity(adminId),
    queryFn: async () => ({ user_id: adminId, is_admin: true }),
    enabled: false,
  });
  const isAdmin = identityQuery.data?.is_admin === true;
  const value: AdminAccess = {
    userId: adminId,
    isLoading: false,
    isAdmin,
    isDenied: !isAdmin,
    error: null,
    retry: () => undefined,
  };
  return <AdminAccessContext.Provider value={value}>{children}</AdminAccessContext.Provider>;
}

function AdminGate({ children }: { children: ReactNode }) {
  const accessState = useContext(AdminAccessContext);
  return accessState?.isAdmin ? <>{children}</> : <p>Нет доступа</p>;
}

function renderSettings(options: { trackRevocation?: boolean } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  queryClient.setQueryData(queryKeys.identity(adminId), {
    user_id: adminId,
    is_admin: true,
  });
  const accessProvider = options.trackRevocation ? (
    <CacheBackedAccessProvider>
      <AdminGate>
        <AdminTelegramSettings />
      </AdminGate>
    </CacheBackedAccessProvider>
  ) : (
    <AdminAccessContext.Provider value={access}>
      <AdminTelegramSettings />
    </AdminAccessContext.Provider>
  );
  const view = render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>{accessProvider}</ToastProvider>
    </QueryClientProvider>,
  );
  return { queryClient, ...view };
}

beforeEach(() => {
  settingsResult = { ...publicSettings };
  settingsCalls = 0;
  saveCalls = [];
  saveImplementation = async (values) => {
    settingsResult = {
      ...publicSettings,
      api_id: values.api_id,
      api_hash: values.api_hash,
      updated_at: '2026-10-19T12:00:00Z',
    };
    return settingsResult;
  };
  adminApi.telegramSettings = async () => {
    settingsCalls += 1;
    return settingsResult;
  };
  adminApi.saveTelegramSettings = async (values) => {
    saveCalls.push(values);
    return saveImplementation(values);
  };
});

afterEach(() => {
  cleanup();
  adminApi.telegramSettings = originalTelegramSettings;
  adminApi.saveTelegramSettings = originalSaveTelegramSettings;
});

const { AdminTelegramSettings } = await import('@/components/admin/AdminTelegramSettings');

describe('AdminTelegramSettings', () => {
  test('loads the saved pair and keeps HASH masked until the eye is pressed', async () => {
    renderSettings();

    expect((await screen.findByLabelText('API ID') as HTMLInputElement).value).toBe('12345');
    const hash = screen.getByLabelText('API HASH') as HTMLInputElement;
    expect(hash.type).toBe('password');
    expect(hash.value).toBe('saved-api-hash');
    expect(screen.getByText('Настройка платформы')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Показать HASH' }));
    expect(hash.type).toBe('text');
    fireEvent.click(screen.getByRole('button', { name: 'Скрыть HASH' }));
    expect(hash.type).toBe('password');
  });

  test('requires a strict positive integer API ID and a non-empty HASH', async () => {
    settingsResult = { ...publicSettings, api_id: null, has_api_hash: false, api_hash: null };
    renderSettings();
    const apiId = (await screen.findByLabelText('API ID')) as HTMLInputElement;
    const apiHash = screen.getByLabelText('API HASH');
    expect(apiId.value).toBe('');
    expect((screen.getByRole('button', { name: 'Сохранить настройки' }) as HTMLButtonElement).disabled).toBe(
      true,
    );

    fireEvent.change(apiId, { target: { value: '1abc' } });
    fireEvent.change(apiHash, { target: { value: 'new-api-hash' } });
    expect((screen.getByRole('button', { name: 'Сохранить настройки' }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(saveCalls).toEqual([]);
  });

  test('writes directly, shows the saved HASH, and keeps mutations out of the cache', async () => {
    let resolveSave: ((value: PublicTelegramSettings) => void) | undefined;
    saveImplementation = (values) =>
      new Promise<PublicTelegramSettings>((resolve) => {
        resolveSave = (result) => {
          settingsResult = { ...result, api_id: values.api_id };
          resolve(settingsResult);
        };
      });
    const { queryClient } = renderSettings();
    const apiId = (await screen.findByLabelText('API ID')) as HTMLInputElement;
    const apiHash = screen.getByLabelText('API HASH') as HTMLInputElement;
    fireEvent.change(apiId, { target: { value: '45678' } });
    fireEvent.change(apiHash, { target: { value: 'new-api-hash' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }));

    expect(saveCalls).toEqual([{ api_id: 45678, api_hash: 'new-api-hash' }]);
    expect((screen.getByRole('button', { name: 'Сохраняю…' }) as HTMLButtonElement).disabled).toBe(true);
    expect(apiHash.value).toBe('new-api-hash');

    resolveSave?.({ ...publicSettings, api_id: 45678, api_hash: 'new-api-hash' });
    expect(await screen.findByText('Настройки Telegram сохранены.')).toBeTruthy();
    expect((screen.getByLabelText('API ID') as HTMLInputElement).value).toBe('45678');
    expect((screen.getByLabelText('API HASH') as HTMLInputElement).value).toBe('new-api-hash');
    expect(queryClient.getMutationCache().getAll()).toEqual([]);
    await waitFor(() => expect(settingsCalls).toBeGreaterThan(1));
  });

  test('failure retains API ID and HASH and shows only a safe message', async () => {
    saveImplementation = async () => {
      throw { status: 503, message: 'secret echoed by transport' };
    };
    renderSettings();
    const apiId = (await screen.findByLabelText('API ID')) as HTMLInputElement;
    const apiHash = screen.getByLabelText('API HASH') as HTMLInputElement;
    fireEvent.change(apiId, { target: { value: '789' } });
    fireEvent.change(apiHash, { target: { value: 'temporary-hash' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }));

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).not.toContain('secret echoed by transport');
    expect((screen.getByLabelText('API ID') as HTMLInputElement).value).toBe('789');
    expect((screen.getByLabelText('API HASH') as HTMLInputElement).value).toBe('temporary-hash');
  });

  test('a 403 revokes admin access and unmounts the secret field', async () => {
    saveImplementation = async () => {
      throw { status: 403, message: 'forbidden' };
    };
    renderSettings({ trackRevocation: true });
    const apiId = (await screen.findByLabelText('API ID')) as HTMLInputElement;
    fireEvent.change(apiId, { target: { value: '12345' } });
    fireEvent.change(screen.getByLabelText('API HASH'), { target: { value: 'temporary-hash' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }));

    expect(await screen.findByText('Нет доступа')).toBeTruthy();
    expect(screen.queryByLabelText('API HASH')).toBeNull();
  });
});
