import { describe, expect, test } from 'bun:test';
import { mergeEnabledTools, readEnabledTools } from '@/lib/tools/agentTools';
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

  test('пробелы вокруг имён срезаются, как на бэкенде', () => {
    expect(readEnabledTools({ enabled_tools: ['  send_text_message  '] })).toEqual([
      'send_text_message',
    ]);
  });
});

describe('mergeEnabledTools', () => {
  test('список записывается в ключ как есть', () => {
    expect(mergeEnabledTools({ model: 'm' }, ['view_image', 'send_text_message'])).toEqual({
      model: 'm',
      enabled_tools: ['view_image', 'send_text_message'],
    });
  });

  test('пустой список — честный пустой allowlist, а не удаление ключа', () => {
    const merged = mergeEnabledTools({}, []);
    expect(merged.enabled_tools).toEqual([]);
    expect('enabled_tools' in merged).toBe(true);
  });

  test('null и undefined удаляют ключ, а прочие ключи остаются', () => {
    const existing = { model: 'm', enabled_tools: ['send_text_message'], alien: 1 };
    expect(mergeEnabledTools(existing, null)).toEqual({ model: 'm', alien: 1 });
    expect(mergeEnabledTools(existing, undefined)).toEqual({ model: 'm', alien: 1 });
  });

  test('другие ключи не теряются и не перезаписываются', () => {
    const existing = { model: 'm', first_comment: { enabled: false }, alien: { deep: true } };
    const merged = mergeEnabledTools(existing, ['send_text_message']);
    expect(merged.model).toBe('m');
    expect(merged.first_comment).toEqual({ enabled: false });
    expect(merged.alien).toEqual({ deep: true });
    expect(merged.enabled_tools).toEqual(['send_text_message']);
  });

  test('исходный объект не мутируется', () => {
    const existing = { model: 'm', enabled_tools: ['old'] };
    mergeEnabledTools(existing, ['new']);
    expect(existing).toEqual({ model: 'm', enabled_tools: ['old'] });
    mergeEnabledTools(existing, null);
    expect(existing).toEqual({ model: 'm', enabled_tools: ['old'] });
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
