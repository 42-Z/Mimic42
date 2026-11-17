import type { AttackAgentAvailability } from '@/types';

export type MimicAvailabilityTone = 'ready' | 'warning' | 'disabled';

export interface MimicAvailability {
  disabled: boolean;
  note: string | null;
  tone: MimicAvailabilityTone;
}

/**
 * Почему мимика можно или нельзя добавить в атаку. Состояние `active_attack_id`
 * чужой атаки не блокирует добавление: сервис перенесёт мимика, а прежняя
 * атака либо продолжит работу без него, либо отменится, если опустеет.
 */
export function mimicAvailability(
  agent: AttackAgentAvailability,
  currentAttackId?: string | null,
): MimicAvailability {
  if (!agent.telegram_authorized) {
    return { disabled: true, note: 'Сессия Telegram отозвана', tone: 'disabled' };
  }
  if (agent.warmup_restricted_at) {
    return {
      disabled: true,
      note: 'Telegram ограничил аккаунт: писать первым нельзя',
      tone: 'disabled',
    };
  }
  if (agent.active_attack_id && agent.active_attack_id !== currentAttackId) {
    return {
      disabled: false,
      note: 'Уже в другой атаке — будет перенесён',
      tone: 'warning',
    };
  }
  if (agent.state === 'stopped' || agent.state === 'draft') {
    return {
      disabled: false,
      note: 'Остановлен — запустится вместе с атакой',
      tone: 'warning',
    };
  }
  return { disabled: false, note: null, tone: 'ready' };
}
