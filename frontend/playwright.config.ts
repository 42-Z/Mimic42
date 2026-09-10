import { defineConfig, devices } from '@playwright/test';

const STUB_PORT = Number(process.env.E2E_STUB_PORT ?? 54321);
const STUB_URL = `http://127.0.0.1:${STUB_PORT}`;
const APP_URL = 'http://127.0.0.1:3000';

// Dummy-but-valid env for the app under test. The Supabase URL points at the
// local stub (see e2e/stub/server.ts); the API base is mocked per-test with
// page.route('**/api/v1/**'), so no real backend is needed.
const testEnv = {
  NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL ?? STUB_URL,
  NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? 'e2e-test-anon-key',
  NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8000',
};

export default defineConfig({
  testDir: 'e2e',
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
      command: `bun e2e/stub/server.ts`,
      url: `${STUB_URL}/__health__`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      env: {
        E2E_STUB_PORT: String(STUB_PORT),
      },
    },
    {
      command: process.env.CI ? 'bun run build && bun run start' : 'bun run dev',
      url: APP_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: testEnv,
    },
  ],
});
