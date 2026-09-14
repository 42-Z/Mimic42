import { test, expect } from '@playwright/test';
import { USERS, hideOnboardingDrafts, currentDraftId, scriptOnboardingLogin } from './helpers';

// Онбординг держит состояние входа в один общий фейковый Telegram-аккаунт
// на сервере (registry.onboarding_account) — параллельные онбординги в
// этом файле затирали бы код/пароль друг друга, поэтому весь файл идёт
// последовательно.
test.describe.configure({ mode: 'serial' });

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
    // Hermetic per attempt: hide leftovers so the app and the test below
    // always agree on the single visible draft (same query the app uses).
    await hideOnboardingDrafts(request, flowUser.id);

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

    // The draft row now exists (created directly against Supabase by the
    // name/soul steps) — this is the real id the finished agent will get.
    const draftId = await currentDraftId(request, flowUser.id);

    // Step 3 — credentials (client validation first, then the real backend:
    // FastAPI -> AgentOnboardingService -> fake Telegram auth client).
    await page.getByLabel('Номер телефона').fill('123');
    await page.getByRole('button', { name: 'Получить код →' }).click();
    await expect(page.getByText(/Номер телефона должен быть в формате E\.164/)).toBeVisible();
    await page.getByLabel('Номер телефона').fill('+79990000000');
    await page.getByRole('button', { name: 'Получить код →' }).click();
    await expect(page.getByRole('heading', { name: 'Код из Telegram' })).toBeVisible();

    // Step 4 — code (client validation first). The fake accepts any 5+
    // digit code by default (no code was scripted for this attempt).
    await page.getByLabel('Код подтверждения').fill('12');
    await page.getByRole('button', { name: 'Подтвердить →' }).click();
    await expect(page.getByText('Код должен содержать минимум 5 цифр')).toBeVisible();
    await page.getByLabel('Код подтверждения').fill('12345');
    await page.getByRole('button', { name: 'Подтвердить →' }).click();
    await expect(page.getByRole('heading', { name: 'Всё готово!' })).toBeVisible();

    // The SMS code must not linger in sessionStorage after authorization.
    await expect
      .poll(() => page.evaluate(() => sessionStorage.getItem('_m42_tc_state')), {
        timeout: 10_000,
      })
      .toBeNull();

    // Step 5 — finalize: the real backend creates the agent for real.
    await page.getByRole('button', { name: 'Создать агента' }).click();
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByTestId(`agent-card-${draftId}`).getByText('Тест')).toBeVisible();
  });
});

test.describe('onboarding 2FA branch', () => {
  test.use({ storageState: twofaUser.stateFile });

  test('submits the 2FA password and finishes without keeping the SMS code', async ({
    page,
    request,
  }) => {
    test.slow();
    await hideOnboardingDrafts(request, twofaUser.id);
    // Arms the shared fake Telegram account: the next sign-in without this
    // exact password must be refused, exactly like a real 2FA-protected
    // account refuses a code-only login.
    await scriptOnboardingLogin(request, null, 'secret2fa');

    await page.goto('/onboarding');
    await page.getByLabel('Имя агента').fill('Тест 2FA');
    await page.getByRole('button', { name: 'Продолжить →' }).click();
    await page.getByLabel(/SOUL\.md/).fill(SOUL_TEXT);
    await page.getByRole('button', { name: 'Продолжить →' }).click();
    await page.getByLabel('Номер телефона').fill('+79990000000');
    await page.getByRole('button', { name: 'Получить код →' }).click();
    await expect(page.getByRole('heading', { name: 'Код из Telegram' })).toBeVisible();

    // The code itself is accepted (not scripted), but the account still
    // requires its 2FA password — the real backend persists that as
    // authorization_status=password_required and the wizard moves on.
    await page.getByLabel('Код подтверждения').fill('12345');
    await page.getByRole('button', { name: 'Подтвердить →' }).click();
    await expect(
      page.getByRole('heading', { name: 'Двухфакторная аутентификация' }),
    ).toBeVisible();

    await page.getByRole('button', { name: 'Подтвердить →' }).click();
    await expect(page.getByText('2FA пароль обязателен')).toBeVisible();

    await page.getByLabel('Пароль 2FA').fill('secret2fa');
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
    request,
  }) => {
    await hideOnboardingDrafts(request, codeUser.id);

    // Arrange: walk to the credentials step for real, so a code_requested
    // draft actually exists in the database before the reload below.
    await page.goto('/onboarding');
    await page.getByLabel('Имя агента').fill('Тест возврата');
    await page.getByRole('button', { name: 'Продолжить →' }).click();
    await page.getByLabel(/SOUL\.md/).fill(SOUL_TEXT);
    await page.getByRole('button', { name: 'Продолжить →' }).click();
    await page.getByLabel('Номер телефона').fill('+79990000000');
    await page.getByRole('button', { name: 'Получить код →' }).click();
    await expect(page.getByRole('heading', { name: 'Код из Telegram' })).toBeVisible();

    // Act: a fresh load must resume at the code step from the stored draft,
    // not restart the wizard from the name step.
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Код из Telegram' })).toBeVisible();
    await expect(page.getByTestId('onboarding-step-telegram_credentials')).toBeVisible();

    await page.getByRole('button', { name: '← Назад' }).click();
    await expect(page.getByRole('heading', { name: 'Подключение Telegram' })).toBeVisible();
  });
});
