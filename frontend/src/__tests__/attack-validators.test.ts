import { describe, expect, test } from 'bun:test';
import { attackCreateSchema, attackEditSchema } from '@/lib/attacks/validators';
import type { AttackEditFormState, AttackFormState } from '@/lib/attacks/types';

const AGENT_ID = '9f1c7a3e-2b4d-4c8a-9e6f-1a2b3c4d5e6f';
const IMAGE = { path: 'attacks/owner/uuid/cat.jpg', name: 'cat.jpg' };

const draft: AttackFormState = {
  title: '',
  target_link: 'https://t.me/example/412',
  texts: ['Участвую!'],
  images: [],
  limit_kind: 'messages',
  message_limit: 40,
  duration_minutes: null,
  agent_ids: [],
};

describe('attackCreateSchema — цель', () => {
  test('без ссылки на пост форма не проходит', () => {
    const missing = attackCreateSchema.safeParse({ ...draft, target_link: '' });
    expect(missing.success).toBe(false);
    if (!missing.success) {
      expect(missing.error.issues[0]?.path).toEqual(['target_link']);
    }
  });

  test('чужой хост и ссылка на канал без поста отклоняются', () => {
    expect(attackCreateSchema.safeParse({ ...draft, target_link: 'https://example.com/channel/1' }).success).toBe(false);
    expect(attackCreateSchema.safeParse({ ...draft, target_link: 'https://t.me/example' }).success).toBe(false);
    expect(attackCreateSchema.safeParse({ ...draft, target_link: 'https://t.me/example/0' }).success).toBe(false);
  });

  test('публичная и приватная ссылка на пост принимаются', () => {
    for (const link of [
      'https://t.me/example/412',
      't.me/example/412',
      'https://t.me/c/1234567890/42',
      'https://t.me/example/412?single',
    ]) {
      expect(attackCreateSchema.safeParse({ ...draft, target_link: link }).success).toBe(true);
    }
  });
});

describe('attackCreateSchema — тексты', () => {
  test('без картинок текст до 4096 символов', () => {
    expect(attackCreateSchema.safeParse({ ...draft, texts: ['x'.repeat(4096)] }).success).toBe(true);
    expect(attackCreateSchema.safeParse({ ...draft, texts: ['x'.repeat(4097)] }).success).toBe(false);
  });

  test('с картинками текст до 1024 символов', () => {
    expect(
      attackCreateSchema.safeParse({ ...draft, images: [IMAGE], texts: ['x'.repeat(1024)] }).success,
    ).toBe(true);

    const tooLong = attackCreateSchema.safeParse({
      ...draft,
      images: [IMAGE],
      texts: ['x'.repeat(1025)],
    });
    expect(tooLong.success).toBe(false);
    if (!tooLong.success) {
      expect(tooLong.error.issues[0]?.path).toEqual(['texts', 0]);
    }
  });

  test('пустой список текстов и текст из пробелов не проходят', () => {
    expect(attackCreateSchema.safeParse({ ...draft, texts: [] }).success).toBe(false);
    expect(attackCreateSchema.safeParse({ ...draft, texts: ['   '] }).success).toBe(false);
  });
});

describe('attackCreateSchema — лимит', () => {
  test('задаётся ровно один лимит', () => {
    expect(attackCreateSchema.safeParse(draft).success).toBe(true);
    expect(
      attackCreateSchema.safeParse({
        ...draft,
        limit_kind: 'minutes',
        message_limit: null,
        duration_minutes: 30,
      }).success,
    ).toBe(true);

    expect(
      attackCreateSchema.safeParse({ ...draft, message_limit: 40, duration_minutes: 30 }).success,
    ).toBe(false);
    expect(
      attackCreateSchema.safeParse({ ...draft, message_limit: null, duration_minutes: null }).success,
    ).toBe(false);
  });

  test('тип лимита совпадает с заполненным полем', () => {
    expect(
      attackCreateSchema.safeParse({
        ...draft,
        limit_kind: 'minutes',
        message_limit: 40,
        duration_minutes: null,
      }).success,
    ).toBe(false);
    expect(
      attackCreateSchema.safeParse({
        ...draft,
        limit_kind: 'messages',
        message_limit: null,
        duration_minutes: 30,
      }).success,
    ).toBe(false);
  });

  test('лимит больше нуля и целый', () => {
    expect(attackCreateSchema.safeParse({ ...draft, message_limit: 0 }).success).toBe(false);
    expect(attackCreateSchema.safeParse({ ...draft, message_limit: 1.5 }).success).toBe(false);
  });
});

describe('attackCreateSchema — картинки, название и мимики', () => {
  test('картинка описывается путём и именем', () => {
    expect(attackCreateSchema.safeParse({ ...draft, images: [IMAGE] }).success).toBe(true);
    expect(
      attackCreateSchema.safeParse({ ...draft, images: [{ path: '', name: 'cat.jpg' }] }).success,
    ).toBe(false);
    expect(
      attackCreateSchema.safeParse({ ...draft, images: [{ path: 'attacks/owner/uuid/cat.jpg' }] }).success,
    ).toBe(false);
  });

  test('черновик можно сохранить без назначенных мимиков', () => {
    const result = attackCreateSchema.safeParse({ ...draft, agent_ids: [] });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.agent_ids).toEqual([]);
    }

    expect(attackCreateSchema.safeParse({ ...draft, agent_ids: [AGENT_ID] }).success).toBe(true);
    expect(attackCreateSchema.safeParse({ ...draft, agent_ids: ['not-a-uuid'] }).success).toBe(false);
  });

  test('название обрезается, а пустое не уходит в запрос', () => {
    const named = attackCreateSchema.safeParse({ ...draft, title: '  Розыгрыш  ' });
    expect(named.success).toBe(true);
    if (named.success) {
      expect(named.data.title).toBe('Розыгрыш');
    }

    const unnamed = attackCreateSchema.safeParse({ ...draft, title: '' });
    expect(unnamed.success).toBe(true);
    if (unnamed.success) {
      expect(unnamed.data.title).toBeUndefined();
    }
  });
});

describe('attackEditSchema', () => {
  const edit: AttackEditFormState = {
    version: 3,
    title: '',
    texts: ['Участвую!'],
    images: [],
    limit_kind: 'messages',
    message_limit: 40,
    duration_minutes: null,
  };

  test('правка требует версию атаки', () => {
    expect(attackEditSchema.safeParse(edit).success).toBe(true);

    const withoutVersion: Record<string, unknown> = { ...edit };
    delete withoutVersion.version;
    expect(attackEditSchema.safeParse(withoutVersion).success).toBe(false);
  });

  test('ссылку через правку прислать нельзя', () => {
    const result = attackEditSchema.safeParse({
      ...edit,
      target_link: 'https://t.me/example/999',
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect('target_link' in result.data).toBe(false);
      expect(result.data.version).toBe(3);
    }
  });

  test('правила пар картинок и текстов те же, что при создании', () => {
    expect(
      attackEditSchema.safeParse({
        ...edit,
        images: [IMAGE],
        texts: ['x'.repeat(1025)],
      }).success,
    ).toBe(false);
  });
});
