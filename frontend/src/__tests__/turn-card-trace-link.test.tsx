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

describe('TurnCard: ссылка «Трейс» вне кнопок', () => {
  test('turn.completed — строка без кнопки раскрытия, ссылка не внутри button', () => {
    render(
      <TurnCard
        item={item([action({ traceUrl: TRACE_URL, startedAt: '2026-09-26T10:00:00Z', completedAt: '2026-09-26T10:00:01Z' })])}
      />,
    );

    const link = screen.getByRole('link', { name: /Трейс/ });
    expect(link.getAttribute('href')).toBe(TRACE_URL);
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.closest('button')).toBeNull();
    // Единственная кнопка карточки — шапка хода: строка turn.completed
    // не раскрывается (у неё нет args/result).
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  test('turn.failed с hint — видны и ошибка, и ссылка вне button', () => {
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
    expect(screen.getByRole('link', { name: /Трейс/ }).closest('button')).toBeNull();
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  test('тул с args по-прежнему раскрывается кнопкой', async () => {
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

    await userEvent.click(button);

    expect(button.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText('Аргументы JSON')).toBeTruthy();
    // Кнопка раскрытия не вкладывает в себя интерактивные элементы.
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

  test('строка со ссылкой на трейс не оборачивается в кнопку даже у тула', () => {
    // Защита в глубину: <a> не может жить внутри <button> (nested-interactive),
    // поэтому строка со ссылкой всегда остаётся листовой.
    render(
      <TurnCard
        item={item([
          action({
            id: 'a4',
            eventType: 'tool.send_text_message',
            label: 'Отправить сообщение',
            args: { message: 'Привет!' },
            traceUrl: TRACE_URL,
          }),
        ])}
      />,
    );

    expect(screen.getByRole('link', { name: /Трейс/ }).closest('button')).toBeNull();
  });
});
