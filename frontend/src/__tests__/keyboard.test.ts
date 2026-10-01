import { describe, expect, test } from 'bun:test';
import { nextTabFocusIndex } from '@/lib/keyboard';

describe('nextTabFocusIndex', () => {
  test('стрелки двигают фокус по кругу', () => {
    expect(nextTabFocusIndex('ArrowRight', 0, 6)).toBe(1);
    expect(nextTabFocusIndex('ArrowRight', 5, 6)).toBe(0);
    expect(nextTabFocusIndex('ArrowLeft', 0, 6)).toBe(5);
    expect(nextTabFocusIndex('ArrowLeft', 3, 6)).toBe(2);
  });

  test('Home/End уводят фокус к краям', () => {
    expect(nextTabFocusIndex('Home', 4, 6)).toBe(0);
    expect(nextTabFocusIndex('End', 1, 6)).toBe(5);
  });

  test('прочие клавиши и невалидные индексы не двигают фокус', () => {
    expect(nextTabFocusIndex('Enter', 0, 6)).toBeNull();
    expect(nextTabFocusIndex(' ', 0, 6)).toBeNull();
    expect(nextTabFocusIndex('Tab', 0, 6)).toBeNull();
    expect(nextTabFocusIndex('ArrowRight', -1, 6)).toBeNull();
    expect(nextTabFocusIndex('ArrowRight', 6, 6)).toBeNull();
    expect(nextTabFocusIndex('ArrowRight', 0, 0)).toBeNull();
  });
});
