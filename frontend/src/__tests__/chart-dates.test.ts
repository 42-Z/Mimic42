import { describe, expect, test } from 'bun:test';
import { formatDayLabel, formatDayFull } from '@/lib/format';

describe('formatDayLabel', () => {
  test('ISO-день превращается в короткую русскую подпись оси', () => {
    expect(formatDayLabel('2026-09-25')).toBe('25.09');
    expect(formatDayLabel('2026-01-05')).toBe('05.01');
    expect(formatDayLabel('2026-12-31')).toBe('31.12');
  });

  test('полная дата — в русскую подпись тултипа', () => {
    expect(formatDayFull('2026-09-25')).toBe('25 сентября 2026');
    expect(formatDayFull('2026-01-05')).toBe('5 января 2026');
    expect(formatDayFull('2026-12-31')).toBe('31 декабря 2026');
  });

  test('мусор вместо даты не роняет подпись', () => {
    expect(formatDayLabel('не дата')).toBe('не дата');
    expect(formatDayFull('')).toBe('');
    expect(formatDayFull(undefined)).toBe('');
  });
});
