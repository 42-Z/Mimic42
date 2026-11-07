import { describe, expect, test } from 'bun:test';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TurnCard } from '@/components/activity/TurnCard';
import type { ActivityAction, ActivityItem } from '@/lib/activity/normalize';

const action = (over: Partial<ActivityAction> = {}): ActivityAction => ({
  id: 'a1',
  eventType: 'turn.completed',
  status: 'succeeded',
  label: 'Ход завершён',
  hint: null,
  args: null,
  result: null,
  startedAt: null,
  completedAt: null,
  traceUrl: null,
  ...over,
});

const item = (actions: ActivityAction[], over: Partial<ActivityItem> = {}): ActivityItem => ({
  kind: 'turn',
  id: 'turn:t1',
  agentId: '11111111-2222-3333-4444-555555555555',
  turnId: 't1',
  peer: '123',
  peerTitle: 'Алиса',
  createdAt: '2026-09-26T10:00:00Z',
  endedAt: null,
  failed: false,
  incoming: { id: 'm1', content: 'привет', createdAt: '2026-09-26T10:00:00Z' },
  response: null,
  trigger: null,
  responseReplyTo: null,
  actions,
  ...over,
});

const TRACE_URL = 'https://braintrust.dev/app/p/mimic42/t/turn-1';

describe('TurnCard без ссылок на трассировку', () => {
  test('turn.completed без деталей не раскрывается и не показывает ссылку', () => {
    render(
      <TurnCard
        item={item([action({ traceUrl: TRACE_URL, startedAt: '2026-09-26T10:00:00Z', completedAt: '2026-09-26T10:00:01Z' })])}
      />,
    );

    expect(screen.getByText('Ход завершён')).toBeTruthy();
    expect(screen.queryAllByRole('link').length).toBe(0);
    expect(screen.queryAllByText(/Трейс/).length).toBe(0);
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  test('turn.failed сохраняет текст ошибки без ссылки', () => {
    render(
      <TurnCard
        item={item(
          [
            action({
              eventType: 'turn.failed',
              status: 'failed',
              label: 'Ход завершился ошибкой',
              hint: 'Сессия отозвана, требуется переподключение',
              traceUrl: TRACE_URL,
            }),
          ],
          { failed: true },
        )}
      />,
    );

    expect(screen.getByText('Сессия отозвана, требуется переподключение')).toBeTruthy();
    expect(screen.queryAllByRole('link').length).toBe(0);
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  test('тул с args по-прежнему раскрывается кнопкой', async () => {
    const user = userEvent.setup();
    render(
      <TurnCard
        item={item([
          action({
            id: 'a2',
            eventType: 'tool.send_text_message',
            label: 'Отправить сообщение',
            args: { message: 'Привет!' },
            result: { success: true },
          }),
        ])}
      />,
    );

    const button = screen.getByRole('button', { name: /Отправить сообщение/ });
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByText('Аргументы JSON')).toBeNull();

    await user.click(button);

    expect(button.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText('Аргументы JSON')).toBeTruthy();
    expect(screen.getByText('Результат JSON')).toBeTruthy();
    expect(button.querySelector('a')).toBeNull();
  });

  test('у строки с сырым JSON нет тупика «Детали недоступны»', async () => {
    render(
      <TurnCard
        item={item([
          action({
            id: 'a3',
            eventType: 'tool.send_text_message',
            label: 'Отправить сообщение',
            args: { turn_id: 't1' },
          }),
        ])}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /Отправить сообщение/ }));

    expect(screen.getByText('Аргументы JSON')).toBeTruthy();
    expect(screen.queryByText('Детали недоступны')).toBeNull();
  });

  test('traceUrl не мешает раскрыть аргументы и результат инструмента', async () => {
    const user = userEvent.setup();
    render(
      <TurnCard
        item={item([
          action({
            id: 'a4',
            eventType: 'tool.send_text_message',
            label: 'Отправить сообщение',
            args: { message: 'Привет!' },
            result: { success: true, message_id: 42 },
            traceUrl: TRACE_URL,
          }),
        ])}
      />,
    );

    const button = screen.getByRole('button', { name: /Отправить сообщение/ });
    expect(button.getAttribute('aria-expanded')).toBe('false');

    await user.click(button);

    expect(button.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText('Привет!')).toBeTruthy();
    expect(screen.getByText('42')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Аргументы JSON' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Результат JSON' })).toBeTruthy();
    expect(screen.queryAllByRole('link').length).toBe(0);

    await user.click(button);

    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByText('Аргументы JSON')).toBeNull();
    expect(screen.queryByText('Результат JSON')).toBeNull();
  });

  test('результат без аргументов раскрывается даже при наличии traceUrl', async () => {
    const user = userEvent.setup();
    render(
      <TurnCard
        item={item([
          action({
            eventType: 'tool.get_me',
            label: 'Информация об аккаунте',
            result: { username: 'mimic42' },
            traceUrl: TRACE_URL,
          }),
        ])}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Информация об аккаунте/ }));

    expect(screen.getByText('mimic42')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Результат JSON' })).toBeTruthy();
    expect(screen.queryByText('Аргументы JSON')).toBeNull();
    expect(screen.queryAllByRole('link').length).toBe(0);
  });
});
