import { describe, expect, mock, test } from 'bun:test';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import {
  PresetEditorDialog,
  type PresetEditorInitial,
} from '@/components/presets/PresetEditorDialog';

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
  const view = render(<PresetEditorDialog {...props} />);
  return {
    onSave,
    rerender: (next: Partial<typeof props>) => {
      Object.assign(props, next);
      view.rerender(<PresetEditorDialog {...props} />);
    },
  };
}

function firstCallArg(hook: { mock: { calls: unknown[][] } }): unknown {
  const call = hook.mock.calls[0];
  if (!call) throw new Error('onSave не вызывался');
  return call[0];
}

function initialPreset(): PresetEditorInitial {
  return {
    id: 'preset-1',
    title: 'Старое название',
    summary: 'Старое описание',
    body: 'Старый промпт',
    settings: { enabled_tools: ['view_image', 'future_tool'], alien: { keep: true } },
  };
}

const editedDraft = {
  title: 'Новое название',
  summary: 'Новое описание',
  body: 'Новый промпт\nс продолжением',
  settings: { enabled_tools: ['future_tool'], alien: { keep: true } },
};

function editDraft() {
  fireEvent.change(screen.getByLabelText('Название'), {
    target: { value: editedDraft.title },
  });
  fireEvent.change(screen.getByLabelText('Короткое описание'), {
    target: { value: editedDraft.summary },
  });
  fireEvent.change(screen.getByLabelText('Промпт'), {
    target: { value: editedDraft.body },
  });
  fireEvent.change(screen.getByLabelText('Поиск'), { target: { value: 'view_image' } });
  fireEvent.click(screen.getByRole('switch', { name: 'Просмотр изображений' }));
}

function expectEditedDraft() {
  expect(screen.getByLabelText('Название')).toHaveProperty('value', editedDraft.title);
  expect(screen.getByLabelText('Короткое описание')).toHaveProperty('value', editedDraft.summary);
  expect(screen.getByLabelText('Промпт')).toHaveProperty('value', editedDraft.body);
  expect(screen.getByRole('switch', { name: 'Просмотр изображений' }).getAttribute('aria-checked'))
    .toBe('false');
}

