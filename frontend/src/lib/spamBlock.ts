import type { AgentRecord } from '@/types';

/** Telegram ограничил аккаунт агента: сервер отдаёт момент начала ограничения. */
export function isSpamBlocked(agent: Pick<AgentRecord, 'warmup_restricted_at'>): boolean {
  return agent.warmup_restricted_at !== null;
}

/**
 * Агенты в спам-блоке — в начало списка, остальные в прежнем порядке: сортировка
 * устойчивая, так что порядок внутри обеих групп не меняется.
 */
export function spamBlockedFirst<T extends Pick<AgentRecord, 'warmup_restricted_at'>>(
  agents: readonly T[],
): T[] {
  return [...agents].sort((a, b) => Number(isSpamBlocked(b)) - Number(isSpamBlocked(a)));
}
