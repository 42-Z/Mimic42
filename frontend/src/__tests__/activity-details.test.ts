import { describe, expect, test } from 'bun:test';
import { valueToString } from '@/components/activity/ActivityDetails';

describe('valueToString', () => {
  test('маркер base64 показывается подписью, а не сырым JSON', () => {
    const marker = { _omitted: 'base64 media, archived in Storage' };
    expect(valueToString(marker)).toBe('base64 media, archived in Storage');
  });

  test('прочие объекты остаются JSON', () => {
    expect(valueToString({ a: 1 })).toBe('{\n  "a": 1\n}');
    expect(valueToString('текст')).toBe('текст');
    expect(valueToString(null)).toBe('—');
  });
});
