import { describe, expect, it } from 'bun:test';

import { DEFAULT_MODEL, MODEL_OPTIONS, optionsIncluding } from '@/lib/models';

describe('optionsIncluding', () => {
  it('returns the plain menu when the current value is in it', () => {
    const current = MODEL_OPTIONS[2]?.value ?? '';
    expect(optionsIncluding(current)).toEqual(MODEL_OPTIONS);
  });

  it('prepends the stored legacy slug so the select shows the real value', () => {
    const legacy = 'google/gemini-3.1-flash-lite';
    const options = optionsIncluding(legacy);
    expect(options[0]).toEqual({ value: legacy, label: legacy });
    expect(options).toHaveLength(MODEL_OPTIONS.length + 1);
  });
});

describe('MODEL_OPTIONS', () => {
  it('contains exactly the five menu models with a non-empty default', () => {
    expect(MODEL_OPTIONS).toHaveLength(5);
    expect(MODEL_OPTIONS.some((o) => o.value === DEFAULT_MODEL)).toBe(true);
  });
});
