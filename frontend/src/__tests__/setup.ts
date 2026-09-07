import '@testing-library/jest-dom';
import { beforeAll } from 'vitest';
import { preloadSanitizer } from '@/lib/sanitize';

// DOMPurify must be loaded before sanitize tests run: without it
// sanitizeClientSide falls back to entity-encoding instead of stripping.
beforeAll(async () => {
  await preloadSanitizer();
});
