import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import {
  EMPTY_FIRST_COMMENT,
  FirstCommentSettingsSection,
  imageProblem,
  readFirstComment,
  type FirstCommentDraft,
  type FirstCommentDraftVariant,
} from '@/components/agent/FirstCommentSettings';
import { agentsApi, apiClient } from '@/lib/api';
import { firstCommentSchema, agentSettingsSchema } from '@/lib/validators';
import type { FirstCommentVariant, UploadedMedia } from '@/types';

const AGENT_ID = '11111111-2222-3333-4444-555555555555';

function variant(text: string, key = text): FirstCommentDraftVariant {
  return { key, text, image_path: null, image_name: null };
}

/** Секция с настоящим состоянием: обновления-функции применяются как в форме. */
function renderSection(initial: FirstCommentDraft, error?: string) {
  const seen: { current: FirstCommentDraft } = { current: initial };
  function Harness() {
    const [value, setValue] = useState(initial);
    seen.current = value;
    return (
      <FirstCommentSettingsSection
        agentId={AGENT_ID}
        value={value}
        onChange={(update) => setValue((prev) => update(prev))}
        error={error}
      />
    );
  }
  render(<Harness />);
  return seen;
}

function fileInput(index: number): HTMLInputElement {
  return document.querySelectorAll<HTMLInputElement>('input[type="file"]')[index]!;
}

function withoutKeys(value: FirstCommentDraft): { enabled: boolean; variants: FirstCommentVariant[] } {
  return {
    enabled: value.enabled,
    variants: value.variants.map(({ key: _key, ...rest }) => rest),
  };
}

const originalUpload = agentsApi.uploadMedia;
const originalAdapter = apiClient.defaults.adapter;

beforeEach(() => {
  // Превью картинки ходит за файлом в API — в тестах отвечаем пустым блобом.
  apiClient.defaults.adapter = async (config) => ({
    data: new Blob([new Uint8Array([1])], { type: 'image/png' }),
    status: 200,
    statusText: 'OK',
    headers: {},
    config,
  });
});

afterEach(() => {
  agentsApi.uploadMedia = originalUpload;
  apiClient.defaults.adapter = originalAdapter;
});

describe('readFirstComment', () => {
  test('у агента без настройки она выключена', () => {
    expect(readFirstComment(null)).toEqual(EMPTY_FIRST_COMMENT);
    expect(readFirstComment({})).toEqual(EMPTY_FIRST_COMMENT);
  });

  test('чужая форма не роняет форму настроек', () => {
    expect(readFirstComment({ first_comment: 'on' })).toEqual(EMPTY_FIRST_COMMENT);
    expect(readFirstComment({ first_comment: { enabled: true, variants: 'nope' } })).toEqual({
      enabled: true,
      variants: [],
    });
    expect(readFirstComment({ first_comment: { enabled: 'true', variants: [] } }).enabled).toBe(
      false,
    );
  });

  test('варианты читаются с отсутствующими полями и получают разные ключи', () => {
    const parsed = readFirstComment({
      first_comment: {
        enabled: true,
        variants: [{ text: 'Первый!' }, { image_path: 'a/pic.jpg', image_name: 'pic.jpg' }, 42],
      },
    });

    expect(parsed.enabled).toBe(true);
    expect(withoutKeys(parsed).variants).toEqual([
      { text: 'Первый!', image_path: null, image_name: null },
      { text: '', image_path: 'a/pic.jpg', image_name: 'pic.jpg' },
    ]);
    expect(new Set(parsed.variants.map((item) => item.key)).size).toBe(2);
  });
});

