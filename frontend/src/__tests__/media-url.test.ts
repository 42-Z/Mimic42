import { describe, expect, test } from 'bun:test';
import { encodeMediaPath } from '@/hooks/useMediaUrl';

describe('encodeMediaPath', () => {
  test('обычный путь не меняется', () => {
    expect(encodeMediaPath('agent/uuid/photo.jpeg')).toBe('agent/uuid/photo.jpeg');
  });

  test('опасные символы квотируются по сегментам', () => {
    expect(encodeMediaPath('agent/uuid/photo #1?.jpeg')).toBe('agent/uuid/photo%20%231%3F.jpeg');
    expect(encodeMediaPath('agent/uuid/фото.jpeg')).toBe('agent/uuid/%D1%84%D0%BE%D1%82%D0%BE.jpeg');
  });
});
