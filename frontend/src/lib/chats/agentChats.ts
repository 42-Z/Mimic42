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
 * только целые числа без повторов: `true` и строки из ручной правки JSON
 * отбрасываются, как на бэкенде.
 */
export function readDisabledChats(
  settings: Record<string, unknown> | null | undefined,
): number[] {
  const value = settings?.disabled_chats;
  if (!Array.isArray(value)) return [];
  const ids = value.filter(
    (item): item is number => typeof item === 'number' && Number.isInteger(item),
  );
  return Array.from(new Set(ids));
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
  /**
   * ID, которые меняет переключатель строки. У группы обсуждения канала, которого
   * нет среди диалогов (в группу вступили напрямую), это и её ID, и ID канала:
   * переключателя канала нет, а правило доступа отпустило бы группу вместе с ним.
   */
  ids: number[];
}

/** Строки списка с учётом правила комментариев: группа обсуждения идёт за своим каналом. */
export function buildChatRows(chats: AgentChat[], disabled: ReadonlySet<number>): ChatRow[] {
  const byId = new Map(chats.map((chat) => [chat.id, chat]));
  return chats.map((chat) => {
    const channelId = chat.discussion_of;
    if (channelId === null) {
      return { chat, enabled: !disabled.has(chat.id), lockedBy: null, ids: [chat.id] };
    }
    const channel = byId.get(channelId);
    if (channel === undefined) {
      return {
        chat,
        enabled: !disabled.has(chat.id) || !disabled.has(channelId),
        lockedBy: null,
        ids: [chat.id, channelId],
      };
    }
    const channelEnabled = !disabled.has(channelId);
    return {
      chat,
      enabled: !disabled.has(chat.id) || channelEnabled,
      lockedBy: channelEnabled ? { id: channelId, title: channel.title } : null,
      ids: [chat.id],
    };
  });
}

/**
 * ID каналов вне списка диалогов, за которыми стоят группы обсуждения из списка.
 * Ими управляет переключатель группы, отдельной строкой они не показываются.
 */
export function hiddenChannelIds(chats: AgentChat[]): Set<number> {
  const known = new Set(chats.map((chat) => chat.id));
  const hidden = new Set<number>();
  for (const chat of chats) {
    if (chat.discussion_of !== null && !known.has(chat.discussion_of)) {
      hidden.add(chat.discussion_of);
    }
  }
  return hidden;
}

const fold = (text: string) => text.toLowerCase().replace(/ё/g, 'е');

/** Поисковая строка без пробелов по краям, ведущего «@», регистра и «ё». */
export function normalizeQuery(query: string): string {
  return fold(query.trim().replace(/^@+/, ''));
}

/** Подходит ли чат под запрос из `normalizeQuery`: по названию или @username. */
export function chatMatches(chat: AgentChat, needle: string): boolean {
  if (needle.length === 0) return true;
  return fold(chat.title).includes(needle) || fold(chat.username ?? '').includes(needle);
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
