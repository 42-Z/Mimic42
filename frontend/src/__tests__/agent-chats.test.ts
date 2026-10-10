import { describe, expect, test } from 'bun:test';
import {
  buildChatRows,
  chatMatches,
  hiddenChannelIds,
  mergeDisabledChats,
  normalizeQuery,
  readDisabledChats,
  toggleChats,
} from '@/lib/chats/agentChats';
import { agentSettingsSchema } from '@/lib/validators';
import type { AgentChat } from '@/types';

const NEWS: AgentChat = {
  id: -1001000000001,
  title: 'Новости',
  username: 'news',
  kind: 'channel',
  discussion_of: null,
};
const COMMENTS: AgentChat = {
  id: -1001000000002,
  title: 'Комментарии',
  username: null,
  kind: 'group',
  discussion_of: NEWS.id,
};
const ANNA: AgentChat = { id: 42, title: 'Анна', username: null, kind: 'private', discussion_of: null };

describe('readDisabledChats', () => {
  test('без настроек и без ключа ничего не отключено', () => {
    expect(readDisabledChats(null)).toEqual([]);
    expect(readDisabledChats({})).toEqual([]);
    expect(readDisabledChats({ disabled_chats: null })).toEqual([]);
  });

  test('список ID возвращается как есть', () => {
    expect(readDisabledChats({ disabled_chats: [NEWS.id, 42] })).toEqual([NEWS.id, 42]);
  });

  test('мусор отбрасывается, как на бэкенде', () => {
    expect(readDisabledChats({ disabled_chats: [NEWS.id, true, '42', 1.5, null] })).toEqual([
      NEWS.id,
    ]);
    expect(readDisabledChats({ disabled_chats: { id: 1 } })).toEqual([]);
  });

  test('повторяющиеся ID схлопываются', () => {
    expect(readDisabledChats({ disabled_chats: [777, NEWS.id, 777] })).toEqual([777, NEWS.id]);
  });
});

describe('mergeDisabledChats', () => {
  test('список записывается без дублей, другие ключи сохраняются', () => {
    expect(mergeDisabledChats({ model: 'm' }, [1, 2, 1])).toEqual({
      model: 'm',
      disabled_chats: [1, 2],
    });
  });

  test('пустой список и undefined удаляют ключ', () => {
    const existing = { model: 'm', disabled_chats: [1], alien: 1 };
    expect(mergeDisabledChats(existing, [])).toEqual({ model: 'm', alien: 1 });
    expect(mergeDisabledChats(existing, undefined)).toEqual({ model: 'm', alien: 1 });
  });

  test('исходный объект не мутируется', () => {
    const existing = { disabled_chats: [1] };
    mergeDisabledChats(existing, [2]);
    mergeDisabledChats(existing, []);
    expect(existing).toEqual({ disabled_chats: [1] });
  });
});

describe('buildChatRows', () => {
  test('по умолчанию все чаты включены', () => {
    const rows = buildChatRows([NEWS, ANNA], new Set());
    expect(rows.map((row) => row.enabled)).toEqual([true, true]);
    expect(rows.every((row) => row.lockedBy === null)).toBe(true);
  });

  test('отключённый чат выключен', () => {
    const rows = buildChatRows([NEWS, ANNA], new Set([ANNA.id]));
    expect(rows.map((row) => row.enabled)).toEqual([true, false]);
  });

  test('группа обсуждения включённого канала включена и заблокирована им', () => {
    const rows = buildChatRows([NEWS, COMMENTS], new Set([COMMENTS.id]));
    const comments = rows[1];
    expect(comments?.enabled).toBe(true);
    expect(comments?.lockedBy).toEqual({ id: NEWS.id, title: 'Новости' });
  });

  test('при отключённом канале группа живёт своим состоянием', () => {
    const rows = buildChatRows([NEWS, COMMENTS], new Set([NEWS.id, COMMENTS.id]));
    expect(rows[1]?.enabled).toBe(false);
    expect(rows[1]?.lockedBy).toBeNull();
    const rowsEnabledOwn = buildChatRows([NEWS, COMMENTS], new Set([NEWS.id]));
    expect(rowsEnabledOwn[1]?.enabled).toBe(true);
    expect(rowsEnabledOwn[1]?.lockedBy).toBeNull();
  });

  test('канал вне списка диалогов группу не блокирует: она отключается вместе с ним', () => {
    const [row] = buildChatRows([COMMENTS], new Set());
    expect(row?.lockedBy).toBeNull();
    expect(row?.enabled).toBe(true);
    expect(row?.ids).toEqual([COMMENTS.id, NEWS.id]);
  });

  test('группа с неизвестным каналом выключена, только когда отключены оба ID', () => {
    const onlyGroup = buildChatRows([COMMENTS], new Set([COMMENTS.id]));
    expect(onlyGroup[0]?.enabled).toBe(true);
    const both = buildChatRows([COMMENTS], new Set([COMMENTS.id, NEWS.id]));
    expect(both[0]?.enabled).toBe(false);
  });

  test('переключатель обычного чата меняет только его ID', () => {
    const rows = buildChatRows([NEWS, COMMENTS, ANNA], new Set());
    expect(rows.map((row) => row.ids)).toEqual([[NEWS.id], [COMMENTS.id], [ANNA.id]]);
  });
});

