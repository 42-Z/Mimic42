import { describe, expect, test } from 'bun:test';
import { render, screen } from '@testing-library/react';
import { ActionRow } from '@/components/activity/ActionRow';
import type { ActivityAction } from '@/lib/activity/normalize';

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

describe('ActionRow без ссылок на трассировку', () => {
  test('traceUrl не превращается в пользовательскую ссылку', () => {
    render(
      <ActionRow
        action={action({ traceUrl: 'https://braintrust.dev/app/p/mimic42/t/turn-1' })}
      />,
    );

    expect(screen.getByText('Ход завершён')).toBeTruthy();
    expect(screen.queryAllByRole('link').length).toBe(0);
    expect(screen.queryAllByText(/Трейс/).length).toBe(0);
  });

  test('без traceUrl ссылки нет', () => {
    render(<ActionRow action={action()} />);

    expect(screen.queryAllByRole('link').length).toBe(0);
  });

  test('у failed-строки видна ошибка без ссылки на трассировку', () => {
    render(
      <ActionRow
        action={action({
          eventType: 'turn.failed',
          status: 'failed',
          label: 'Ход завершился ошибкой',
          hint: 'Сессия отозвана, требуется переподключение',
          traceUrl: 'https://braintrust.dev/app/p/mimic42/t/turn-1',
        })}
      />,
    );

    const hint = screen.getByText('Сессия отозвана, требуется переподключение');
    expect(hint).toBeTruthy();
    expect(screen.queryAllByRole('link').length).toBe(0);
    expect(hint.className).not.toContain('hidden');
  });
});
