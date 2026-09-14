import { expect, type APIRequestContext, type Page } from '@playwright/test';

export const API_ORIGIN = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8000';
export const SUPABASE_URL = requiredEnv('TEST_SUPABASE_URL');

function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} не задан — источник .env.test перед запуском e2e`);
  return value;
}

export interface E2EUser {
  key: string;
  id: string;
  email: string;
  password: string;
  stateFile: string;
}

interface SlotDescription {
  slot: string;
  password: string;
  personas: { key: string; id: string; email: string }[];
}

/**
 * Персоны текущего слота (задаётся global-setup.ts перед стартом всех
 * воркеров). Слот на весь прогон один — по нему настоящие Supabase-учётки
 * не пересекаются с параллельным прогоном на другой машине/ветке.
 */
function loadUsers(): Record<string, E2EUser> {
  const raw = process.env['E2E_SLOT_DESCRIPTION'];
  if (!raw) {
    throw new Error('E2E_SLOT_DESCRIPTION не задан — global-setup.ts должен был его выставить');
  }
  const description = JSON.parse(raw) as SlotDescription;
  const users: Record<string, E2EUser> = {};
  for (const persona of description.personas) {
    users[persona.key] = {
      key: persona.key,
      id: persona.id,
      email: persona.email,
      password: description.password,
      stateFile: `e2e/.auth/${persona.key}.json`,
    };
  }
  return users;
}

export const USERS: Record<string, E2EUser> = loadUsers();

function serviceRoleHeaders(): Record<string, string> {
  const key = requiredEnv('TEST_SUPABASE_SERVICE_ROLE_KEY');
  return { apikey: key, Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' };
}

/** Reset the real backend (both the slot's DB rows and the fake Telegram/LLM state). */
export async function resetBackend(request: APIRequestContext, slot: string): Promise<void> {
  const res = await request.post(`${API_ORIGIN}/__test__/reset`, { data: { slot } });
  expect(res.ok()).toBeTruthy();
}

/** Create a real agent (bypassing onboarding) for a given owner; returns its id. */
export async function createTestAgent(
  request: APIRequestContext,
  ownerId: string,
  name: string,
  state: 'running' | 'stopped' = 'stopped',
  phoneNumber: string | null = null,
  withTelegramSession = true,
): Promise<string> {
  const res = await request.post(`${API_ORIGIN}/__test__/agents`, {
    data: {
      owner_id: ownerId,
      name,
      state,
      phone_number: phoneNumber,
      with_telegram_session: withTelegramSession,
    },
  });
  expect(res.ok()).toBeTruthy();
  const { agent_id: agentId } = (await res.json()) as { agent_id: string };
  return agentId;
}

/** Feed a fake incoming Telegram message straight to the agent's runtime. */
export async function deliverMessage(
  request: APIRequestContext,
  agentId: string,
  chatId: number,
  text: string,
): Promise<void> {
  const res = await request.post(`${API_ORIGIN}/__test__/telegram/${agentId}/deliver`, {
    data: { chat_id: chatId, text },
  });
  expect(res.ok()).toBeTruthy();
}

/** Read what the fake Telegram account for this agent has sent so far. */
export async function sentMessages(
  request: APIRequestContext,
  agentId: string,
): Promise<{ chat_id: string; text: string }[]> {
  const res = await request.get(`${API_ORIGIN}/__test__/telegram/${agentId}/sent`);
  expect(res.ok()).toBeTruthy();
  return (await res.json()) as { chat_id: string; text: string }[];
}

/** Script the code (and optional 2FA password) the fake onboarding login accepts. */
export async function scriptOnboardingLogin(
  request: APIRequestContext,
  code: string | null,
  password: string | null = null,
): Promise<void> {
  const res = await request.post(`${API_ORIGIN}/__test__/telegram/onboarding/script`, {
    data: { code, password },
  });
  expect(res.ok()).toBeTruthy();
}

/**
 * Deletes leftover incomplete onboarding drafts of a user, straight against
 * Supabase with the service-role key (bypasses RLS; test-only cleanup, not
 * something a real user session could do). Makes a wizard test hermetic
 * across retries: without it, a leftover draft from a previous attempt
 * would be the "most recent incomplete draft" deriveOnboardingStep resumes.
 */
export async function hideOnboardingDrafts(
  request: APIRequestContext,
  ownerId: string,
): Promise<void> {
  const res = await request.delete(
    `${SUPABASE_URL}/rest/v1/agent_onboarding_sessions?owner_id=eq.${ownerId}&completed_agent_id=is.null`,
    { headers: serviceRoleHeaders() },
  );
  expect(res.ok()).toBeTruthy();
}

/** Read the single most recent incomplete onboarding draft id for a user. */
export async function currentDraftId(
  request: APIRequestContext,
  ownerId: string,
): Promise<string> {
  const res = await request.get(
    `${SUPABASE_URL}/rest/v1/agent_onboarding_sessions` +
      `?select=id&owner_id=eq.${ownerId}&completed_agent_id=is.null&order=created_at.desc&limit=1`,
    { headers: serviceRoleHeaders() },
  );
  expect(res.ok()).toBeTruthy();
  const rows = (await res.json()) as { id: string }[];
  const id = rows[0]?.id;
  if (!id) throw new Error(`Нет черновика онбординга для owner_id=${ownerId}`);
  return id;
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
