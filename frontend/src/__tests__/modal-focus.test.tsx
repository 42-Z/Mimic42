import { describe, expect, test } from 'bun:test';
import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { Modal } from '@/components/ui/modal';

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
});
