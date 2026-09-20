import { describe, expect, test } from 'bun:test';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import {
  EMPTY_FIRST_COMMENT,
  FirstCommentSettingsSection,
  readFirstComment,
} from '@/components/agent/FirstCommentSettings';
import { ToastProvider } from '@/components/ui/toast';
import { firstCommentSchema, agentSettingsSchema } from '@/lib/validators';
import type { FirstCommentSettings } from '@/types';

const AGENT_ID = '11111111-2222-3333-4444-555555555555';

function renderSection(
  value: FirstCommentSettings,
  onChange: (next: FirstCommentSettings) => void = () => {},
) {
  return render(
    <ToastProvider>
      <FirstCommentSettingsSection agentId={AGENT_ID} value={value} onChange={onChange} />
    </ToastProvider>,
  );
}

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
  });

  test('варианты читаются с отсутствующими полями', () => {
    const parsed = readFirstComment({
      first_comment: {
        enabled: true,
        variants: [{ text: 'Первый!' }, { image_path: 'a/pic.jpg', image_name: 'pic.jpg' }, 42],
      },
    });

    expect(parsed.enabled).toBe(true);
    expect(parsed.variants).toEqual([
      { text: 'Первый!', image_path: null, image_name: null },
      { text: '', image_path: 'a/pic.jpg', image_name: 'pic.jpg' },
    ]);
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

  test('настройки агента сохраняются и без ключа — у старых агентов его нет', () => {
    const result = agentSettingsSchema.safeParse({
      name: 'Mimic',
      soul_prompt: 'Характер',
      model: 'z-ai/glm-5.3-flash',
    });
    expect(result.success).toBe(true);
  });
});

describe('FirstCommentSettingsSection', () => {
  test('выключенная настройка не показывает варианты', () => {
    renderSection({
      enabled: false,
      variants: [{ text: 'Первый!', image_path: null, image_name: null }],
    });

    expect(screen.queryByText('Вариант 1')).toBeNull();
    expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('false');
  });

  test('включённая настройка показывает каждый вариант', () => {
    renderSection({
      enabled: true,
      variants: [
        { text: 'Первый!', image_path: null, image_name: null },
        { text: 'Второй!', image_path: null, image_name: null },
      ],
    });

    expect(screen.getByText('Вариант 1')).toBeTruthy();
    expect(screen.getByText('Вариант 2')).toBeTruthy();
    expect(screen.getByDisplayValue('Первый!')).toBeTruthy();
    expect(screen.getByDisplayValue('Второй!')).toBeTruthy();
  });

  test('пустой вариант подсвечивается до сохранения', () => {
    renderSection({
      enabled: true,
      variants: [{ text: '  ', image_path: null, image_name: null }],
    });

    expect(
      screen.getByText('Добавьте текст или картинку — иначе вариант не отправится'),
    ).toBeTruthy();
  });

  test('переключатель сообщает новое значение наверх', async () => {
    const changes: FirstCommentSettings[] = [];
    renderSection(EMPTY_FIRST_COMMENT, (next) => changes.push(next));

    await userEvent.click(screen.getByRole('switch'));

    expect(changes).toEqual([{ enabled: true, variants: [] }]);
  });

  test('добавление варианта даёт пустую заготовку', async () => {
    const changes: FirstCommentSettings[] = [];
    renderSection({ enabled: true, variants: [] }, (next) => changes.push(next));

    await userEvent.click(screen.getByRole('button', { name: /Добавить вариант/ }));

    expect(changes).toEqual([
      { enabled: true, variants: [{ text: '', image_path: null, image_name: null }] },
    ]);
  });

  test('удаление убирает именно выбранный вариант', async () => {
    const changes: FirstCommentSettings[] = [];
    renderSection(
      {
        enabled: true,
        variants: [
          { text: 'раз', image_path: null, image_name: null },
          { text: 'два', image_path: null, image_name: null },
        ],
      },
      (next) => changes.push(next),
    );

    await userEvent.click(screen.getByRole('button', { name: 'Удалить вариант 1' }));

    expect(changes).toEqual([
      { enabled: true, variants: [{ text: 'два', image_path: null, image_name: null }] },
    ]);
  });
});

describe('agentsApi.uploadMedia', () => {
  test('картинка уходит формой, а не JSON-строкой', async () => {
    const { agentsApi, apiClient } = await import('@/lib/api');
    const original = apiClient.defaults.adapter;
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

    try {
      const file = new File([new Uint8Array([1, 2, 3])], 'pic.png', { type: 'image/png' });
      const result = await agentsApi.uploadMedia(AGENT_ID, file);

      expect(result.storage_path).toBe('a/pic.jpg');
      // JSON-заголовок инстанса обязан быть снят до transformRequest: с ним
      // axios сериализует FormData в строку и файл до бэкенда не доедет.
      // Сам multipart-заголовок с boundary ставит уже браузер.
      expect(seen!.data instanceof FormData).toBe(true);
      expect(String(seen!.contentType ?? '')).not.toContain('application/json');
    } finally {
      apiClient.defaults.adapter = original;
    }
  });
});
