'use client';

import { useQuery } from '@tanstack/react-query';

import type { ModelReasoningMeta } from '@/lib/reasoning';

interface OpenRouterModel {
  id: string;
  reasoning?: ModelReasoningMeta;
}

/**
 * Per-model reasoning metadata from the OpenRouter Models API (public, no
 * key required). Keyed by model slug, undefined for models without the
 * `reasoning` field.
 */
export function useModelReasoning() {
  return useQuery({
    queryKey: ['openrouter', 'models'],
    queryFn: async () => {
      const response = await fetch('https://openrouter.ai/api/v1/models');
      if (!response.ok) {
        throw new Error(`OpenRouter Models API error: ${response.status}`);
      }
      const json = (await response.json()) as { data: OpenRouterModel[] };
      const reasoningByModel: Record<string, ModelReasoningMeta | undefined> = {};
      for (const model of json.data) {
        reasoningByModel[model.id] = model.reasoning;
      }
      return reasoningByModel;
    },
    staleTime: 10 * 60 * 1000,
    retry: 1,
  });
}
