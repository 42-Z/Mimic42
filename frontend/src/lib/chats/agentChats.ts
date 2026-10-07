/**
 * Настройка отключённых чатов в `agents.settings` — зеркало
 * `src/mimic42/core/chat_access.py`.
 */
import type { AgentChat, AgentChatKind } from '@/types';

export const CHAT_GROUPS: { id: AgentChatKind; title: string }[] = [
  { id: 'channel', title: 'Каналы' },
  { id: 'group', title: 'Группы' },
  { id: 'private', title: 'Личные' },
];

/**
 * Прочитать ID отключённых чатов из settings.
 *
 * Ключа нет или значение нечитаемо — пустой список (доступны все чаты). Остаются
 * только целые числа: `true` и строки из ручной правки JSON отбрасываются, как на бэкенде.
 */
export function readDisabledChats(
  settings: Record<string, unknown> | null | undefined,
): number[] {
  const value = settings?.disabled_chats;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is number => typeof item === 'number' && Number.isInteger(item));
}

/**
 * Вернуть настройки с обновлённым `disabled_chats`.
 *
 * Пустой список и `undefined` удаляют ключ: «ничего не отключено» — отсутствие
 * настройки, как у существующих агентов. Исходный объект не мутируется.
 */
export function mergeDisabledChats(
  existing: Record<string, unknown>,
  disabled: number[] | undefined,
): Record<string, unknown> {
  const merged = { ...existing };
  if (disabled && disabled.length > 0) {
    merged.disabled_chats = Array.from(new Set(disabled));
  } else {
    delete merged.disabled_chats;
  }
  return merged;
}

export interface ChatRow {
  chat: AgentChat;
  /** Доступен ли чат агенту: включён сам или включён его канал (комментарии). */
  enabled: boolean;
  /** Канал, из-за которого группа обсуждения доступна и переключатель заблокирован. */
  lockedBy: { id: number; title: string } | null;
}

/** Строки списка с учётом правила комментариев: группа обсуждения идёт за своим каналом. */
export function buildChatRows(chats: AgentChat[], disabled: ReadonlySet<number>): ChatRow[] {
  const byId = new Map(chats.map((chat) => [chat.id, chat]));
  return chats.map((chat) => {
    const channelId = chat.discussion_of;
    const channelEnabled = channelId !== null && !disabled.has(channelId);
    const lockedBy =
      channelId !== null && channelEnabled
        ? { id: channelId, title: byId.get(channelId)?.title ?? `Канал ${channelId}` }
        : null;
    return { chat, enabled: !disabled.has(chat.id) || lockedBy !== null, lockedBy };
  });
}

/** Включить (`enable`) или отключить чаты; остальные ID — в том числе неизвестные — сохраняются. */
export function toggleChats(disabled: number[], ids: number[], enable: boolean): number[] {
  const next = new Set(disabled);
  for (const id of ids) {
    if (enable) next.delete(id);
    else next.add(id);
  }
  return Array.from(next);
}
