'use client';

import { useQuery } from '@tanstack/react-query';

import { apiClient } from '@/lib/api';
import { MODEL_OPTIONS } from '@/lib/models';
import type { ModelReasoningMeta } from '@/lib/reasoning';

/**
 * Per-model reasoning metadata, proxied through our backend: openrouter.ai
 * is unreachable from some countries, the server can always reach it.
 * Keyed by model slug, undefined for models without the `reasoning` field.
 */
export function useModelReasoning() {
  return useQuery({
    queryKey: ['openrouter', 'reasoning'],
    queryFn: async () => {
      try {
        const response = await apiClient.get<{ models: Record<string, ModelReasoningMeta | undefined> }>(
          '/openrouter/reasoning'
        );
        return response.data.models;
      } catch {
        // Backend could not reach OpenRouter: fall back to the documented
        // "null → all gateway efforts accepted" semantics per model, so the
        // settings form stays usable.
        const fallback: Record<string, ModelReasoningMeta | undefined> = {};
        for (const option of MODEL_OPTIONS) {
          fallback[option.value] = { supported_efforts: null };
        }
        return fallback;
      }
    },
    staleTime: 10 * 60 * 1000,
    retry: 1,
  });
}