function deferredSave() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
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

  test('новый объект initial с тем же id не сбрасывает изменённые поля и настройки', async () => {
    const initial = initialPreset();
    const { onSave, rerender } = renderEditor({ initial });
    editDraft();

    rerender({
      initial: {
        ...initial,
        title: 'Название после refetch',
        summary: 'Описание после refetch',
        body: 'Промпт после refetch',
        settings: { enabled_tools: [], alien: 'server' },
      },
    });

    expectEditedDraft();
    fireEvent.click(screen.getByTestId('preset-editor-save'));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(firstCallArg(onSave)).toEqual(editedDraft);
  });

  test('ререндер во время запроса сохраняет черновик и блокировку до завершения', async () => {
    const request = deferredSave();
    const onSave = mock(() => request.promise);
    const onClose = mock(() => {});
    const initial = initialPreset();
    const { rerender } = renderEditor({ initial, onSave, onClose });
    editDraft();
    fireEvent.submit(screen.getByTestId('preset-editor'));

    rerender({ initial: { ...initial } });

    expect((screen.getByTestId('preset-editor-save') as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId('preset-editor-save').textContent).toBe('Сохраняю…');
    expectEditedDraft();
    fireEvent.submit(screen.getByTestId('preset-editor'));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onClose.mock.calls.length).toBe(0);

    await act(async () => request.resolve());
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('два синхронных submit запускают только один запрос', async () => {
    const request = deferredSave();
    const onSave = mock(() => request.promise);
    renderEditor({ initial: initialPreset(), onSave });
    const form = screen.getByTestId('preset-editor');

    act(() => {
      fireEvent.submit(form);
      fireEvent.submit(form);
    });

    expect(onSave).toHaveBeenCalledTimes(1);
    await act(async () => request.resolve());
  });

  test('ошибка mutateAsync и ререндеры сохраняют все поля, настройки и повторное сохранение', async () => {
    const request = deferredSave();
    const onSave = mock((_draft: unknown) => request.promise);
    const onClose = mock(() => {});
    const initial = initialPreset();
    const { rerender } = renderEditor({ initial, onSave, onClose });
    editDraft();
    fireEvent.submit(screen.getByTestId('preset-editor'));
    rerender({ initial: { ...initial } });

    await act(async () => request.reject(new Error('permission denied')));
    rerender({ initial: { ...initial } });

    expectEditedDraft();
    expect(screen.getByRole('alert').textContent).toContain('permission denied');
    expect((screen.getByTestId('preset-editor-save') as HTMLButtonElement).disabled).toBe(false);
    expect(onClose.mock.calls.length).toBe(0);
    onSave.mockImplementation(() => Promise.resolve());
    fireEvent.submit(screen.getByTestId('preset-editor'));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls).toEqual([[editedDraft], [editedDraft]]);
  });

  test('во время сохранения Отмена, крестик и Escape не закрывают редактор', async () => {
    const request = deferredSave();
    const onClose = mock(() => {});
    renderEditor({ initial: initialPreset(), onSave: () => request.promise, onClose });
    fireEvent.submit(screen.getByTestId('preset-editor'));

    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });

    expect(onClose.mock.calls.length).toBe(0);
    expect((screen.getByTestId('preset-editor-save') as HTMLButtonElement).disabled).toBe(true);
    await act(async () => request.resolve());
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('закрытие без сохранения остаётся доступно', () => {
    const onClose = mock(() => {});
    renderEditor({ onClose });
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('закрытие и повторное открытие того же id создают свежий черновик', async () => {
    const initial = initialPreset();
    const { onSave, rerender } = renderEditor({ initial });
    editDraft();
    rerender({ isOpen: false });
    expect(screen.queryByTestId('preset-editor') === null).toBe(true);

    rerender({ isOpen: true, initial: { ...initial, title: 'Обновлённое название' } });
    expect(screen.getByLabelText('Название')).toHaveProperty('value', 'Обновлённое название');
    expect(screen.getByLabelText('Короткое описание')).toHaveProperty('value', initial.summary);
    expect(screen.getByLabelText('Промпт')).toHaveProperty('value', initial.body);
    expect(screen.queryByRole('alert') === null).toBe(true);
    fireEvent.submit(screen.getByTestId('preset-editor'));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(firstCallArg(onSave)).toEqual({
      title: 'Обновлённое название',
      summary: initial.summary,
      body: initial.body,
      settings: initial.settings,
    });
  });

  test('новый пресет после закрытия открывается пустым', () => {
    const { rerender } = renderEditor();
    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'Черновик' } });
    fireEvent.change(screen.getByLabelText('Промпт'), { target: { value: 'Промпт' } });
    rerender({ isOpen: false });
    rerender({ isOpen: true });
    expect(screen.getByLabelText('Название')).toHaveProperty('value', '');
    expect(screen.getByLabelText('Короткое описание')).toHaveProperty('value', '');
    expect(screen.getByLabelText('Промпт')).toHaveProperty('value', '');
    expect((screen.getByTestId('preset-editor-save') as HTMLButtonElement).disabled).toBe(true);
  });

  test('смена id сбрасывает все поля, настройки и ошибку предыдущего пресета', async () => {
    const onSave = mock((_draft: unknown): Promise<void> => Promise.reject(new Error('Ошибка первого')));
    const { rerender } = renderEditor({ initial: initialPreset(), onSave });
    editDraft();
    fireEvent.submit(screen.getByTestId('preset-editor'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('Ошибка первого'));
    const next = {
      id: 'preset-2',
      title: 'Второй',
      summary: 'Второе описание',
      body: 'Второй промпт',
      settings: { enabled_tools: [], different: true },
    };

    rerender({ initial: next });

    expect(screen.getByLabelText('Название')).toHaveProperty('value', next.title);
    expect(screen.getByLabelText('Короткое описание')).toHaveProperty('value', next.summary);
    expect(screen.getByLabelText('Промпт')).toHaveProperty('value', next.body);
    expect(screen.queryByRole('alert') === null).toBe(true);
    onSave.mockImplementation(() => Promise.resolve());
    fireEvent.submit(screen.getByTestId('preset-editor'));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
    expect(onSave.mock.calls[1]).toEqual([{
      title: next.title,
      summary: next.summary,
      body: next.body,
      settings: next.settings,
    }]);
  });

  for (const transition of ['reopen', 'different-id'] as const) {
    for (const outcome of ['resolve', 'reject'] as const) {
      test(`устаревшее ${outcome} после ${transition} не закрывает и не разблокирует новую сессию`, async () => {
        const previousRequest = deferredSave();
        const currentRequest = deferredSave();
        const onSave = mock((_draft: unknown) => previousRequest.promise);
        const onClose = mock(() => {});
        const initial = initialPreset();
        const { rerender } = renderEditor({ initial, onSave, onClose });
        fireEvent.submit(screen.getByTestId('preset-editor'));

        if (transition === 'reopen') {
          rerender({ isOpen: false });
          rerender({ isOpen: true, initial: { ...initial } });
        } else {
          rerender({ initial: { ...initial, id: 'preset-2' } });
        }
        editDraft();
        onSave.mockImplementation(() => currentRequest.promise);
        fireEvent.submit(screen.getByTestId('preset-editor'));
        expect(onSave).toHaveBeenCalledTimes(2);

        await act(async () => {
          if (outcome === 'resolve') previousRequest.resolve();
          else previousRequest.reject(new Error('Устаревшая ошибка'));
        });

        expect(onClose.mock.calls.length).toBe(0);
        expectEditedDraft();
        expect(screen.queryByRole('alert') === null).toBe(true);
        expect((screen.getByTestId('preset-editor-save') as HTMLButtonElement).disabled).toBe(true);
        fireEvent.submit(screen.getByTestId('preset-editor'));
        expect(onSave).toHaveBeenCalledTimes(2);
        await act(async () => currentRequest.resolve());
        expect(onClose).toHaveBeenCalledTimes(1);
      });
    }
  }
});
