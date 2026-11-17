import type { AttackImage, AttackLimitKind } from '@/types';

/** Пределы Telegram: подпись к картинке и обычное текстовое сообщение. */
export const ATTACK_CAPTION_MAX = 1024;
export const ATTACK_TEXT_MAX = 4096;
/** Предел названия — тот же, что MAX_TITLE_LENGTH в core/attack.py. */
export const ATTACK_TITLE_MAX = 200;

/**
 * Состояние формы создания до разбора схемой: пустые поля остаются числами
 * или null, а не undefined, чтобы формы на контролируемых инпутах не теряли
 * значение при очистке.
 */
export interface AttackFormState {
  title: string;
  target_link: string;
  texts: string[];
  images: AttackImage[];
  limit_kind: AttackLimitKind;
  message_limit: number | null;
  duration_minutes: number | null;
  agent_ids: string[];
}

/** Форма правки: ссылка и ростер мимиков не меняются здесь, добавлена версия атаки. */
export interface AttackEditFormState {
  version: number;
  title: string;
  texts: string[];
  images: AttackImage[];
  limit_kind: AttackLimitKind;
  message_limit: number | null;
  duration_minutes: number | null;
}
