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

describe('ActionRow trace link', () => {
  test('ссылка «Трейс» ведёт на trace_url в новой вкладке', () => {
    render(
      <ActionRow
        action={action({ traceUrl: 'https://braintrust.dev/app/p/mimic42/t/turn-1' })}
      />,
    );

    const link = screen.getByRole('link', { name: /Трейс/ });
    expect(link.getAttribute('href')).toBe('https://braintrust.dev/app/p/mimic42/t/turn-1');
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toContain('noreferrer');
  });

  test('без traceUrl ссылки нет', () => {
    render(<ActionRow action={action()} />);

    expect(screen.queryByRole('link')).toBeNull();
  });

  test('у failed-строки видны и hint, и ссылка «Трейс»', () => {
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
    expect(screen.getByRole('link', { name: /Трейс/ })).toBeTruthy();
    // У строк без раскрытия hint виден и на узких экранах — раскрыть их нельзя.
    expect(hint.className).not.toContain('hidden');
  });

  test('ссылка «Трейс» объявляет новую вкладку скринридеру', () => {
    render(
      <ActionRow action={action({ traceUrl: 'https://braintrust.dev/app/p/mimic42/t/turn-1' })} />,
    );

    const link = screen.getByRole('link', { name: /Трейс/ });
    expect(link.textContent).toContain('откроется в новой вкладке');
  });
});
