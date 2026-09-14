import { defineConfig, devices } from '@playwright/test';

// Port 3000 is the default (backend CORS is hardcoded to it); override when
// the port is taken by another project on the dev machine.
const APP_PORT = Number(process.env.E2E_APP_PORT ?? 3000);
const APP_URL = `http://127.0.0.1:${APP_PORT}`;
const API_PORT = Number(process.env.E2E_API_PORT ?? 8000);
const API_URL = `http://127.0.0.1:${API_PORT}`;

function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} не задан — источник .env.test перед запуском e2e`);
  }
  return value;
}

// Настоящий проект Mimic42 Dev: фронт ходит в настоящую Supabase Auth, а
// API — в mimic42.testing.server:app, поднятый ниже поверх настоящей базы.
const testEnv = {
  NEXT_PUBLIC_SUPABASE_URL: requiredEnv('TEST_SUPABASE_URL'),
  NEXT_PUBLIC_SUPABASE_ANON_KEY: requiredEnv('TEST_SUPABASE_ANON_KEY'),
  NEXT_PUBLIC_API_BASE_URL: API_URL,
};

export default defineConfig({
  testDir: 'e2e',
  globalSetup: './e2e/global-setup.ts',
  globalTeardown: './e2e/global-teardown.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI
    ? [['github'], ['html', { outputFolder: 'playwright-report', open: 'never' }]]
    : [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: APP_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    // Generous web-first assertion timeout: the local dev server compiles
    // routes on demand, so first navigations are slow. CI uses the
    // production build and is much faster.
    actionTimeout: 15_000,
  },
  expect: {
    timeout: 15_000,
  },
  projects: [
    {
      name: 'setup',
      testMatch: /auth\.setup\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'chromium',
      testIgnore: /auth\.setup\.ts/,
      dependencies: ['setup'],
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      command: `uv run uvicorn mimic42.testing.server:app --port ${API_PORT}`,
      cwd: '..',
      url: `${API_URL}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: process.env.CI ? 'bun run build && bun run start' : 'bun run dev',
      url: APP_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: {
        ...testEnv,
        PORT: String(APP_PORT),
      },
    },
  ],
});
