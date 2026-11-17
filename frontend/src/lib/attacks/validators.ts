import { z, type RefinementCtx, type ZodTypeDef } from 'zod';

import type { AttackDraft, AttackPatch } from '@/types';
import {
  ATTACK_CAPTION_MAX,
  ATTACK_TEXT_MAX,
  ATTACK_TITLE_MAX,
  type AttackEditFormState,
  type AttackFormState,
} from './types';

/** ID атаки приходит из URL: только UUID, чтобы не собрать чужой путь запроса. */
export const attackIdSchema = z.string().uuid('Некорректный ID атаки');

const TELEGRAM_HOSTS = new Set(['t.me', 'www.t.me', 'telegram.me', 'www.telegram.me']);

/**
 * Ссылка на пост канала в том же виде, который принимает parse_target_link:
 * t.me/<username>/<post>, t.me/c/<internal>/<post>, схема необязательна.
 */
export function isAttackTargetLink(value: string): boolean {
  const raw = value.trim();
  if (raw.length === 0) return false;
  const withScheme = raw.includes('://') ? raw : `https://${raw}`;
  let url: URL;
  try {
    url = new URL(withScheme);
  } catch {
    return false;
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return false;
  if (!TELEGRAM_HOSTS.has(url.hostname.toLowerCase())) return false;

  const path = url.pathname.replace(/\/+$/, '');
  const publicPost = /^\/([A-Za-z0-9_]+)\/(\d+)$/.exec(path);
  if (publicPost) return Number(publicPost[2]) > 0;
  const privatePost = /^\/c\/(\d+)\/(\d+)$/.exec(path);
  return privatePost !== null && Number(privatePost[2]) > 0;
}

const targetLinkSchema = z
  .string()
  .trim()
  .min(1, 'Ссылка на пост обязательна')
  .refine(isAttackTargetLink, 'Нужна ссылка на пост в t.me, например https://t.me/канал/123');

const titleSchema = z
  .string()
  .trim()
  .max(ATTACK_TITLE_MAX, `Название не длиннее ${ATTACK_TITLE_MAX} символов`)
  .transform((value) => (value.length > 0 ? value : undefined));

const textSchema = z
  .string()
  .min(1, 'Текст не может быть пустым')
  .refine((text) => text.trim().length > 0, 'Текст не может быть пустым');

const imageSchema = z.object({
  path: z.string().min(1, 'Путь к картинке не задан'),
  name: z.string().min(1, 'Имя картинки не задано'),
});

const limitSchema = z
  .number()
  .int('Лимит должен быть целым числом')
  .positive('Лимит должен быть больше нуля')
  .nullable()
  .transform((value) => value ?? undefined);

const contentShape = {
  title: titleSchema,
  texts: z.array(textSchema).min(1, 'Добавьте хотя бы один текст'),
  images: z.array(imageSchema),
  limit_kind: z.enum(['messages', 'minutes'], {
    errorMap: () => ({ message: 'Выберите тип лимита' }),
  }),
  message_limit: limitSchema,
  duration_minutes: limitSchema,
};

interface AttackContent {
  texts: string[];
  images: { path: string; name: string }[];
  limit_kind: 'messages' | 'minutes';
  message_limit?: number;
  duration_minutes?: number;
}

function refineAttackContent(value: AttackContent, ctx: RefinementCtx): void {
  const hasMessageLimit = value.message_limit !== undefined;
  const hasDuration = value.duration_minutes !== undefined;

  if (hasMessageLimit === hasDuration) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['message_limit'],
      message: 'Задайте ровно один лимит: сообщения или минуты',
    });
  } else if (value.limit_kind === 'messages' && !hasMessageLimit) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['message_limit'],
      message: 'Укажите лимит сообщений',
    });
  } else if (value.limit_kind === 'minutes' && !hasDuration) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['duration_minutes'],
      message: 'Укажите длительность в минутах',
    });
  }

  const maxLength = value.images.length > 0 ? ATTACK_CAPTION_MAX : ATTACK_TEXT_MAX;
  const message =
    value.images.length > 0
      ? `С картинками текст не длиннее ${ATTACK_CAPTION_MAX} символов`
      : `Текст не длиннее ${ATTACK_TEXT_MAX} символов`;
  value.texts.forEach((text, index) => {
    // Лимит Телеграма и бэкенда считается в символах, а не в UTF-16 единицах:
    // эмодзи из суррогатной пары — один символ.
    if (Array.from(text).length > maxLength) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['texts', index], message });
    }
  });
}

export const attackCreateSchema: z.ZodType<AttackDraft, ZodTypeDef, AttackFormState> = z
  .object({
    ...contentShape,
    target_link: targetLinkSchema,
    agent_ids: z.array(z.string().uuid('Некорректный ID мимика')),
  })
  .superRefine(refineAttackContent);

export const attackEditSchema: z.ZodType<AttackPatch, ZodTypeDef, AttackEditFormState> = z
  .object({
    ...contentShape,
    version: z.number().int('Версия атаки должна быть целой').positive('Версия атаки не задана'),
  })
  .superRefine(refineAttackContent);
