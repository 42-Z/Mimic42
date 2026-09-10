import { test, expect } from '@playwright/test';
import {
  STUB_URL,
  USERS,
  mockApi,
  patchStubRow,
  readStubRows,
} from './helpers';

const flowUser = USERS.flow;
const twofaUser = USERS.twofa;
const codeUser = USERS.code;
if (!flowUser || !twofaUser || !codeUser) throw new Error('Missing e2e users');

const SOUL_TEXT = '0123456789性格テスト: спокойный помощник, отвечает коротко и по делу каждый день';

test.describe('onboarding wizard', () => {
  test.use({ storageState: flowUser.stateFile });

  test('walks the whole flow: name, soul, credentials, code, finalize', async ({
    page,
    request,
  }) => {
    test.slow();

    await page.goto('/onboarding');
    await expect(page.getByRole('heading', { name: 'Как зовут вашего агента?' })).toBeVisible();

    // Step 1 — name (client validation first).
    await page.getByRole('button', { name: 'Продолжить →' }).click();
    await expect(page.getByText('Имя агента обязательно')).toBeVisible();
    await page.getByLabel('Имя агента').fill('Тест');
    await page.getByRole('button', { name: 'Продолжить →' }).click();
    await expect(page.getByRole('heading', { name: 'Характер агента' })).toBeVisible();

    // Step 2 — soul (client validation first).
    await page.getByLabel(/SOUL\.md/).fill('коротко');
    await page.getByRole('button', { name: 'Продолжить →' }).click();
    await expect(page.getByText('Характер должен содержать хотя бы 10 символов')).toBeVisible();
    await page.getByLabel(/SOUL\.md/).fill(SOUL_TEXT);
    await page.getByRole('button', { name: 'Продолжить →' }).click();
    await expect(page.getByRole('heading', { name: 'Подключение Telegram' })).toBeVisible();

    // Step 3 — credentials (client validation first, then mocked API + stub flip).
    await page.getByLabel('Номер телефона').fill('123');
    await page.getByRole('button', { name: 'Получить код →' }).click();
    await expect(page.getByText(/Номер телефона должен быть в формате E\.164/)).toBeVisible();
    await page.getByLabel('Номер телефона').fill('+79990000000');

    await page.route(
      (url) => url.origin + url.pathname === 'http://127.0.0.1:8000/api/v1/onboarding/telegram',
      async (route) => {
        if (route.request().method() !== 'POST') {
          await route.fallback();
          return;
        }
        const body = route.request().postDataJSON() as {
          phone_number: string;
          onboarding_id: string | null;
        };
        const draftId = body.onboarding_id;
        if (typeof draftId === 'string') {
          await patchStubRow(request, 'agent_onboarding_sessions', draftId, {
            authorization_status: 'code_requested',
            phone_number: '+79990000000',
          });
        }
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            onboarding_id: draftId,
            owner_id: flowUser.id,
            phone_number: '+79990000000',
            authorization_status: 'code_requested',
          }),
        });
      },
    );
    await page.getByRole('button', { name: 'Получить код →' }).click();
    await expect(page.getByRole('heading', { name: 'Код из Telegram' })).toBeVisible();

    // Step 4 — code (client validation first, then mocked API + stub flip).
    const drafts = await readStubRows(
      request,
      'agent_onboarding_sessions',
      `select=id&owner_id=eq.${flowUser.id}`,
    );
    const draftId = drafts[0]?.['id'];
    expect(typeof draftId).toBe('string');

    await page.getByLabel('Код подтверждения').fill('12');
    await page.getByRole('button', { name: 'Подтвердить →' }).click();
    await expect(page.getByText('Код должен содержать минимум 5 цифр')).toBeVisible();
    await page.getByLabel('Код подтверждения').fill('12345');

    await page.route(
      (url) =>
        url.origin + url.pathname ===
        `http://127.0.0.1:8000/api/v1/onboarding/${String(draftId)}/telegram/code`,
      async (route) => {
        if (route.request().method() !== 'POST') {
          await route.fallback();
          return;
        }
        await patchStubRow(request, 'agent_onboarding_sessions', String(draftId), {
          authorization_status: 'authorized',
        });
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            onboarding_id: draftId,
            owner_id: flowUser.id,
            phone_number: '+79990000000',
            authorization_status: 'authorized',
          }),
        });
      },
    );
    await page.getByRole('button', { name: 'Подтвердить →' }).click();
    await expect(page.getByRole('heading', { name: 'Всё готово!' })).toBeVisible();

    // The SMS code must not linger in sessionStorage after authorization.
    await expect
      .poll(() => page.evaluate(() => sessionStorage.getItem('_m42_tc_state')), {
        timeout: 10_000,
      })
      .toBeNull();

    // Step 5 — finalize.
    await mockApi(page, 'GET', '/agents', [
      { agent_id: draftId, owner_id: flowUser.id, name: 'Тест', state: 'stopped' },
    ]);
    await page.route(
      (url) =>
        url.origin + url.pathname ===
        `http://127.0.0.1:8000/api/v1/onboarding/${String(draftId)}/agent`,
      async (route) => {
        if (route.request().method() !== 'POST') {
          await route.fallback();
          return;
        }
        // Emulate the backend side-effect: the created agent appears in Supabase.
        await request.post(`${STUB_URL}/rest/v1/agents`, {
          data: {
            id: draftId,
            owner_id: flowUser.id,
            name: 'Тест',
            status: 'stopped',
          },
          headers: { apikey: 'e2e-test-anon-key' },
        });
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            agent_id: draftId,
            owner_id: flowUser.id,
            state: 'stopped',
          }),
        });
      },
    );
    await page.getByRole('button', { name: 'Создать агента' }).click();
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(
      page.getByTestId(`agent-card-${String(draftId)}`).getByText('Тест'),
    ).toBeVisible();
  });
});

