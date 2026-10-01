import { afterEach, describe, expect, mock, test } from 'bun:test';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryCard } from '@/components/agent/MemoryCard';

const memory = {
  id: 'memory-1',
  user_id: 'agent-1',
  memory: 'User says they are doing well',
  created_at: '2026-10-01T11:35:00Z',
};

const originalObserver = globalThis.ResizeObserver;
afterEach(() => {
  globalThis.ResizeObserver = originalObserver;
});

function setup() {
  let resize = () => {};
  const disconnect = mock(() => {});
  globalThis.ResizeObserver = class {
    constructor(callback: ResizeObserverCallback) {
      resize = () => callback([], this);
    }
    observe() {}
    unobserve() {}
    disconnect = disconnect;
  };
  const onShowHistory = mock(() => {});
  render(<MemoryCard memory={memory} onShowHistory={onShowHistory} />);
  const text = screen.getByText(memory.memory);
  let scrollHeight = 84;
  Object.defineProperties(text, {
    clientHeight: { get: () => 84 },
    scrollHeight: { get: () => scrollHeight },
  });
  return {
    text,
    onShowHistory,
    disconnect,
    measure(height: number) {
      scrollHeight = height;
      act(() => resize());
    },
  };
}

describe('MemoryCard', () => {
  test('short memories have no unnecessary expansion control', () => {
    const { text, measure } = setup();
    measure(84);
    expect(text.className).toContain('line-clamp-4');
    expect(text.className).toContain('[overflow-wrap:anywhere]');
    expect(screen.queryByRole('button', { name: 'Показать полностью' })).toBeNull();
  });

  test('long memories expand and collapse without losing text', async () => {
    const { text, measure, disconnect } = setup();
    measure(420);
    const toggle = screen.getByRole('button', { name: 'Показать полностью' });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(toggle.getAttribute('aria-controls')).toBe(text.id);
    await userEvent.click(toggle);
    expect(text.className).not.toContain('line-clamp-4');
    expect(text.textContent).toBe(memory.memory);
    expect(disconnect).toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Свернуть' }));
    expect(text.className).toContain('line-clamp-4');
  });

  test('responsive resizing updates whether expansion is needed', () => {
    const { measure } = setup();
    measure(200);
    expect(screen.getByRole('button', { name: 'Показать полностью' })).toBeTruthy();
    measure(84);
    expect(screen.queryByRole('button', { name: 'Показать полностью' })).toBeNull();
  });

  test('history still opens for the selected memory', async () => {
    const { onShowHistory } = setup();
    await userEvent.click(screen.getByRole('button', { name: 'История' }));
    expect(onShowHistory).toHaveBeenCalledWith(memory.id);
  });
});
