export interface ModelOption {
  value: string;
  label: string;
}

export const MODEL_OPTIONS: ModelOption[] = [
  { value: 'z-ai/glm-5.3-flash', label: 'GLM 5.3 Flash' },
  { value: 'deepseek/deepseek-v4.1-flash-1017', label: 'DeepSeek V4.1 Flash 1017' },
  { value: 'inclusionai/ling-3.0-flash-vl', label: 'Ling 3.0 Flash VL' },
  { value: 'nvidia/nemotron-3.5-super-vl', label: 'Nemotron 3.5 Super VL' },
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
