import { describe, expect, test } from 'bun:test';
import { render, screen } from '@testing-library/react';

import { AgentStatusBadge } from '@/components/agents/AgentStatusBadge';
import { isSpamBlocked, spamBlockedFirst } from '@/lib/spamBlock';

const SINCE = '2026-10-10T20:14:44Z';

function agent(name: string, restrictedAt: string | null) {
  return { name, warmup_restricted_at: restrictedAt };
}

describe('AgentStatusBadge в спам-блоке', () => {
  test('у работающего агента вместо «Активен» — «В спам-блоке»', () => {
    render(<AgentStatusBadge state="running" restricted />);

    expect(screen.getByText('В СПАМ-БЛОКЕ')).toBeTruthy();
    expect(screen.queryByText('АКТИВЕН')).toBeNull();
  });

  test('без ограничения работающий агент по-прежнему «Активен»', () => {
    render(<AgentStatusBadge state="running" />);

    expect(screen.getByText('АКТИВЕН')).toBeTruthy();
    expect(screen.queryByText('В СПАМ-БЛОКЕ')).toBeNull();
  });

  test('остановка, запуск и ошибка не подменяются: они про рантайм, а не про аккаунт', () => {
    for (const [state, label] of [
      ['stopped', 'ОСТАНОВЛЕН'],
      ['starting', 'ЗАПУСК'],
      ['error', 'ОШИБКА'],
    ] as const) {
      const { unmount } = render(<AgentStatusBadge state={state} restricted />);
      expect(screen.getByText(label)).toBeTruthy();
      unmount();
    }
  });
});

describe('spamBlockedFirst', () => {
  test('агент в спам-блоке уходит в начало, остальные остаются в своём порядке', () => {
    const ordered = spamBlockedFirst([
      agent('Аня', null),
      agent('Боря', SINCE),
      agent('Вера', null),
      agent('Гоша', SINCE),
    ]);

    expect(ordered.map((a) => a.name)).toEqual(['Боря', 'Гоша', 'Аня', 'Вера']);
  });

  test('исходный список не меняется', () => {
    const source = [agent('Аня', null), agent('Боря', SINCE)];

    spamBlockedFirst(source);

    expect(source.map((a) => a.name)).toEqual(['Аня', 'Боря']);
  });

  test('isSpamBlocked смотрит только на момент ограничения', () => {
    expect(isSpamBlocked(agent('Аня', null))).toBe(false);
    expect(isSpamBlocked(agent('Боря', SINCE))).toBe(true);
  });
});
