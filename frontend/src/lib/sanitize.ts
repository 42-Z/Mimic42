/**
 * XSS sanitization utilities.
 *
 * ALL user-generated content from Telegram must pass through these
 * before being rendered. This is non-negotiable.
 *
 * Dangerous fields:
 * - agent_messages.content  (text from Telegram — arbitrary input)
 * - agents.soul_prompt       (user-defined, could be malicious)
 * - agents.name              (user-defined)
 * - message_threads.peer_name (from Telegram)
 */
import type { DOMPurify } from 'dompurify';

/**
 * Strips ALL HTML — returns plain text only.
 * Use for content that should never contain HTML.
 */
export function sanitizeText(input: string | null | undefined): string {
  if (!input) return '';

  // Server-side: DOMPurify needs a DOM — use simple stripping
  if (typeof window === 'undefined') {
    return stripHtmlServer(input);
  }

  // Client-side: use DOMPurify
  return sanitizeClientSide(input, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] });
}

/**
 * Allows a small safe set of HTML tags for rich content display.
 * Use for system prompts / soul prompts shown in preview.
 * Still strips any dangerous attributes or scripts.
 */
/**
 * Allows a small safe set of HTML tags for rich content display.
 */
export function sanitizeRichText(input: string | null | undefined): string {
  if (!input) return '';

  // Если мы на сервере (или в тестах)
  if (typeof window === 'undefined') {
    return sanitizeRichHtmlServer(input); // Используем новую функцию вместо stripHtmlServer
  }

  // На клиенте используем DOMPurify
  return sanitizeClientSide(input, {
    ALLOWED_TAGS: ['b', 'i', 'em', 'strong', 'p', 'br', 'code', 'pre'],
    ALLOWED_ATTR: [],
    FORBID_SCRIPT: true,
    FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'input'],
  });
}

/**
 * Server-side / pre-DOMPurify cleanup for rich text.
 * Removes dangerous tags, keeps only bare allowed tags — every attribute
 * is stripped, so handlers like onmouseover cannot survive the fallback.
 */
function sanitizeRichHtmlServer(input: string): string {
  const ALLOWED_BARE = /<(?!\/?(?:b|i|em|strong|p|br|code|pre)\s*\/?>)[^>]*>/g;
  return input
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, '')
    // Rewrite allowed tags to their bare, attribute-less form
    .replace(/<(\/?)(b|i|em|strong|p|br|code|pre)\b[^>]*>/gi, '<$1$2>')
    // Drop every tag that is not a bare allowed tag
    .replace(ALLOWED_BARE, '')
    .trim();
}

// ── Internal helpers ──────────────────────────────────────────────────────────

type PurifyConfig = {
  ALLOWED_TAGS?: string[];
  ALLOWED_ATTR?: string[];
  FORBID_SCRIPT?: boolean;
  FORBID_TAGS?: string[];
};

let DOMPurifyInstance: DOMPurify | null = null;

async function loadDOMPurify() {
  if (!DOMPurifyInstance) {
    const module = await import('dompurify');
    DOMPurifyInstance = module.default;
  }
  return DOMPurifyInstance;
}

function sanitizeClientSide(input: string, config: PurifyConfig): string {
  // Synchronous path — DOMPurify must be pre-loaded or we use fallback.
  // The fallback mirrors the server-side semantics so behaviour is
  // identical until DOMPurify finishes loading.
  if (!DOMPurifyInstance) {
    return config.ALLOWED_TAGS?.length
      ? sanitizeRichHtmlServer(input)
      : stripHtmlServer(input);
  }

  try {
    return DOMPurifyInstance.sanitize(input, config) as string;
  } catch {
    return config.ALLOWED_TAGS?.length
      ? sanitizeRichHtmlServer(input)
      : stripHtmlServer(input);
  }
}

/**
 * Preloads DOMPurify. Call once on app startup (in root layout).
 */
export async function preloadSanitizer(): Promise<void> {
  if (typeof window !== 'undefined') {
    await loadDOMPurify();
  }
}

/**
 * Server-side fallback: strip HTML tags with regex.
 * Less safe than DOMPurify but acceptable for SSR where
 * the output is escaped by React anyway.
 */
function stripHtmlServer(input: string): string {
  return input
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, '')
    .replace(/<[^>]+>/g, '')
    .trim();
}

/**
 * Masks a phone number: shows first 4 and last 2 digits.
 * e.g., "+79991234567" → "+799*****67"
 */
export function maskPhoneNumber(phone: string | null | undefined): string {
  if (!phone) return '—';
  if (phone.length <= 6) return phone;

  const prefix = phone.slice(0, 4);
  const suffix = phone.slice(-2);
  const middle = '*'.repeat(Math.max(0, phone.length - 6));
  return `${prefix}${middle}${suffix}`;
}

/**
 * Truncates content for preview, with ellipsis.
 */
export function truncate(text: string, maxLength: number): string {
  const clean = sanitizeText(text);
  if (clean.length <= maxLength) return clean;
  return clean.slice(0, maxLength - 3) + '...';
}
