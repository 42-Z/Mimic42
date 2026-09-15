/**
 * Media reference detection for the activity log.
 *
 * Tool args/results carry Telegram media as `media_id` strings
 * (`photo:<id>:<hash>:<ref>:<dc>`, stickers append `:emoji`) or inline
 * `data:` URLs. The log never stores raw bytes (truncated at write time),
 * so viewable media is fetched on demand via GET /agents/:id/media.
 */

/** Matches a Telegram media_id string (photo/sticker/doc/voice/round). */
export const MEDIA_ID_RE = /^(photo|sticker|doc|voice|round):\d+:\d+:[0-9a-fA-F]*:\d+(?::.+)?$/;

/** Matches inline data: URLs (images/audio/video). */
export const DATA_URL_RE = /^data:(image|audio|video)\/[a-zA-Z0-9.+-]+;base64,/;

export function isMediaId(value: unknown): value is string {
  return typeof value === 'string' && MEDIA_ID_RE.test(value.trim());
}

export function isDataUrl(value: unknown): value is string {
  return typeof value === 'string' && DATA_URL_RE.test(value.trim());
}

/**
 * Collect unique viewable media references from an arbitrary JSON value
 * (tool args / result). Preserves first-seen order, caps the count so a
 * pathological payload can't flood the UI.
 */
export function findMediaRefs(value: unknown, maxRefs = 8): string[] {
  const found: string[] = [];
  const seen = new Set<string>();
  const visit = (node: unknown): void => {
    if (found.length >= maxRefs) return;
    if (typeof node === 'string') {
      const trimmed = node.trim();
      if ((MEDIA_ID_RE.test(trimmed) || DATA_URL_RE.test(trimmed)) && !seen.has(trimmed)) {
        seen.add(trimmed);
        found.push(trimmed);
      }
      return;
    }
    if (Array.isArray(node)) {
      for (const item of node) visit(item);
      return;
    }
    if (node !== null && typeof node === 'object') {
      for (const item of Object.values(node)) visit(item);
    }
  };
  visit(value);
  return found;
}