test.describe('onboarding 2FA branch', () => {
  test.use({ storageState: twofaUser.stateFile });

  test('submits the 2FA password and finishes without keeping the SMS code', async ({
    page,
    context,
    request,
  }) => {
    test.slow();

    // The SMS code from the previous step lives in sessionStorage in prod.
    await context.addInitScript(() => {
      sessionStorage.setItem('_m42_tc_state', '12345');
    });

    await page.goto('/onboarding');
    await expect(
      page.getByRole('heading', { name: 'Двухфакторная аутентификация' }),
    ).toBeVisible();

    await page.getByRole('button', { name: 'Подтвердить →' }).click();
    await expect(page.getByText('2FA пароль обязателен')).toBeVisible();

    await page.getByLabel('Пароль 2FA').fill('secret2fa');
    await page.route(
      (url) =>
        url.origin + url.pathname ===
        'http://127.0.0.1:8000/api/v1/onboarding/draft-2fa-1/telegram/code',
      async (route) => {
        if (route.request().method() !== 'POST') {
          await route.fallback();
          return;
        }
        const body = route.request().postDataJSON() as { code?: unknown; password?: unknown };
        expect(body.code).toBe('12345');
        expect(body.password).toBe('secret2fa');
        await patchStubRow(request, 'agent_onboarding_sessions', 'draft-2fa-1', {
          authorization_status: 'authorized',
        });
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            onboarding_id: 'draft-2fa-1',
            owner_id: twofaUser.id,
            phone_number: '+79990000000',
            authorization_status: 'authorized',
          }),
        });
      },
    );
    await page.getByRole('button', { name: 'Подтвердить →' }).click();
    await expect(page.getByRole('heading', { name: 'Всё готово!' })).toBeVisible();

    await expect
      .poll(() => page.evaluate(() => sessionStorage.getItem('_m42_tc_state')), {
        timeout: 10_000,
      })
      .toBeNull();
  });
});

test.describe('onboarding from stored step', () => {
  test.use({ storageState: codeUser.stateFile });

  test('code-requested draft opens the code step, back returns to credentials', async ({
    page,
  }) => {
    await page.goto('/onboarding');
    await expect(page.getByRole('heading', { name: 'Код из Telegram' })).toBeVisible();
    await expect(page.getByTestId('onboarding-step-telegram_credentials')).toBeVisible();

    await page.getByRole('button', { name: '← Назад' }).click();
    await expect(page.getByRole('heading', { name: 'Подключение Telegram' })).toBeVisible();
  });
});
