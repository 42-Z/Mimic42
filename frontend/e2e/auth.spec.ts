import { test, expect, type APIRequestContext } from '@playwright/test';
import { USERS, loginViaForm, createTestAgent, type E2EUser } from './helpers';

const fullUserOrUndefined = USERS.full;
if (!fullUserOrUndefined) throw new Error('Missing e2e user full');
const fullUser: E2EUser = fullUserOrUndefined;

test.use({ storageState: fullUser.stateFile });

async function seedAgents(
  request: APIRequestContext,
): Promise<{ runningId: string; stoppedId: string }> {
  const runningId = await createTestAgent(request, fullUser.id, 'Бегущий', 'running');
  const stoppedId = await createTestAgent(request, fullUser.id, 'Остановленный', 'stopped');
  return { runningId, stoppedId };
}

test.describe('authenticated navigation', () => {
  test('redirects authenticated user away from login to dashboard', async ({ page, request }) => {
    await seedAgents(request);
    await page.goto('/login');
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByRole('heading', { name: 'Ваши агенты' })).toBeVisible();
  });

  test('dashboard with agents lists them with KPIs', async ({ page, request }) => {
    const { runningId, stoppedId } = await seedAgents(request);
    await page.goto('/dashboard');
    await expect(page.getByRole('heading', { name: 'Ваши агенты' })).toBeVisible();
    await expect(page.getByTestId(`agent-card-${runningId}`)).toBeVisible();
    await expect(page.getByTestId(`agent-card-${stoppedId}`)).toBeVisible();
    await expect(page.getByTestId('kpi-card')).toHaveCount(4);
  });

  test('start/stop buttons reflect agent state', async ({ page, request }) => {
    const { runningId, stoppedId } = await seedAgents(request);
    await page.goto('/dashboard');
    const running = page.getByTestId(`agent-card-${runningId}`);
    await expect(running.getByRole('button', { name: 'Запустить' })).toBeDisabled();
    await expect(running.getByRole('button', { name: 'Стоп' })).toBeEnabled();

    const stopped = page.getByTestId(`agent-card-${stoppedId}`);
    await expect(stopped.getByRole('button', { name: 'Запустить' })).toBeEnabled();
    await expect(stopped.getByRole('button', { name: 'Стоп' })).toBeDisabled();
  });
});

test.describe('sign out', () => {
  // A real logout revokes the Supabase refresh token — using the shared
  // fullUser.stateFile here would poison it for every other test that
  // still expects that snapshot to be a valid, live session.
  test.use({ storageState: { cookies: [], origins: [] } });

  test('logs out from the sidebar', async ({ page, request }) => {
    await seedAgents(request);
    await loginViaForm(page, fullUser);
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByRole('heading', { name: 'Ваши агенты' })).toBeVisible();
    await page.getByRole('button', { name: 'Выйти' }).click();
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe('dashboard without agents', () => {
  test.use({ storageState: USERS.empty?.stateFile });

  test('forces onboarding when the user has no agents', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/onboarding/);
    await expect(page.getByTestId('step-indicator')).toBeVisible();
  });
});

test.describe('fresh login with redirect', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('logs in and lands on the redirect target', async ({ page, request }) => {
    const runningId = await createTestAgent(request, fullUser.id, 'Бегущий', 'running');
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/login\?redirect=%2Fdashboard/);
    await loginViaForm(page, fullUser);
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByTestId(`agent-card-${runningId}`).getByText('Бегущий')).toBeVisible();
  });
});
