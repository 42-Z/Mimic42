import { test, expect } from '@playwright/test';

test.describe('unauthenticated redirects', () => {
  test('/dashboard redirects to login with redirect param', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/login\?redirect=%2Fdashboard/);
  });

  test('/ redirects to login', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/login/);
  });

  test('/onboarding redirects to login with redirect param', async ({ page }) => {
    await page.goto('/onboarding');
    await expect(page).toHaveURL(/\/login\?redirect=%2Fonboarding/);
  });

  test('/agent/:id redirects to login with redirect param', async ({ page }) => {
    await page.goto('/agent/some-agent');
    await expect(page).toHaveURL(/\/login\?redirect=/);
  });
});

test.describe('public pages', () => {
  test('login page renders', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByRole('heading', { name: 'Вход в систему' })).toBeVisible();
  });

  test('register page renders', async ({ page }) => {
    await page.goto('/register');
    await expect(page.getByRole('heading', { name: 'Создать аккаунт' })).toBeVisible();
  });

  test('reset-password page renders', async ({ page }) => {
    await page.goto('/reset-password');
    await expect(page.getByRole('heading', { name: 'Восстановление пароля' })).toBeVisible();
  });

  test('navigates login to register and back', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('link', { name: 'Зарегистрироваться' }).click();
    await expect(page).toHaveURL(/\/register/);
    await page.getByRole('link', { name: 'Войти' }).click();
    await expect(page).toHaveURL(/\/login/);
  });

  test('navigates login to reset-password and back', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('link', { name: 'Забыли пароль?' }).click();
    await expect(page).toHaveURL(/\/reset-password/);
    await page.getByRole('link', { name: 'Вернуться ко входу' }).click();
    await expect(page).toHaveURL(/\/login/);
  });

  test('password visibility toggle works', async ({ page }) => {
    await page.goto('/login');
    const password = page.getByLabel('Пароль', { exact: true });
    await expect(password).toHaveAttribute('type', 'password');
    await page.getByRole('button', { name: 'Показать пароль' }).click();
    await expect(password).toHaveAttribute('type', 'text');
    await page.getByRole('button', { name: 'Скрыть пароль' }).click();
    await expect(password).toHaveAttribute('type', 'password');
  });

  test('login shows zod validation errors', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('button', { name: 'Войти' }).click();
    await expect(page.getByText('Введите корректный email')).toBeVisible();
    await expect(page.getByText('Пароль обязателен')).toBeVisible();
  });

  test('register shows password mismatch error', async ({ page }) => {
    await page.goto('/register');
    await page.getByLabel('Email').fill('user@example.com');
    await page.getByLabel('Пароль', { exact: true }).fill('password123');
    await page.getByLabel('Повторите пароль').fill('different123');
    await page.getByRole('button', { name: 'Создать аккаунт' }).click();
    await expect(page.getByText('Пароли не совпадают')).toBeVisible();
  });

  test('reset-password shows email validation error', async ({ page }) => {
    await page.goto('/reset-password');
    await page.getByPlaceholder('Email').fill('not-an-email');
    await page.getByRole('button', { name: 'Отправить ссылку' }).click();
    await expect(page.getByText('Введите корректный email')).toBeVisible();
  });

  test('update-password without session shows session check only', async ({ page }) => {
    await page.goto('/update-password');
    await expect(page.getByText('Проверка сессии...')).toBeVisible();
    await expect(page.getByPlaceholder('Новый пароль')).toHaveCount(0);
  });

  test('auth callback without code redirects to login with error', async ({ page }) => {
    await page.goto('/api/auth/callback');
    await expect(page).toHaveURL(/\/login\?error=auth_callback_failed/);
  });
});

test.describe('security headers', () => {
  test('login response carries security headers and CSP', async ({ page }) => {
    const response = await page.goto('/login');
    expect(response?.ok()).toBeTruthy();
    const headers = response?.headers() ?? {};
    expect(headers['x-frame-options']).toBe('DENY');
    expect(headers['x-content-type-options']).toBe('nosniff');
    expect(headers['referrer-policy']).toBe('strict-origin-when-cross-origin');
    expect(headers['content-security-policy']).toContain("default-src 'self'");
    expect(headers['content-security-policy']).toContain('frame-ancestors');
  });
});
