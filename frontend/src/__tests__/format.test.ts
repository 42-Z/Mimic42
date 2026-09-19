import { describe, it, expect } from 'bun:test';
import { formatCompactNumber } from '@/lib/format';

describe('formatCompactNumber', () => {
  it('маленькие числа не сокращает', () => {
    expect(formatCompactNumber(0)).toBe('0');
    expect(formatCompactNumber(999)).toBe('999');
  });

  it('тысячи — с одной десятой до 100 тыс', () => {
    expect(formatCompactNumber(1_234)).toBe('1,2 тыс');
    expect(formatCompactNumber(12_345)).toBe('12,3 тыс');
    expect(formatCompactNumber(123_456)).toBe('123 тыс');
  });

  it('миллионы — с одной десятой', () => {
    expect(formatCompactNumber(1_234_567)).toBe('1,2 млн');
    expect(formatCompactNumber(12_345_678)).toBe('12,3 млн');
  });

  it('некорректные и отрицательные значения — ноль', () => {
    expect(formatCompactNumber(-5)).toBe('0');
    expect(formatCompactNumber(Number.NaN)).toBe('0');
  });
});
