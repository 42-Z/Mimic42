import { describe, it, expect } from 'bun:test';
import { sanitizeText, sanitizeRichText, maskPhoneNumber, truncate } from '@/lib/sanitize';

describe('sanitizeText', () => {
  it('returns empty string for null/undefined', () => {
    expect(sanitizeText(null)).toBe('');
    expect(sanitizeText(undefined)).toBe('');
    expect(sanitizeText('')).toBe('');
  });

  it('strips script tags', () => {
    const input = '<script>alert("xss")</script>hello';
    const result = sanitizeText(input);
    expect(result).not.toContain('<script>');
    expect(result).not.toContain('alert');
    expect(result).toContain('hello');
  });

  it('strips all HTML tags', () => {
    expect(sanitizeText('<b>bold</b>')).not.toContain('<b>');
    expect(sanitizeText('<img src=x onerror=alert(1)>')).not.toContain('<img');
    expect(sanitizeText('<a href="javascript:alert(1)">link</a>')).not.toContain('<a');
  });

  it('strips event handlers', () => {
    const input = '<div onmouseover="alert(1)">text</div>';
    expect(sanitizeText(input)).not.toContain('onmouseover');
    expect(sanitizeText(input)).not.toContain('alert');
  });

  it('strips iframe', () => {
    const input = '<iframe src="https://evil.com"></iframe>';
    expect(sanitizeText(input)).not.toContain('iframe');
  });

  it('handles javascript: scheme', () => {
    const input = '<a href="javascript:void(0)">click</a>';
    expect(sanitizeText(input)).not.toContain('javascript:');
  });

  it('preserves plain text content', () => {
    const plain = 'Hello, это обычный текст. 123!';
    expect(sanitizeText(plain)).toBe(plain);
  });

  it('handles nested script injection', () => {
    const input = '<scr<script>ipt>alert("xss")</scr</script>ipt>';
    expect(sanitizeText(input)).not.toContain('alert');
  });

  it('handles SVG-based XSS', () => {
    const input = '<svg onload=alert(1)><circle cx=10 cy=10 r=5/></svg>';
    expect(sanitizeText(input)).not.toContain('onload');
    expect(sanitizeText(input)).not.toContain('<svg');
  });

  it('handles data URI XSS', () => {
    const input = '<img src="data:text/html,<script>alert(1)</script>">';
    expect(sanitizeText(input)).not.toContain('data:text/html');
  });
});

describe('sanitizeRichText', () => {
  it('allows safe tags', () => {
    const input = '<b>bold</b> and <i>italic</i>';
    const result = sanitizeRichText(input);
    expect(result).toContain('<b>');
    expect(result).toContain('<i>');
  });

  it('strips attributes from allowed tags in the fallback path', () => {
    const input = '<b onmouseover="alert(1)">bold</b>';
    const result = sanitizeRichText(input);
    expect(result).not.toContain('onmouseover');
    expect(result).not.toContain('alert');
    expect(result).toContain('<b>bold</b>');
  });

  it('strips script in rich mode', () => {
    const input = '<b>text</b><script>alert(1)</script>';
    expect(sanitizeRichText(input)).not.toContain('<script>');
    expect(sanitizeRichText(input)).not.toContain('alert');
  });

  it('strips style in rich mode', () => {
    const input = '<style>body{display:none}</style>';
    expect(sanitizeRichText(input)).not.toContain('<style>');
  });
});

describe('maskPhoneNumber', () => {
  it('masks middle digits', () => {
    const result = maskPhoneNumber('+79991234567');
    expect(result).toMatch(/^\+799\*+67$/);
  });

  it('returns dash for null', () => {
    expect(maskPhoneNumber(null)).toBe('—');
    expect(maskPhoneNumber(undefined)).toBe('—');
  });

  it('returns original for short numbers', () => {
    expect(maskPhoneNumber('+1234')).toBe('+1234');
  });
});

describe('truncate', () => {
  it('truncates long text with ellipsis', () => {
    const long = 'a'.repeat(200);
    const result = truncate(long, 50);
    expect(result.length).toBeLessThanOrEqual(50);
    expect(result.endsWith('...')).toBe(true);
  });

  it('does not truncate short text', () => {
    const short = 'Hello world';
    expect(truncate(short, 50)).toBe(short);
  });

  it('strips HTML before truncating', () => {
    const input = '<script>evil</script>Normal text here';
    const result = truncate(input, 100);
    expect(result).not.toContain('<script>');
    expect(result).toContain('Normal text');
  });
});
