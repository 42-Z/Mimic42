import { test, expect } from '@playwright/test';
import {
  USERS,
  createTestAgent,
  deliverMessage,
  recordAgentEvent,
  scriptAgentReply,
  type E2EUser,
} from './helpers';

const fullUserOrUndefined = USERS.full;
if (!fullUserOrUndefined) throw new Error('Missing e2e user full');
const fullUser: E2EUser = fullUserOrUndefined;

test.use({ storageState: fullUser.stateFile });

const PEER_CHAT_ID = 123;

// Никаких page.route: страница агента проверяется против живого бэкенда и
// настоящей базы. Статус и telegram_sessions — настоящие строки, переписка
// рождается настоящим ходом агента (входящее через поддельную телегу, ответ
// поддельной модели), события журнала пишет тот же ActivityRecorder, что и
// в проде. Каждый тест заводит себе агента, чтобы состояние соседей не
// влияло на него.
test.describe('agent page', () => {
  test('rejects an invalid agent id', async ({ page }) => {
    await page.goto('/agent/!!!');
    await expect(page.getByText('Недопустимый ID агента')).toBeVisible();
  });

  test('switches tabs through ?tab=', async ({ page, request }) => {
    const agentId = await createTestAgent(
      request,
      fullUser.id,
      'Вкладки',
      'stopped',
      '+79990000001',
    );

    await page.goto(`/agent/${agentId}`);
    await expect(page.getByTestId('agent-tabs')).toBeVisible();

    await page.getByTestId('agent-tab-logs').click();
    await expect(page).toHaveURL(/[?&]tab=logs/);
    await expect(page.getByTestId('activity-filter-full')).toBeVisible();

    await page.getByTestId('agent-tab-memory').click();
    await expect(page).toHaveURL(/[?&]tab=memory/);
    await expect(page.getByText('Память пуста')).toBeVisible();

    await page.getByTestId('agent-tab-telegram').click();
    await expect(page).toHaveURL(/[?&]tab=telegram/);
    // Masked phone from the real telegram_sessions row, not a mocked route.
    await expect(page.getByText('+799******01')).toBeVisible();
  });

  test('log filters narrow the feed', async ({ page, request }) => {
    const agentId = await createTestAgent(request, fullUser.id, 'Логи', 'running');
    await scriptAgentReply(request, agentId, 'Здравствуйте!');
    await deliverMessage(request, agentId, PEER_CHAT_ID, 'Привет');
    // Tool-call events are seeded through the real recorder: the scripted
    // model bypasses LangGraph, so no tool actually executes this turn.
    await recordAgentEvent(request, agentId, {
      event_type: 'tool.send_text_message',
      status: 'succeeded',
      payload: { turn_id: 'turn-ok', peer: String(PEER_CHAT_ID) },
      result: { success: true },
    });
    await recordAgentEvent(request, agentId, {
      event_type: 'tool.get_dialogs',
      status: 'failed',
      payload: { turn_id: 'turn-fail', peer: String(PEER_CHAT_ID) },
      error: 'FloodWait',
    });

<<<<<<< HEAD
    await page.goto(`/agent/${agentId}?tab=logs`);
    await expect(page.getByText('Здравствуйте!')).toBeVisible();
=======
    await page.goto(`/agent/${AGENT_RUNNING}?tab=logs`);
    // Mock data: 2 messages (turn_id: t-1) + 2 actions (turn_id: t-1, t-2)
    // buildActivityFeed groups them into 2 turns: t-1 (incoming+response+tool) and t-2 (lifecycle)
    await expect(page.getByText('2 записей')).toBeVisible();
>>>>>>> 01301b4 (test: fix mock data with turn_ids for proper activity grouping)

    // Chat filter: only turns with messages (t-1), t-2 lifecycle is excluded
    await page.getByTestId('activity-filter-chat').click();
    await expect(page.getByText('1 записей')).toBeVisible();

    // Back to full view: both items
    await page.getByTestId('activity-filter-full').click();
    await expect(page.getByText('2 записей')).toBeVisible();
  });

  test('stop confirm dialog calls the API and toasts', async ({ page, request }) => {
    const agentId = await createTestAgent(request, fullUser.id, 'Стоп', 'running');

    await page.goto(`/agent/${agentId}?tab=actions`);
    await page.getByRole('button', { name: 'Остановить', exact: true }).first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Остановить агента?')).toBeVisible();
    await dialog.getByRole('button', { name: 'Остановить', exact: true }).click();
    await expect(page.getByTestId('toast-container')).toContainText('Агент остановлен');
    // Настоящий stop: бейдж статуса перечитывает состояние с бэкенда.
    await expect(page.getByLabel('Статус агента: ОСТАНОВЛЕН')).toBeVisible();
  });

  test('send-message modal posts a trigger', async ({ page, request }) => {
    const agentId = await createTestAgent(request, fullUser.id, 'Триггер', 'stopped');

    await page.goto(`/agent/${agentId}?tab=actions`);
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
  test('memory tab shows the empty state', async ({ page, request }) => {
    const agentId = await createTestAgent(request, fullUser.id, 'Без памяти', 'stopped');

    await page.goto(`/agent/${agentId}?tab=memory`);
    await expect(page.getByText('Память пуста')).toBeVisible();
  });

  test('logs tab shows the empty state', async ({ page, request }) => {
    const agentId = await createTestAgent(request, fullUser.id, 'Без логов', 'stopped');

    await page.goto(`/agent/${agentId}?tab=logs`);
    await expect(page.getByText('Нет записей')).toBeVisible();
  });

  test('telegram tab shows the missing-session state', async ({ page, request }) => {
    const agentId = await createTestAgent(
      request,
      fullUser.id,
      'Без сессии',
      'stopped',
      null,
      false,
    );

    await page.goto(`/agent/${agentId}?tab=telegram`);
    await expect(page.getByText('Telegram сессия не найдена')).toBeVisible();
  });
});
