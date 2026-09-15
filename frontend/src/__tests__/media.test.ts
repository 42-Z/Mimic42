import { describe, expect, test } from 'bun:test';
import { findMediaRefs, isDataUrl, isMediaId } from '@/lib/activity/media';

describe('isMediaId', () => {
  test('accepts photo/document references', () => {
    expect(isMediaId('photo:123:456:abcd:4')).toBe(true);
    expect(isMediaId('doc:1:2:ff:5')).toBe(true);
    expect(isMediaId('sticker:1:2:ff:5:👍')).toBe(true);
    expect(isMediaId('  voice:1:2:ff:5  ')).toBe(true);
  });

  test('rejects non-references', () => {
    expect(isMediaId('hello')).toBe(false);
    expect(isMediaId('photo:123')).toBe(false);
    expect(isMediaId('image:1:2:ff:5')).toBe(false);
    expect(isMediaId('data:image/png;base64,AAA')).toBe(false);
    expect(isMediaId(null)).toBe(false);
    expect(isMediaId(42)).toBe(false);
  });
});

describe('isDataUrl', () => {
  test('accepts inline media URLs', () => {
    expect(isDataUrl('data:image/jpeg;base64,/9j/')).toBe(true);
    expect(isDataUrl('data:audio/ogg;base64,AAA')).toBe(true);
  });

  test('rejects other strings', () => {
    expect(isDataUrl('data:text/plain;base64,AAA')).toBe(false);
    expect(isDataUrl('https://example.com/a.png')).toBe(false);
    expect(isDataUrl(null)).toBe(false);
  });
});

describe('findMediaRefs', () => {
  test('collects refs from nested args/result', () => {
    const refs = findMediaRefs({
      peer: '123',
      file: 'photo:9:8:aa:4',
      nested: [{ url: 'data:image/png;base64,AAA' }, 'plain text'],
    });
    expect(refs).toEqual(['photo:9:8:aa:4', 'data:image/png;base64,AAA']);
  });

  test('dedupes and ignores non-media', () => {
    const refs = findMediaRefs({
      a: 'doc:1:2:ff:5',
      b: 'doc:1:2:ff:5',
      c: 'just text',
      d: 42,
      e: null,
    });
    expect(refs).toEqual(['doc:1:2:ff:5']);
  });

  test('returns empty for media-free payloads', () => {
    expect(findMediaRefs(null)).toEqual([]);
    expect(findMediaRefs({ success: true })).toEqual([]);
    expect(findMediaRefs('no media here')).toEqual([]);
  });
});
