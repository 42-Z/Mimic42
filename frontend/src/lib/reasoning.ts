export interface ModelReasoningMeta {
  supported_efforts?: string[] | null;
  default_effort?: string;
  mandatory?: boolean;
  default_enabled?: boolean;
  supports_max_tokens?: boolean;
}

export const GATEWAY_EFFORTS = [
  'max',
  'xhigh',
  'high',
  'medium',
  'low',
  'minimal',
  'none',
] as const;

export const REASONING_LABELS: Record<string, string> = {
  none: 'None (Без рассуждения)',
  minimal: 'Minimal (Минимальное)',
  low: 'Low (Низкое)',
  medium: 'Medium (Среднее)',
  high: 'High (Глубокое)',
  xhigh: 'XHigh (Максимальное)',
  max: 'Max (Максимум)',
};

const REASONING_LABEL_MAP = new Map(Object.entries(REASONING_LABELS));

export function reasoningLabel(effort: string): string {
  return REASONING_LABEL_MAP.get(effort) ?? effort;
}

/**
 * Effort options for the reasoning select, or null when the model does not
 * expose effort selection and the control should be hidden.
 *
 * Semantics from the OpenRouter docs (GET /api/v1/models → model.reasoning):
 * - no `reasoning` field → the model does not expose effort selection;
 * - `reasoning` present without `supported_efforts` → the same;
 * - `supported_efforts: null` → every gateway effort value is accepted;
 * - array → those values, in descending effort order; `none` is appended
 *   unless `mandatory` (a mandatory model rejects `effort: "none"`).
 */
export function reasoningOptionValues(
  meta: ModelReasoningMeta | undefined | null
): readonly string[] | null {
  if (!meta || meta.supported_efforts === undefined) return null;
  if (meta.supported_efforts === null) return GATEWAY_EFFORTS;
  const options = [...meta.supported_efforts];
  if (meta.mandatory !== true) options.push('none');
  return options;
}

/**
 * Value to show in the reasoning select: keep the current one when the model
 * supports it, otherwise fall back to the model default, then to the first
 * available option.
 */
export function pickReasoningValue(
  current: string,
  options: readonly string[] | null,
  meta?: ModelReasoningMeta | null
): string | undefined {
  if (options === null) return undefined;
  if (options.includes(current)) return current;
  const fallback = meta?.default_effort;
  if (fallback && options.includes(fallback)) return fallback;
  return options[0];
}
