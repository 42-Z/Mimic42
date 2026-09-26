import { describe, test, expect } from 'bun:test';

import { needsRebind } from '@/lib/telegram';

describe('needsRebind', () => {
  test('returns true for revoked and error sessions', () => {
    expect(needsRebind('revoked')).toBe(true);
    expect(needsRebind('error')).toBe(true);
  });

  test('returns false for healthy, pending and missing sessions', () => {
    expect(needsRebind('authorized')).toBe(false);
    expect(needsRebind('code_requested')).toBe(false);
    expect(needsRebind('password_required')).toBe(false);
    expect(needsRebind('not_started')).toBe(false);
    expect(needsRebind(null)).toBe(false);
    expect(needsRebind(undefined)).toBe(false);
  });
});
