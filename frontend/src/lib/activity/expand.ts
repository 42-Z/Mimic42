/**
 * Раскрытие стеков запусков/остановок живёт по id событий, а не по позиции
 * группы в списке: «Загрузить ещё» дописывает старые события к той же
 * последовательности, realtime — новые сверху, и ни то, ни другое не должно
 * схлопывать уже раскрытый стек.
 */
export type ExpandedStackIds = ReadonlySet<string>;

export function isStackOpen(ids: readonly string[], expanded: ExpandedStackIds): boolean {
  return ids.some((id) => expanded.has(id));
}

export function setStackOpen(
  expanded: ExpandedStackIds,
  ids: readonly string[],
  open: boolean,
): ExpandedStackIds {
  const next = new Set(expanded);
  for (const id of ids) {
    if (open) next.add(id);
    else next.delete(id);
  }
  return next;
}
