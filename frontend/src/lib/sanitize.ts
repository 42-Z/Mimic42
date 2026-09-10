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
 *
 * Deterministic pipeline (no DOMPurify): identical behaviour on
 * server, in bun tests (happy-dom) and in the browser. Dangerous elements are
 * removed WITH their content; unclosed opens consume to end of input.
 */
export function sanitizeText(input: string | null | undefined): string {
  if (!input) return '';
  return stripDangerousContent(input).replace(/<[^>]*>/g, '').trim();
}

// Elements whose content must never survive (even as text).
const DANGEROUS_ELEMENTS = ['script', 'style', 'iframe', 'object', 'embed', 'svg', 'form', 'link', 'meta', 'base'] as const;

// Hard bound: Telegram messages are ≤ 4096 chars, soul prompts ≤ 50000.
const MAX_SANITIZE_LEN = 200_000;

/** Finds the next `<tag …>` open (not a close) for a dangerous tag. */
function findOpenTag(
  lower: string,
  from: number,
): { start: number; end: number; tag: string } | null {
  let idx = lower.indexOf('<', from);
  while (idx !== -1) {
    const m = /^<([a-z][a-z0-9]*)[\s>]/.exec(lower.slice(idx, idx + 16));
    if (m?.[1] && (DANGEROUS_ELEMENTS as readonly string[]).includes(m[1])) {
      const gt = lower.indexOf('>', idx);
      return gt === -1
        ? { start: idx, end: lower.length, tag: m[1] }
        : { start: idx, end: gt + 1, tag: m[1] };
    }
    idx = lower.indexOf('<', idx + 1);
  }
  return null;
}

function stripDangerousContent(input: string): string {
  const src = input.length > MAX_SANITIZE_LEN ? input.slice(0, MAX_SANITIZE_LEN) : input;
  const lower = src.toLowerCase();
  let out = '';
  let i = 0;
  // Linear scan: a removed inner block may reconstitute an outer open
  // (e.g. <scr<script>..</script>), but every open is consumed at most
  // once going forward, so this always terminates.
  while (i < src.length) {
    const open = findOpenTag(lower, i);
    if (open === null) {
      out += src.slice(i);
      break;
    }
    out += src.slice(i, open.start);
    const closeIdx = lower.indexOf(`</${open.tag}`, open.end);
    if (closeIdx === -1) break; // Unclosed open consumes to end of input.
    const closeEnd = lower.indexOf('>', closeIdx);
    i = closeEnd === -1 ? src.length : closeEnd + 1;
  }
  return out;
}

/**
 * Allows a small safe set of HTML tags for rich content display.
 * Use for system prompts / soul prompts shown in preview.
 * Still strips any dangerous attributes or scripts.
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
 * Removes dangerous blocks (with content) via the linear scanner, keeps
 * only bare allowed tags — every attribute is stripped, so handlers like
 * onmouseover cannot survive the fallback.
 */
// Linear-time patterns: sequential quantifiers only, no nesting — no ReDoS.
function sanitizeRichHtmlServer(input: string): string {
  const ALLOWED_BARE = /<(?!\/?(?:b|i|em|strong|p|br|code|pre)\s*\/?>)[^>]*>/g;
  return stripDangerousContent(input)
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
    const dompurifyModule = await import('dompurify');
    DOMPurifyInstance = dompurifyModule.default;
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
 * Server-side fallback: strip HTML tags (plain text only).
 * Reuses the linear dangerous-content scanner, so behaviour matches
 * sanitizeText and no nested-quantifier regexes are needed.
 */
function stripHtmlServer(input: string): string {
  return stripDangerousContent(input)
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
