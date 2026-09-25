import { describe, expect, test } from 'bun:test';
import { render, screen, fireEvent } from '@testing-library/react';
import { AgentToggleButton } from '@/components/agents/AgentToggleButton';
import type { AgentState } from '@/types';

function renderButton(
  overrides: Partial<React.ComponentProps<typeof AgentToggleButton>> = {},
) {
  const calls: string[] = [];
  const props: React.ComponentProps<typeof AgentToggleButton> = {
    agentId: 'agent-1',
    state: 'stopped',
    needsRebind: false,
    onStart: () => calls.push('start'),
    onStop: () => calls.push('stop'),
    ...overrides,
  };
  return { ...render(<AgentToggleButton {...props} />), calls };
}

describe('AgentToggleButton', () => {
  test('вместо пары «Запустить»/«Стоп» рисует ровно одну кнопку', () => {
    renderButton({ state: 'running' });
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  test('в остановленном состоянии запускает агента', () => {
    const { calls } = renderButton({ state: 'stopped' });
    const button = screen.getByRole('button');
    expect(button.textContent).toContain('Запустить');
    expect(button.hasAttribute('disabled')).toBe(false);
    fireEvent.click(button);
    expect(calls).toEqual(['start']);
    expect(screen.queryByText('Стоп')).toBeNull();
  });

  test('в состоянии ошибки тоже предлагает запустить', () => {
    renderButton({ state: 'error' });
    expect(screen.getByRole('button').textContent).toContain('Запустить');
  });

  test('в запущенном состоянии останавливает агента', () => {
    const { calls } = renderButton({ state: 'running' });
    expect(screen.getByRole('button').textContent).toContain('Остановить');
    expect(screen.queryByText('Запустить')).toBeNull();
    fireEvent.click(screen.getByRole('button'));
    expect(calls).toEqual(['stop']);
  });

  test('во время запуска показывает «Запускается…» и заблокирована', () => {
    renderButton({ state: 'starting' });
    const button = screen.getByRole('button');
    expect(button.textContent).toContain('Запускается');
    expect(button.hasAttribute('disabled')).toBe(true);
  });

  test('во время остановки показывает «Останавливается…» и заблокирована', () => {
    renderButton({ state: 'stopping' });
    const button = screen.getByRole('button');
    expect(button.textContent).toContain('Останавливается');
    expect(button.hasAttribute('disabled')).toBe(true);
  });

  test('пока статус неизвестен, кнопка заблокирована', () => {
    renderButton({ state: undefined });
    const button = screen.getByRole('button');
    expect(button.textContent).toContain('Запустить');
    expect(button.hasAttribute('disabled')).toBe(true);
  });

  test('нужна перепривязка — вместо кнопки управления ссылка на перепривязку', () => {
    renderButton({ state: 'stopped', needsRebind: true });
    expect(screen.queryByRole('button')).toBeNull();
    const link = screen.getByRole('link');
    expect(link.textContent).toContain('Перепривязать');
    expect(link.getAttribute('href')).toBe('/agent/agent-1/rebind');
  });

  const states: AgentState[] = ['draft', 'stopped', 'starting', 'running', 'stopping', 'error'];
  for (const state of states) {
    test(`состояние «${state}» даёт не более одной кнопки управления`, () => {
      renderButton({ state });
      expect(screen.getAllByRole('button').length).toBeLessThanOrEqual(1);
    });
  }
});
