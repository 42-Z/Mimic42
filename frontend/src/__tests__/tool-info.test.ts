import { describe, expect, test } from 'bun:test';
import { TOOL_CATALOG } from '@/lib/activity/toolCatalog';
import { TOOL_GROUP_ORDER, TOOL_INFO } from '@/lib/tools/toolInfo';

describe('toolInfo', () => {
  test('перечисляет все 91 инструмент каталога действий без повторов', () => {
    const names = TOOL_INFO.map((tool) => tool.name);
    expect(names.length).toBe(91);
    expect(new Set(names).size).toBe(91);
    expect(new Set(names)).toEqual(new Set(Object.keys(TOOL_CATALOG)));
  });

  test('у каждого инструмента есть название и описание', () => {
    for (const tool of TOOL_INFO) {
      expect(tool.title.trim().length).toBeGreaterThan(0);
      expect(tool.description.trim().length).toBeGreaterThan(0);
    }
  });

  test('названия уникальны: по ним интерфейс подписывает переключатели', () => {
    const titles = TOOL_INFO.map((tool) => tool.title);
    expect(new Set(titles).size).toBe(titles.length);
  });

  test('порядок групп фиксирован и покрывает все группы каталога', () => {
    expect(TOOL_GROUP_ORDER.map((group) => group.id)).toEqual([
      'messages',
      'dialogs',
      'channels',
      'media',
      'stickers',
      'profile',
      'chatinfo',
      'members',
      'chatsettings',
      'chatlifecycle',
      'utils',
      'folders',
      'bots',
      'privacy',
    ]);
    const known = new Set(TOOL_GROUP_ORDER.map((group) => group.id));
    for (const tool of TOOL_INFO) expect(known.has(tool.group)).toBe(true);
  });

  test('группа каждого инструмента совпадает с каталогом действий', () => {
    for (const tool of TOOL_INFO) {
      const meta = TOOL_CATALOG[tool.name];
      if (!meta) throw new Error(`нет каталога для ${tool.name}`);
      expect(tool.group).toBe(meta.group);
    }
  });
});
