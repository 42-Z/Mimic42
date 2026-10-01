/**
 * Настройки инструментов в `agents.settings` — зеркало
 * `src/mimic42/core/tool_config.py`.
 */

/**
 * Прочитать allowlist инструментов из settings.
 *
 * `null` — ключа нет (включены все) или значение нечитаемо. Пустой массив —
 * честный пустой allowlist. Непустой массив без валидных строк — мусор:
 * ведём себя как при отсутствии ключа, как и бэкенд.
 */
export function readEnabledTools(
  settings: Record<string, unknown> | null | undefined,
): string[] | null {
  if (!settings) return null;
  const value = settings.enabled_tools;
  if (!Array.isArray(value)) return null;
  const names = value
    .filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    .map((item) => item.trim());
  if (names.length === 0 && value.length > 0) return null;
  return names;
}

/**
 * Вернуть настройки с обновлённым `enabled_tools`.
 *
 * Список (включая пустой) записывается как есть; `null`/`undefined` — режим
 * «включены все»: ключ удаляется. Исходный объект не мутируется.
 */
export function mergeEnabledTools(
  existing: Record<string, unknown>,
  enabledTools: string[] | null | undefined,
): Record<string, unknown> {
  const merged = { ...existing };
  if (enabledTools != null) {
    merged.enabled_tools = enabledTools;
  } else {
    delete merged.enabled_tools;
  }
  return merged;
}
