import { describe, expect, mock, test } from 'bun:test';
import type { ComponentProps } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PresetPickerDialog } from '@/components/agent/PresetPicker';
import type { PromptPresetRow } from '@/types';

const PRESETS: PromptPresetRow[] = [
  {
    id: '11111111-1111-1111-1111-111111111111',
    slug: 'rage_comments',
    title: 'Рейджбейт в комментариях',
    summary: 'спорит под постами',
    body: 'ТЕЛО РЕЙДЖБЕЙТА',
    sort_order: 1,
    is_active: true,
    created_at: '2026-09-20T00:00:00Z',
    updated_at: '2026-09-20T00:00:00Z',
  },
  {
    id: '22222222-2222-2222-2222-222222222222',
    slug: 'sasavot_fan',
    title: 'Фанат сасыча',
    summary: 'пацанский олд',
    body: 'ТЕЛО ФАНАТА',
    sort_order: 2,
    is_active: true,
    created_at: '2026-09-20T00:00:00Z',
    updated_at: '2026-09-20T00:00:00Z',
  },
];

function renderDialog(overrides: Partial<ComponentProps<typeof PresetPickerDialog>> = {}) {
  const onApply = mock((_body: string) => {});
  const onClose = mock(() => {});
  render(
    <PresetPickerDialog
      isOpen
      onClose={onClose}
      presets={PRESETS}
      isLoading={false}
      isError={false}
      currentValue=""
      onApply={onApply}
      {...overrides}
    />,
  );
  return { onApply, onClose };
}

describe('PresetPickerDialog', () => {
  test('показывает названия, описания и тело первого пресета', () => {
    renderDialog();
    expect(screen.getByText('Рейджбейт в комментариях')).toBeTruthy();
    expect(screen.getByText('спорит под постами')).toBeTruthy();
    expect(screen.getByText('Фанат сасыча')).toBeTruthy();
    expect(screen.getByTestId('preset-body').textContent).toBe('ТЕЛО РЕЙДЖБЕЙТА');
  });

  test('выбор другого пресета показывает его тело', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole('option', { name: /Фанат сасыча/ }));
    expect(screen.getByTestId('preset-body').textContent).toBe('ТЕЛО ФАНАТА');
  });

  test('пустое поле — применение сразу отдаёт текст наверх', async () => {
    const user = userEvent.setup();
    const { onApply } = renderDialog({ currentValue: '   ' });
    await user.click(screen.getByRole('button', { name: 'Применить пресет' }));
    expect(onApply).toHaveBeenCalledWith('ТЕЛО РЕЙДЖБЕЙТА');
  });

  test('непустое поле — первый клик только предупреждает, второй применяет', async () => {
    const user = userEvent.setup();
    const { onApply } = renderDialog({ currentValue: 'мой старый характер' });

    await user.click(screen.getByRole('button', { name: 'Применить пресет' }));
    expect(onApply).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toContain('будет заменён');

    await user.click(screen.getByRole('button', { name: 'Всё равно заменить' }));
    expect(onApply).toHaveBeenCalledWith('ТЕЛО РЕЙДЖБЕЙТА');
  });

  test('смена пресета сбрасывает предупреждение', async () => {
    const user = userEvent.setup();
    const { onApply } = renderDialog({ currentValue: 'мой старый характер' });

    await user.click(screen.getByRole('button', { name: 'Применить пресет' }));
    await user.click(screen.getByRole('option', { name: /Фанат сасыча/ }));
    expect(screen.queryByRole('alert')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Применить пресет' }));
    expect(onApply).not.toHaveBeenCalled();
  });

  test('ошибка загрузки не подменяется пустым списком', () => {
    renderDialog({ presets: [], isError: true });
    expect(screen.getByRole('alert').textContent).toContain('Не удалось загрузить пресеты');
    expect(screen.queryByRole('option')).toBeNull();
  });

  test('пустой справочник говорит об этом прямо', () => {
    renderDialog({ presets: [] });
    expect(screen.getByText('Пресетов пока нет')).toBeTruthy();
  });
});
