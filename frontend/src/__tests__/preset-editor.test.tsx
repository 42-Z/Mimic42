import { describe, expect, mock, test } from 'bun:test';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { PresetEditorDialog } from '@/components/presets/PresetEditorDialog';

function renderEditor(
  overrides: Partial<Parameters<typeof PresetEditorDialog>[0]> = {},
) {
  const onSave = mock((_draft: unknown) => Promise.resolve());
  const props = {
    isOpen: true,
    onClose: () => {},
    onSave,
    ...overrides,
  };
  render(<PresetEditorDialog {...props} />);
  return { onSave };
}

function firstCallArg(hook: { mock: { calls: unknown[][] } }): unknown {
  const call = hook.mock.calls[0];
  if (!call) throw new Error('onSave не вызывался');
  return call[0];
}

describe('PresetEditorDialog', () => {
  test('создание: пустая форма, сохранение отдаёт черновик', async () => {
    const { onSave } = renderEditor();

    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'Олд' } });
    fireEvent.change(screen.getByLabelText('Короткое описание'), {
      target: { value: 'как в 2007' },
    });
    fireEvent.change(screen.getByLabelText('Промпт'), { target: { value: 'Ты олд...' } });

    fireEvent.click(screen.getByTestId('preset-editor-save'));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(firstCallArg(onSave as never)).toEqual({
      title: 'Олд',
      summary: 'как в 2007',
      body: 'Ты олд...',
      settings: null,
    });
  });

  test('пустой промпт не сохраняется', () => {
    renderEditor();
    expect((screen.getByTestId('preset-editor-save') as HTMLButtonElement).disabled).toBe(true);
  });

  test('редактирование: поля из initial, настройки идут насквозь', async () => {
    const { onSave } = renderEditor({
      initial: {
        id: 'preset-1',
        title: 'Старое',
        summary: 'старое описание',
        body: 'старый текст',
        settings: { enabled_tools: ['view_image'], alien: 1 },
      },
    });

    expect(screen.getByLabelText('Название')).toHaveProperty('value', 'Старое');
    expect(screen.getByTestId('tools-settings')).not.toBeNull();

    fireEvent.click(screen.getByTestId('preset-editor-save'));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(firstCallArg(onSave as never)).toEqual({
      title: 'Старое',
      summary: 'старое описание',
      body: 'старый текст',
      settings: { enabled_tools: ['view_image'], alien: 1 },
    });
  });

  test('ошибка сохранения остаётся на экране', async () => {
    const onSave = mock(() => Promise.reject(new Error('permission denied')));
    renderEditor({ onSave });
    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'Олд' } });
    fireEvent.change(screen.getByLabelText('Промпт'), { target: { value: 'Ты олд...' } });
    fireEvent.click(screen.getByTestId('preset-editor-save'));

    await waitFor(() =>
      expect(screen.getByTestId('preset-editor-error').textContent).toContain(
        'permission denied',
      ),
    );
  });
});
