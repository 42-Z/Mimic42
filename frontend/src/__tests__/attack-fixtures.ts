import type { AttackAgent, AttackAgentAvailability, AttackDetail } from '@/types';

export const OWNER_ID = '00000000-0000-4000-8000-000000000001';
export const ACTIVE_ATTACK_ID = '11111111-1111-4111-8111-111111111111';
export const ARCHIVE_ATTACK_ID = '22222222-2222-4222-8222-222222222222';
export const MIMIC_A_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
export const MIMIC_B_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
export const MIMIC_C_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

export function makeAgent(
  overrides: Partial<AttackAgent> & Pick<AttackAgent, 'name'>,
): AttackAgent {
  const { name, ...rest } = overrides;
  return {
    id: `participation-${name}`,
    attack_id: ACTIVE_ATTACK_ID,
    agent_id: MIMIC_A_ID,
    name,
    status: 'active',
    sent_count: 0,
    next_at: null,
    last_error: null,
    exit_reason: null,
    note_written_at: null,
    ...rest,
  };
}

export function makeAttack(overrides: Partial<AttackDetail> = {}): AttackDetail {
  const base: AttackDetail = {
    id: ACTIVE_ATTACK_ID,
    owner_id: OWNER_ID,
    title: 'Розыгрыш',
    target_link: 'https://t.me/example/412',
    status: 'running',
    limit_kind: 'messages',
    limit_value: 40,
    sent_count: 12,
    claimed_count: 13,
    version: 2,
    started_at: '2026-11-16T10:00:00.000Z',
    finished_at: null,
    deadline_at: null,
    end_reason: null,
    slowmode_seconds: 30,
    agents: [
      makeAgent({ name: 'Мила', sent_count: 7, status: 'active' }),
      makeAgent({
        id: 'participation-Гоша',
        agent_id: MIMIC_B_ID,
        name: 'Гоша',
        sent_count: 5,
        status: 'active',
        last_error: 'SlowModeWaitError: 30',
      }),
    ],
    texts: ['Участвую!', 'Бросаю в зачёт'],
    media: [
      {
        path: 'attacks/owner/uuid/a.jpg',
        name: 'a.jpg',
        url: 'https://signed.test/a.jpg',
      },
    ],
  };
  return { ...base, ...overrides };
}

export function makeArchive(overrides: Partial<AttackDetail> = {}): AttackDetail {
  return makeAttack({
    id: ARCHIVE_ATTACK_ID,
    title: 'Старая атака',
    status: 'finished',
    limit_value: 20,
    sent_count: 20,
    claimed_count: 20,
    finished_at: '2026-11-16T11:00:00.000Z',
    end_reason: 'limit_reached',
    agents: [
      makeAgent({
        id: 'participation-Гоша-archive',
        agent_id: MIMIC_B_ID,
        name: 'Гоша',
        status: 'exited',
        sent_count: 20,
        exit_reason: 'attack_finished',
      }),
    ],
    texts: ['Финальный текст'],
    media: [],
    ...overrides,
  });
}

export function makeAvailability(
  overrides: Partial<AttackAgentAvailability> & Pick<AttackAgentAvailability, 'agent_id' | 'name'>,
): AttackAgentAvailability {
  const { agent_id, name, ...rest } = overrides;
  return {
    agent_id,
    name,
    state: 'running',
    telegram_authorized: true,
    warmup_restricted_at: null,
    active_attack_id: null,
    ...rest,
  };
}
