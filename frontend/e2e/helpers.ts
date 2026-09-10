import { expect, type APIRequestContext, type Page } from '@playwright/test';

export const STUB_PORT = Number(process.env.E2E_STUB_PORT ?? 54321);
export const STUB_URL = `http://127.0.0.1:${STUB_PORT}`;
export const API_ORIGIN = 'http://127.0.0.1:8000';

export interface E2EUser {
  key: string;
  id: string;
  email: string;
  password: string;
  stateFile: string;
}

/**
 * Fixed users served by e2e/stub/server.ts. Server-side code (middleware,
 * route handlers) cannot see per-request test context, so isolation is done
 * by owner: every spec file logs in as its own user and touches only its
 * own rows.
 */
export const USERS: Record<string, E2EUser> = {
  empty: {
    key: 'empty',
    id: '11111111-1111-1111-1111-111111111111',
    email: 'e2e@mimic42.test',
    password: 'password123',
    stateFile: 'e2e/.auth/empty.json',
  },
  full: {
    key: 'full',
    id: '22222222-2222-2222-2222-222222222222',
    email: 'e2e-full@mimic42.test',
    password: 'password123',
    stateFile: 'e2e/.auth/full.json',
  },
  flow: {
    key: 'flow',
    id: '33333333-3333-3333-3333-333333333333',
    email: 'e2e-flow@mimic42.test',
    password: 'password123',
    stateFile: 'e2e/.auth/flow.json',
  },
  twofa: {
    key: '2fa',
    id: '44444444-4444-4444-4444-444444444444',
    email: 'e2e-2fa@mimic42.test',
    password: 'password123',
    stateFile: 'e2e/.auth/twofa.json',
  },
  code: {
    key: 'code',
    id: '55555555-5555-5555-5555-555555555555',
    email: 'e2e-code@mimic42.test',
    password: 'password123',
    stateFile: 'e2e/.auth/code.json',
  },
};

/** Reseed the whole stub (called once from auth.setup before all logins). */
export async function resetStub(request: APIRequestContext): Promise<void> {
  const res = await request.post(`${STUB_URL}/__reset__`, { data: {} });
  expect(res.ok()).toBeTruthy();
}

/** Emulate a backend side-effect on a Supabase row (the real FastAPI is mocked in e2e). */
export async function patchStubRow(
  request: APIRequestContext,
  table: string,
  id: string,
  patch: Record<string, unknown>,
): Promise<void> {
  const res = await request.patch(`${STUB_URL}/__row__`, {
    data: { table, id, patch },
  });
  expect(res.ok()).toBeTruthy();
}

/** Read rows from the stub (e.g. to discover ids created through the UI). */
export async function readStubRows(
  request: APIRequestContext,
  table: string,
  query = 'select=*',
): Promise<Record<string, unknown>[]> {
  const res = await request.get(`${STUB_URL}/rest/v1/${table}?${query}`, {
    headers: { apikey: 'e2e-test-anon-key' },
  });
  expect(res.ok()).toBeTruthy();
  return (await res.json()) as Record<string, unknown>[];
}

/** Mock one FastAPI endpoint with a JSON body (query string is ignored). */
export function mockApi(
  page: Page,
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE' | 'PUT',
  path: string,
  body: unknown,
  status = 200,
): Promise<void> {
  const target = `${API_ORIGIN}/api/v1${path}`;
  return page
    .route(
      (url) => url.origin + url.pathname === target,
      async (route) => {
        if (route.request().method() !== method) {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status,
          contentType: 'application/json',
          body: JSON.stringify(body),
        });
      },
    )
    .then(() => undefined);
}

/** Log in through the real login form. */
export async function loginViaForm(page: Page, user: E2EUser): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill(user.email);
  await page.getByLabel('Пароль', { exact: true }).fill(user.password);
  await page.getByRole('button', { name: 'Войти' }).click();
}
