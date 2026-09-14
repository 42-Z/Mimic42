import { test as setup, expect, type Page } from '@playwright/test';
import { USERS, resetBackend, createTestAgent, loginViaForm, type E2EUser } from './helpers';

// The reset must complete, and the "full" user needs its baseline agent,
// before any login runs — fullyParallel would otherwise race these.
setup.describe.configure({ mode: 'serial' });

async function loginAndSave(page: Page, user: E2EUser, expectedUrl: RegExp): Promise<void> {
  await loginViaForm(page, user);
  await expect(page).toHaveURL(expectedUrl, { timeout: 30_000 });
  await page.context().storageState({ path: user.stateFile });
}

/**
 * Resets the backend once, seeds the "full" user's baseline agent (so its
 * login lands on the dashboard, not onboarding), then logs in every e2e
 * user through the real login form (real Supabase Auth) and stores one
 * browser state per user for the specs.
 */
setup('reset backend', async ({ request }) => {
  const slot = process.env['E2E_SLOT'];
  if (!slot) throw new Error('E2E_SLOT не задан — global-setup.ts должен был его выставить');
  await resetBackend(request, slot);

  const fullUser = USERS.full;
  if (!fullUser) throw new Error('Missing e2e user full');
  await createTestAgent(request, fullUser.id, 'Бегущий', 'running');
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
