import { test as setup, expect, type Page } from '@playwright/test';
import { USERS, resetStub, loginViaForm, type E2EUser } from './helpers';

async function loginAndSave(page: Page, user: E2EUser, expectedUrl: RegExp): Promise<void> {
  await loginViaForm(page, user);
  await expect(page).toHaveURL(expectedUrl, { timeout: 30_000 });
  await page.context().storageState({ path: user.stateFile });
}

/**
 * Resets the stub once, then logs in every e2e user through the real login
 * form and stores one browser state per user for the specs.
 */
setup('reset stub', async ({ request }) => {
  await resetStub(request);
});

for (const key of ['empty', 'full', 'flow', 'twofa', 'code'] as const) {
  const user = USERS[key];
  if (!user) throw new Error(`Unknown e2e user ${key}`);
  // Users without seeded agents land on onboarding; the full user has agents.
  const expectedUrl = key === 'full' ? /\/dashboard/ : /\/onboarding/;
  setup(`authenticate as ${key}`, async ({ page }) => {
    await loginAndSave(page, user, expectedUrl);
  });
}
