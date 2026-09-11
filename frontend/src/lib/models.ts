export interface ModelOption {
  value: string;
  label: string;
}

export const MODEL_OPTIONS: ModelOption[] = [
  { value: 'z-ai/glm-5.3-flash', label: 'GLM 5.3 Flash' },
  { value: 'deepseek/deepseek-v4-flash-0731', label: 'DeepSeek V4 Flash 0731' },
  { value: 'inclusionai/ling-3.0-flash-vl', label: 'Ling 3.0 Flash VL' },
  { value: 'meituan/longcat-2.0', label: 'Longcat 2.0' },
  { value: 'poolside/laguna-s-2.1', label: 'Laguna S 2.1' },
];

const MODEL_VALUES = MODEL_OPTIONS.map((m) => m.value) as [string, ...string[]];

export const DEFAULT_MODEL = MODEL_VALUES[0];

/**
 * Menu options with the stored slug kept visible: legacy values outside the
 * catalog must not silently display as the first menu entry.
 */
export function optionsIncluding(current: string): ModelOption[] {
  if (MODEL_OPTIONS.some((o) => o.value === current)) return MODEL_OPTIONS;
  return [{ value: current, label: current }, ...MODEL_OPTIONS];
}