describe('firstCommentSchema', () => {
  test('включённая настройка без вариантов отклоняется', () => {
    const result = firstCommentSchema.safeParse({ enabled: true, variants: [] });
    expect(result.success).toBe(false);
  });

  test('выключенная настройка без вариантов допустима', () => {
    expect(firstCommentSchema.safeParse({ enabled: false, variants: [] }).success).toBe(true);
  });

  test('вариант без текста и картинки отклоняется', () => {
    const result = firstCommentSchema.safeParse({
      enabled: true,
      variants: [{ text: '   ', image_path: null, image_name: null }],
    });
    expect(result.success).toBe(false);
  });

  test('подпись к картинке ограничена 1024 символами', () => {
    const withImage = (text: string) =>
      firstCommentSchema.safeParse({
        enabled: true,
        variants: [{ text, image_path: 'a/pic.jpg', image_name: 'pic.jpg' }],
      }).success;

    expect(withImage('x'.repeat(1024))).toBe(true);
    expect(withImage('x'.repeat(1025))).toBe(false);
  });

  test('текст без картинки живёт до 4096 символов', () => {
    const withoutImage = (text: string) =>
      firstCommentSchema.safeParse({
        enabled: true,
        variants: [{ text, image_path: null, image_name: null }],
      }).success;

    expect(withoutImage('x'.repeat(4096))).toBe(true);
    expect(withoutImage('x'.repeat(4097))).toBe(false);
  });

  test('ключи строк формы не попадают в сохраняемые настройки', () => {
    const result = agentSettingsSchema.safeParse({
      name: 'Mimic',
      soul_prompt: 'Характер',
      model: 'z-ai/glm-5.3-flash',
      first_comment: { enabled: true, variants: [variant('Первый!', 'variant-7')] },
    });

    expect(result.success).toBe(true);
    expect(result.data?.first_comment?.variants[0]).toEqual({
      text: 'Первый!',
      image_path: null,
      image_name: null,
    });
  });

  test('настройки агента сохраняются и без ключа — у старых агентов его нет', () => {
    const result = agentSettingsSchema.safeParse({
      name: 'Mimic',
      soul_prompt: 'Характер',
      model: 'z-ai/glm-5.3-flash',
    });
    expect(result.success).toBe(true);
  });
});

describe('imageProblem', () => {
  test('JPEG и PNG до 10 МБ проходят', () => {
    expect(imageProblem(new File([new Uint8Array(3)], 'a.png', { type: 'image/png' }))).toBeNull();
    expect(imageProblem(new File([new Uint8Array(3)], 'a.jpg', { type: 'image/jpeg' }))).toBeNull();
  });

  test('другой формат и слишком большой файл отсекаются до загрузки', () => {
    expect(imageProblem(new File([new Uint8Array(3)], 'a.gif', { type: 'image/gif' }))).toContain(
      'JPEG или PNG',
    );
    const big = new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'big.png', { type: 'image/png' });
    expect(imageProblem(big)).toContain('10 МБ');
  });
});

