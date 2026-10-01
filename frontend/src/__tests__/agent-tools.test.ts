import { describe, expect, test } from 'bun:test';
import { readEnabledTools } from '@/lib/tools/agentTools';
import { agentSettingsSchema } from '@/lib/validators';

describe('readEnabledTools', () => {
  test('без настроек и без ключа — режим «включены все»', () => {
    expect(readEnabledTools(null)).toBeNull();
    expect(readEnabledTools({})).toBeNull();
    expect(readEnabledTools({ enabled_tools: null })).toBeNull();
  });

  test('пустой список — пустой allowlist', () => {
    expect(readEnabledTools({ enabled_tools: [] })).toEqual([]);
  });

  test('список имён возвращается как есть', () => {
    expect(readEnabledTools({ enabled_tools: ['send_text_message', 'view_image'] })).toEqual([
      'send_text_message',
      'view_image',
    ]);
  });

  test('нестроковые элементы отбрасываются', () => {
    expect(readEnabledTools({ enabled_tools: ['send_text_message', 42, null] })).toEqual([
      'send_text_message',
    ]);
  });

  test('список без валидных строк — мусор, как и на бэкенде', () => {
    expect(readEnabledTools({ enabled_tools: [42, '  '] })).toBeNull();
  });
});

describe('agentSettingsSchema.enabled_tools', () => {
  const base = { name: 'Мимик', soul_prompt: '', model: 'openrouter/free' };

  test('принимает список, пустой список, null и отсутствие ключа', () => {
    expect(agentSettingsSchema.safeParse({ ...base, enabled_tools: ['send_text_message'] }).success).toBe(true);
    expect(agentSettingsSchema.safeParse({ ...base, enabled_tools: [] }).success).toBe(true);
    expect(agentSettingsSchema.safeParse({ ...base, enabled_tools: null }).success).toBe(true);
    expect(agentSettingsSchema.safeParse(base).success).toBe(true);
  });

  test('отклоняет нестроковые имена', () => {
    expect(agentSettingsSchema.safeParse({ ...base, enabled_tools: [42] }).success).toBe(false);
  });
});
