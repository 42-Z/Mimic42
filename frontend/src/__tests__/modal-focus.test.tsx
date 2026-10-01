import { describe, expect, test } from 'bun:test';
import { useEffect, useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Modal } from '@/components/ui/modal';
import { ToastProvider, useToast } from '@/components/ui/toast';

// Radix вешает pointerdown-слушатель на document через setTimeout(0), а
// закрытие по outside-взаимодействию деферрит до click.
const flushTimer = () => new Promise((resolve) => setTimeout(resolve, 20));

async function clickOutside(target: Element) {
  await flushTimer();
  fireEvent.pointerDown(target);
  fireEvent.mouseUp(target);
  fireEvent.click(target);
}

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>Открыть</button>
      <Modal isOpen={open} onClose={() => setOpen(false)} title="Тест">
        <button>Внутри</button>
      </Modal>
    </>
  );
}

let showToast: (() => void) | null = null;

function ToastHarness() {
  const { toast } = useToast();
  const [open, setOpen] = useState(true);

  useEffect(() => {
    showToast = () => toast('Не удалось сбросить контекст', 'error', 0);
  }, [toast]);

  return (
    <Modal isOpen={open} onClose={() => setOpen(false)} title="Сбросить контекст?">
      <button>Внутри</button>
    </Modal>
  );
}

describe('Modal', () => {
  test('возвращает фокус на элемент-триггер после закрытия', () => {
    render(<Harness />);
    const trigger = screen.getByRole('button', { name: 'Открыть' });
    trigger.focus();

    fireEvent.click(trigger);
    // Фокус-ловушка уводит фокус внутрь диалога.
    expect(trigger).not.toBe(document.activeElement);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(document.activeElement).toBe(trigger);
  });

  test('клик вне панели закрывает диалог', async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'Открыть' }));
    expect(screen.getByRole('dialog')).toBeTruthy();

    await clickOutside(document.body);

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  test('взаимодействие с тостом не закрывает диалог', async () => {
    render(
      <ToastProvider>
        <ToastHarness />
      </ToastProvider>,
    );

    act(() => showToast?.());
    // Radix прячет от a11y-дерева всё вне диалога (aria-hidden), поэтому тост
    // ищем в DOM: проверяем именно outside-dismiss, а не доступность тоста.
    const closeToast = document.querySelector<HTMLButtonElement>(
      '[data-testid="toast-container"] button',
    );
    if (!closeToast) throw new Error('Тост не отрендерился');

    await clickOutside(closeToast);

    // Тост живёт в отдельном портале, но не должен считаться outside-dismiss.
    expect(screen.getByRole('dialog')).toBeTruthy();
  });
});