describe('FirstCommentSettingsSection', () => {
  test('выключенная настройка не показывает варианты', () => {
    renderSection({ enabled: false, variants: [variant('Первый!')] });

    expect(screen.queryByText('Вариант 1')).toBeNull();
    expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('false');
  });

  test('включённая настройка показывает каждый вариант', () => {
    renderSection({ enabled: true, variants: [variant('Первый!'), variant('Второй!')] });

    expect(screen.getByText('Вариант 1')).toBeTruthy();
    expect(screen.getByText('Вариант 2')).toBeTruthy();
    expect(screen.getByDisplayValue('Первый!')).toBeTruthy();
    expect(screen.getByDisplayValue('Второй!')).toBeTruthy();
  });

  test('пустой вариант подсвечивается до сохранения', () => {
    renderSection({ enabled: true, variants: [variant('  ')] });

    expect(
      screen.getByText('Добавьте текст или картинку — иначе вариант не отправится'),
    ).toBeTruthy();
  });

  test('новый вариант не ругается, пока в поле не начинали вводить', async () => {
    renderSection({ enabled: true, variants: [] });
    const empty = 'Добавьте текст или картинку — иначе вариант не отправится';

    await userEvent.click(screen.getByRole('button', { name: 'Добавить вариант' }));
    expect(screen.queryByText(empty)).toBeNull();

    await userEvent.click(screen.getByLabelText('Текст варианта 1'));
    await userEvent.tab();
    expect(screen.getByText(empty)).toBeTruthy();
  });

  test('после неудачного сохранения пустой вариант подсвечен сразу', () => {
    renderSection({ enabled: true, variants: [variant('')] }, 'Нужен текст или картинка');

    expect(
      screen.getByText('Добавьте текст или картинку — иначе вариант не отправится'),
    ).toBeTruthy();
  });

  test('переключатель включает настройку', async () => {
    const seen = renderSection(EMPTY_FIRST_COMMENT);

    await userEvent.click(screen.getByRole('switch'));

    expect(seen.current).toEqual({ enabled: true, variants: [] });
  });

  test('добавление варианта даёт пустую заготовку', async () => {
    const seen = renderSection({ enabled: true, variants: [] });

    await userEvent.click(screen.getByRole('button', { name: /Добавить вариант/ }));

    expect(withoutKeys(seen.current).variants).toEqual([
      { text: '', image_path: null, image_name: null },
    ]);
  });

  test('удаление убирает именно выбранный вариант', async () => {
    const seen = renderSection({ enabled: true, variants: [variant('раз'), variant('два')] });

    await userEvent.click(screen.getByRole('button', { name: 'Удалить вариант 1' }));

    expect(withoutKeys(seen.current).variants).toEqual([
      { text: 'два', image_path: null, image_name: null },
    ]);
  });

  test('картинка, загруженная позже ввода, не затирает введённый текст', async () => {
    let finish: (value: UploadedMedia) => void = () => {};
    agentsApi.uploadMedia = () =>
      new Promise<UploadedMedia>((resolve) => {
        finish = resolve;
      });
    const seen = renderSection({ enabled: true, variants: [variant('', 'a'), variant('два', 'b')] });

    const firstInput = fileInput(0);
    await userEvent.upload(firstInput, new File([new Uint8Array(3)], 'pic.png', { type: 'image/png' }));
    // Пока картинка грузится, пишут подпись и удаляют соседний вариант.
    await userEvent.type(screen.getAllByRole('textbox')[0]!, 'подпись');
    await userEvent.click(screen.getByRole('button', { name: 'Удалить вариант 2' }));
    await act(async () => {
      finish({ storage_path: 'agent/pic.png', name: 'pic.png', mime_type: 'image/png', size: 3 });
    });

    expect(withoutKeys(seen.current).variants).toEqual([
      { text: 'подпись', image_path: 'agent/pic.png', image_name: 'pic.png' },
    ]);
  });

  test('картинка удалённого варианта никуда не прилипает', async () => {
    let finish: (value: UploadedMedia) => void = () => {};
    agentsApi.uploadMedia = () =>
      new Promise<UploadedMedia>((resolve) => {
        finish = resolve;
      });
    const seen = renderSection({ enabled: true, variants: [variant('раз', 'a'), variant('два', 'b')] });

    const firstInput = fileInput(0);
    await userEvent.upload(firstInput, new File([new Uint8Array(3)], 'pic.png', { type: 'image/png' }));
    await userEvent.click(screen.getByRole('button', { name: 'Удалить вариант 1' }));
    await act(async () => {
      finish({ storage_path: 'agent/pic.png', name: 'pic.png', mime_type: 'image/png', size: 3 });
    });

    expect(withoutKeys(seen.current).variants).toEqual([
      { text: 'два', image_path: null, image_name: null },
    ]);
  });

  test('неподходящий файл объясняется рядом с полем и не загружается', async () => {
    let uploads = 0;
    agentsApi.uploadMedia = async () => {
      uploads += 1;
      throw new Error('не должно вызываться');
    };
    renderSection({ enabled: true, variants: [variant('раз')] });

    const input = fileInput(0);
    // accept у скрытого input не мешает drag-and-drop и «все файлы» в диалоге.
    await userEvent.upload(input, new File([new Uint8Array(3)], 'anim.gif', { type: 'image/gif' }), {
      applyAccept: false,
    });

    expect(uploads).toBe(0);
    expect(screen.getByRole('alert').textContent).toContain('JPEG или PNG');
  });

  test('ошибка сервера показывается у варианта, а не теряется', async () => {
    agentsApi.uploadMedia = async () => {
      throw { message: 'Поддерживаются только изображения JPEG и PNG' };
    };
    renderSection({ enabled: true, variants: [variant('раз')] });

    const input = fileInput(0);
    await userEvent.upload(input, new File([new Uint8Array(3)], 'pic.png', { type: 'image/png' }));

    expect(screen.getByRole('alert').textContent).toContain(
      'Поддерживаются только изображения JPEG и PNG',
    );
  });
});

describe('agentsApi.uploadMedia', () => {
  test('картинка уходит формой, а не JSON-строкой', async () => {
    let seen: { data: unknown; contentType: unknown } | null = null;

    apiClient.defaults.adapter = async (config) => {
      seen = { data: config.data, contentType: config.headers?.['Content-Type'] };
      return {
        data: { storage_path: 'a/pic.jpg', name: 'pic.jpg', mime_type: 'image/png', size: 3 },
        status: 201,
        statusText: 'Created',
        headers: {},
        config,
      };
    };

    const file = new File([new Uint8Array([1, 2, 3])], 'pic.png', { type: 'image/png' });
    const result = await agentsApi.uploadMedia(AGENT_ID, file);

    expect(result.storage_path).toBe('a/pic.jpg');
    // JSON-заголовок инстанса обязан быть снят до transformRequest: с ним
    // axios сериализует FormData в строку и файл до бэкенда не доедет.
    // Сам multipart-заголовок с boundary ставит уже браузер.
    expect(seen!.data instanceof FormData).toBe(true);
    expect(String(seen!.contentType ?? '')).not.toContain('application/json');
  });
});
