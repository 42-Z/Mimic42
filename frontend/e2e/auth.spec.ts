import { test, expect } from '@playwright/test';
import { USERS, loginViaForm, mockApi } from './helpers';

const fullUser = USERS.full;
if (!fullUser) throw new Error('Missing e2e user full');

test.use({ storageState: fullUser.stateFile });

const agentsList = [
  { agent_id: 'agent-running-1', owner_id: fullUser.id, name: 'Бегущий', state: 'running' },
  { agent_id: 'agent-stopped-2', owner_id: fullUser.id, name: 'Остановленный', state: 'stopped' },
];

test.describe('authenticated navigation', () => {
  test('redirects authenticated user away from login to dashboard', async ({ page }) => {
    await mockApi(page, 'GET', '/agents', agentsList);
    await page.goto('/login');
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByRole('heading', { name: 'Ваши агенты' })).toBeVisible();
  });

  test('logs out from the sidebar', async ({ page }) => {
    await mockApi(page, 'GET', '/agents', agentsList);
    await page.goto('/dashboard');
    await expect(page.getByRole('heading', { name: 'Ваши агенты' })).toBeVisible();
    await page.getByRole('button', { name: 'Выйти' }).click();
    await expect(page).toHaveURL(/\/login/);
  });

  test('dashboard with agents lists them with KPIs', async ({ page }) => {
    await mockApi(page, 'GET', '/agents', agentsList);
    await page.goto('/dashboard');
    await expect(page.getByRole('heading', { name: 'Ваши агенты' })).toBeVisible();
    await expect(page.getByTestId('agent-card-agent-running-1')).toBeVisible();
    await expect(page.getByTestId('agent-card-agent-stopped-2')).toBeVisible();
    await expect(page.getByTestId('kpi-card')).toHaveCount(4);
  });

  test('start/stop buttons reflect agent state', async ({ page }) => {
    await mockApi(page, 'GET', '/agents', agentsList);
    await page.goto('/dashboard');
    const running = page.getByTestId('agent-card-agent-running-1');
    await expect(running.getByRole('button', { name: 'Запустить' })).toBeDisabled();
    await expect(running.getByRole('button', { name: 'Стоп' })).toBeEnabled();

    const stopped = page.getByTestId('agent-card-agent-stopped-2');
    await expect(stopped.getByRole('button', { name: 'Запустить' })).toBeEnabled();
    await expect(stopped.getByRole('button', { name: 'Стоп' })).toBeDisabled();
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

  test('logs in and lands on the redirect target', async ({ page }) => {
    await mockApi(page, 'GET', '/agents', agentsList);
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/login\?redirect=%2Fdashboard/);
    await loginViaForm(page, fullUser);
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(
      page.getByTestId('agent-card-agent-running-1').getByText('Бегущий'),
    ).toBeVisible();
  });
});
