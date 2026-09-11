import { describe, expect, it } from 'bun:test';

import {
  GATEWAY_EFFORTS,
  pickReasoningValue,
  reasoningOptionValues,
} from '@/lib/reasoning';

describe('reasoningOptionValues', () => {
  it('returns null when the model omits the reasoning field', () => {
    expect(reasoningOptionValues(undefined)).toBeNull();
    expect(reasoningOptionValues(null)).toBeNull();
  });

  it('returns null when supported_efforts is omitted but the field exists', () => {
    expect(reasoningOptionValues({ mandatory: false, default_enabled: true })).toBeNull();
  });

  it('returns supported efforts and adds none when reasoning is not mandatory', () => {
    expect(
      reasoningOptionValues({ supported_efforts: ['max', 'high', 'low'], mandatory: false })
    ).toEqual(['max', 'high', 'low', 'none']);
  });

  it('returns supported efforts without none for mandatory models', () => {
    expect(
      reasoningOptionValues({ supported_efforts: ['max', 'high', 'low'], mandatory: true })
    ).toEqual(['max', 'high', 'low']);
  });

  it('returns the full gateway set when supported_efforts is null', () => {
    expect(reasoningOptionValues({ supported_efforts: null })).toEqual(GATEWAY_EFFORTS);
  });
});

describe('pickReasoningValue', () => {
  it('keeps the current value when it is available', () => {
    expect(pickReasoningValue('low', ['max', 'high', 'low', 'none'])).toBe('low');
  });

  it('falls back to the model default effort', () => {
    expect(
      pickReasoningValue('medium', ['max', 'high', 'low', 'none'], {
        supported_efforts: ['max', 'high', 'low'],
        default_effort: 'max',
      })
    ).toBe('max');
  });

  it('falls back to the first option without a default', () => {
    expect(pickReasoningValue('medium', ['max', 'high', 'low'])).toBe('max');
  });

  it('returns undefined when the control is hidden', () => {
    expect(pickReasoningValue('high', null)).toBeUndefined();
  });
});
