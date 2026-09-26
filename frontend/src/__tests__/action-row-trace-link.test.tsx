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
});
