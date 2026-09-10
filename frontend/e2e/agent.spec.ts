import { test, expect, type Page } from '@playwright/test';
import { USERS, mockApi } from './helpers';

const fullUser = USERS.full;
if (!fullUser) throw new Error('Missing e2e user full');

test.use({ storageState: fullUser.stateFile });

const AGENT_RUNNING = 'agent-running-1';
const AGENT_STOPPED = 'agent-stopped-2';
const STAMP = new Date().toISOString();

const statusRunning = {
  agent_id: AGENT_RUNNING,
  owner_id: fullUser.id,
  state: 'running',
};

const statusStopped = {
  agent_id: AGENT_STOPPED,
  owner_id: fullUser.id,
  state: 'stopped',
};

const messages = [
  {
    id: 'msg-1',
    agent_id: AGENT_RUNNING,
    peer: '123',
    role: 'user',
    content: 'Привет',
    created_at: STAMP,
    direction: 'incoming',
    thread_id: 'thread-1',
  },
  {
    id: 'msg-2',
    agent_id: AGENT_RUNNING,
    peer: '123',
    role: 'assistant',
    content: 'Здравствуйте!',
    created_at: STAMP,
    direction: 'agent_response',
    thread_id: 'thread-1',
  },
];

const actions = [
  {
    id: 'ev-1',
    agent_id: AGENT_RUNNING,
    event_type: 'tool.send_text_message',
    status: 'succeeded',
    created_at: STAMP,
    payload: { turn_id: 't-1', peer: '123' },
    result: { success: true },
    error: null,
  },
  {
    id: 'ev-2',
    agent_id: AGENT_RUNNING,
    event_type: 'tool.get_dialogs',
    status: 'failed',
    created_at: STAMP,
    payload: { turn_id: 't-2', peer: '123' },
    result: null,
    error: 'FloodWait',
  },
];

async function mockAgentPage(page: Page, agentId: string, status: unknown): Promise<void> {
  await mockApi(page, 'GET', `/agents/${agentId}`, status);
}

test.describe('agent page', () => {
  test('rejects an invalid agent id', async ({ page }) => {
    await page.goto('/agent/!!!');
    await expect(page.getByText('Недопустимый ID агента')).toBeVisible();
  });

  test('switches tabs through ?tab=', async ({ page }) => {
    await mockAgentPage(page, AGENT_RUNNING, statusRunning);
    await mockApi(page, 'GET', `/agents/${AGENT_RUNNING}/messages`, messages);
    await mockApi(page, 'GET', `/agents/${AGENT_RUNNING}/actions`, actions);
    await mockApi(page, 'GET', `/agents/${AGENT_RUNNING}/memory`, []);

    await page.goto(`/agent/${AGENT_RUNNING}`);
    await expect(page.getByTestId('agent-tabs')).toBeVisible();

    await page.getByTestId('agent-tab-logs').click();
    await expect(page).toHaveURL(/[?&]tab=logs/);
    await expect(page.getByTestId('log-filter-all')).toBeVisible();

    await page.getByTestId('agent-tab-memory').click();
    await expect(page).toHaveURL(/[?&]tab=memory/);
    await expect(page.getByText('Память пуста')).toBeVisible();

    await page.getByTestId('agent-tab-telegram').click();
    await expect(page).toHaveURL(/[?&]tab=telegram/);
    // Masked phone from the stubbed telegram_sessions row.
    await expect(page.getByText('+799******01')).toBeVisible();
  });

  test('log filters narrow the feed', async ({ page }) => {
    await mockAgentPage(page, AGENT_RUNNING, statusRunning);
    await mockApi(page, 'GET', `/agents/${AGENT_RUNNING}/messages`, messages);
    await mockApi(page, 'GET', `/agents/${AGENT_RUNNING}/actions`, actions);

    await page.goto(`/agent/${AGENT_RUNNING}?tab=logs`);
    await expect(page.getByText('Здравствуйте!')).toBeVisible();

    await page.getByTestId('log-filter-errors').click();
    await expect(page.getByText('Здравствуйте!')).toHaveCount(0);
    await expect(page.getByText('1 записей')).toBeVisible();

    await page.getByTestId('log-filter-all').click();
    await expect(page.getByText('Здравствуйте!')).toBeVisible();
  });

  test('stop confirm dialog calls the API and toasts', async ({ page }) => {
    await mockAgentPage(page, AGENT_RUNNING, statusRunning);
    let stopCalls = 0;
    await page.route(
      `http://127.0.0.1:8000/api/v1/agents/${AGENT_RUNNING}/stop`,
      async (route) => {
        if (route.request().method() !== 'POST') {
          await route.fallback();
          return;
        }
        stopCalls += 1;
        await route.fulfill({ status: 204, body: '' });
      },
    );

    await page.goto(`/agent/${AGENT_RUNNING}?tab=actions`);
    await page.getByRole('button', { name: 'Остановить', exact: true }).first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Остановить агента?')).toBeVisible();
    await dialog.getByRole('button', { name: 'Остановить', exact: true }).click();
    await expect(page.getByTestId('toast-container')).toContainText('Агент остановлен');
    expect(stopCalls).toBe(1);
  });

  test('send-message modal posts a trigger', async ({ page }) => {
    await mockAgentPage(page, AGENT_RUNNING, statusRunning);
    await page.route(
      `http://127.0.0.1:8000/api/v1/agents/${AGENT_RUNNING}/messages/trigger`,
      async (route) => {
        if (route.request().method() !== 'POST') {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ sent: true, message_id: '99' }),
        });
      },
    );

    await page.goto(`/agent/${AGENT_RUNNING}?tab=actions`);
    await page.getByRole('button', { name: 'Отправить', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Отправить сообщение')).toBeVisible();
    await dialog.getByLabel('Получатель (peer)').fill('@someone');
    await dialog.getByLabel('Текст сообщения').fill('Тестовый триггер');
    await dialog.getByRole('button', { name: 'Отправить', exact: true }).click();
    await expect(page.getByTestId('toast-container')).toContainText('Сообщение отправлено');
  });
});

test.describe('empty states', () => {
  test('memory tab shows the empty state', async ({ page }) => {
    await mockAgentPage(page, AGENT_STOPPED, statusStopped);
    await mockApi(page, 'GET', `/agents/${AGENT_STOPPED}/memory`, []);

    await page.goto(`/agent/${AGENT_STOPPED}?tab=memory`);
    await expect(page.getByText('Память пуста')).toBeVisible();
  });

  test('logs tab shows the empty state', async ({ page }) => {
    await mockAgentPage(page, AGENT_STOPPED, statusStopped);
    await mockApi(page, 'GET', `/agents/${AGENT_STOPPED}/messages`, []);
    await mockApi(page, 'GET', `/agents/${AGENT_STOPPED}/actions`, []);

    await page.goto(`/agent/${AGENT_STOPPED}?tab=logs`);
    await expect(page.getByText('Нет записей')).toBeVisible();
  });

  test('telegram tab shows the missing-session state', async ({ page }) => {
    await mockAgentPage(page, AGENT_STOPPED, statusStopped);

    await page.goto(`/agent/${AGENT_STOPPED}?tab=telegram`);
    await expect(page.getByText('Telegram сессия не найдена')).toBeVisible();
  });
});