describe('hiddenChannelIds', () => {
  test('каналы вне списка, за которыми стоят группы из списка', () => {
    expect(hiddenChannelIds([COMMENTS, ANNA])).toEqual(new Set([NEWS.id]));
  });

  test('канал из списка скрытым не считается', () => {
    expect(hiddenChannelIds([NEWS, COMMENTS])).toEqual(new Set());
  });
});

describe('поиск чатов', () => {
  const YOLKA: AgentChat = {
    id: 7,
    title: 'Ёлки-палки',
    username: 'Elki_Palki',
    kind: 'channel',
    discussion_of: null,
  };

  test('запрос очищается от пробелов, «@» и регистра', () => {
    expect(normalizeQuery('  @Daily_News ')).toBe('daily_news');
    expect(normalizeQuery('@')).toBe('');
  });

  test('находит по названию и по @username', () => {
    expect(chatMatches(NEWS, normalizeQuery('новости'))).toBe(true);
    expect(chatMatches(NEWS, normalizeQuery('@news'))).toBe(true);
    expect(chatMatches(NEWS, normalizeQuery('друзей'))).toBe(false);
  });

  test('«ё» и «е» не различаются, пустой запрос подходит всем', () => {
    expect(chatMatches(YOLKA, normalizeQuery('елки'))).toBe(true);
    expect(chatMatches(YOLKA, normalizeQuery('ЁЛКИ'))).toBe(true);
    expect(chatMatches(ANNA, '')).toBe(true);
  });

  test('чат без username ищется только по названию', () => {
    expect(chatMatches(ANNA, normalizeQuery('@anna'))).toBe(false);
    expect(chatMatches(ANNA, normalizeQuery('анн'))).toBe(true);
  });
});

describe('toggleChats', () => {
  test('отключение добавляет ID, включение убирает', () => {
    expect(toggleChats([], [NEWS.id], false)).toEqual([NEWS.id]);
    expect(toggleChats([NEWS.id, 42], [NEWS.id], true)).toEqual([42]);
  });

  test('неизвестные списку диалогов ID не теряются', () => {
    expect(toggleChats([999, 42], [NEWS.id], false)).toEqual([999, 42, NEWS.id]);
    expect(toggleChats([999, 42], [42], true)).toEqual([999]);
  });

  test('исходный массив не мутируется', () => {
    const base = [1];
    toggleChats(base, [2], false);
    expect(base).toEqual([1]);
  });
});

describe('agentSettingsSchema.disabled_chats', () => {
  const base = { name: 'Мимик', soul_prompt: '', model: 'openrouter/free' };

  test('принимает список целых, пустой список и отсутствие ключа', () => {
    expect(agentSettingsSchema.safeParse({ ...base, disabled_chats: [NEWS.id, 42] }).success).toBe(true);
    expect(agentSettingsSchema.safeParse({ ...base, disabled_chats: [] }).success).toBe(true);
    expect(agentSettingsSchema.safeParse(base).success).toBe(true);
  });

  test('отклоняет нецелые и нечисловые ID', () => {
    expect(agentSettingsSchema.safeParse({ ...base, disabled_chats: [1.5] }).success).toBe(false);
    expect(agentSettingsSchema.safeParse({ ...base, disabled_chats: ['1'] }).success).toBe(false);
  });
});
