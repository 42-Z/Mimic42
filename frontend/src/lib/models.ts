export interface ModelOption {
  value: string;
  label: string;
  freeVariant: boolean;
}

export const MODEL_OPTIONS: ModelOption[] = [
  { value: 'z-ai/glm-5.3-flash', label: 'GLM 5.3 Flash', freeVariant: false },
  { value: 'deepseek/deepseek-v4-flash-0731', label: 'DeepSeek V4 Flash 0731', freeVariant: false },
  { value: 'inclusionai/ling-3.0-flash-vl', label: 'Ling 3.0 Flash VL', freeVariant: true },
  { value: 'meituan/longcat-2.0', label: 'Longcat 2.0', freeVariant: false },
  { value: 'poolside/laguna-s-2.1', label: 'Laguna S 2.1', freeVariant: true },
];

const MODEL_VALUES = MODEL_OPTIONS.map((m) => m.value) as [string, ...string[]];

export const DEFAULT_MODEL = MODEL_VALUES[0];
