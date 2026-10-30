import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import type { AxiosAdapter, InternalAxiosRequestConfig } from 'axios';

const getSession = mock(async () => ({
  data: { session: { access_token: 'admin-api-test-token' } },
}));

mock.module('@/lib/supabase/client', () => ({
  getSupabaseClient: () => ({ auth: { getSession } }),
}));

const { apiClient } = await import('@/lib/api');
const { adminApi } = await import('@/lib/adminApi');

interface CapturedRequest {
  method?: string;
  url?: string;
  params?: unknown;
  data?: unknown;
  signal?: unknown;
  authorization?: unknown;
}

const originalAdapter = apiClient.defaults.adapter;
let captured: CapturedRequest[];

function useResponseAdapter(data: unknown) {
  const requests: InternalAxiosRequestConfig[] = [];
  const adapter: AxiosAdapter = async (config) => {
    requests.push(config);
    return {
      data,
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
    };
  };
  apiClient.defaults.adapter = adapter;
  captured = [];
  return requests;
}

function record(requests: InternalAxiosRequestConfig[]) {
  captured = requests.map((config) => ({
    method: config.method,
    url: config.url,
    params: config.params,
    data: config.data,
    signal: config.signal,
    authorization: config.headers.get('Authorization'),
  }));
}

beforeEach(() => {
  getSession.mockClear();
});

afterEach(() => {
  apiClient.defaults.adapter = originalAdapter;
  mock.restore();
});

describe('adminApi', () => {
  test('uses the shared authenticated client and passes the query AbortSignal', async () => {
    const body = { items: [], total: 0, page: 2, page_size: 10 };
    const requests = useResponseAdapter(body);
    const controller = new AbortController();

    const result = await adminApi.users(
      { q: 'person', page: 2, page_size: 10 },
      { signal: controller.signal },
    );
    record(requests);

    expect(result).toEqual(body);
    expect(captured).toEqual([
      {
        method: 'get',
        url: '/admin/users',
        params: { q: 'person', page: 2, page_size: 10 },
        data: undefined,
        signal: controller.signal,
        authorization: 'Bearer admin-api-test-token',
      },
    ]);
    expect(getSession).toHaveBeenCalledTimes(1);
  });

  test('writes go directly through the shared API client and return the saved HASH', async () => {
    const publicResponse = {
      api_id: 12345,
      api_hash: 'sensitive-api-hash',
      has_api_hash: true,
      source: 'database' as const,
      updated_at: '2026-10-19T10:00:00Z',
      updated_by: 'admin-id',
    };
    const requests = useResponseAdapter(publicResponse);
    const apiHash = 'sensitive-api-hash';

    const result = await adminApi.saveTelegramSettings({ api_id: 12345, api_hash: apiHash });
    record(requests);

    expect(result).toEqual(publicResponse);
    expect(captured[0]).toMatchObject({
      method: 'put',
      url: '/admin/telegram-settings',
      authorization: 'Bearer admin-api-test-token',
    });
    expect(JSON.parse(String(captured[0]?.data))).toEqual({
      api_id: 12345,
      api_hash: apiHash,
    });
    expect(result.api_hash).toBe(apiHash);
  });

  test('posts proxy import text to the admin import route', async () => {
    const requests = useResponseAdapter({ imported: 1, skipped: 0, errors: [] });

    await adminApi.importProxies({
      text: '1.2.3.4:1080:user:pass',
      protocol: 'socks5',
      is_active: true,
    });
    record(requests);

    expect(captured[0]).toMatchObject({
      method: 'post',
      url: '/admin/proxies/import',
      authorization: 'Bearer admin-api-test-token',
    });
    expect(JSON.parse(String(captured[0]?.data))).toEqual({
      text: '1.2.3.4:1080:user:pass',
      protocol: 'socks5',
      is_active: true,
    });
  });

  test('maps every read route under the admin API and passes cancellation signals', async () => {
    const requests = useResponseAdapter({});
    const signal = new AbortController().signal;

    await adminApi.me({ signal });
    await adminApi.user('user-id', { page: 2, page_size: 5 }, { signal });
    await adminApi.presets(
      { q: 'prompt', kind: 'published', page: 3, page_size: 10 },
      { signal },
    );
    await adminApi.preset('preset-id', { signal });
    await adminApi.telegramSettings({ signal });
    await adminApi.statistics(30, { signal });
    await adminApi.proxies({ page: 2, page_size: 10 }, { signal });
    await adminApi.proxyOptions({ signal });
    record(requests);

    expect(captured.map(({ method, url, params, signal: requestSignal }) => ({
      method,
      url,
      params,
      signal: requestSignal,
    }))).toEqual([
      { method: 'get', url: '/me', params: undefined, signal },
      {
        method: 'get',
        url: '/admin/users/user-id',
        params: { page: 2, page_size: 5 },
        signal,
      },
      {
        method: 'get',
        url: '/admin/presets',
        params: { q: 'prompt', kind: 'published', page: 3, page_size: 10 },
        signal,
      },
      { method: 'get', url: '/admin/presets/preset-id', params: undefined, signal },
      { method: 'get', url: '/admin/telegram-settings', params: undefined, signal },
      { method: 'get', url: '/admin/statistics', params: { days: 30 }, signal },
      {
        method: 'get',
        url: '/admin/proxies',
        params: { page: 2, page_size: 10 },
        signal,
      },
      { method: 'get', url: '/admin/proxies/options', params: undefined, signal },
    ]);
  });
});
