import { describe, expect, it } from 'vitest';
import { deriveOnboardingStep } from '@/hooks/useOnboarding';
import type { OnboardingSessionRow } from '@/types';

function makeSession(overrides: Partial<OnboardingSessionRow> = {}): OnboardingSessionRow {
  return {
    id: '0b3f9c1e-0000-4000-8000-000000000001',
    owner_id: '0b3f9c1e-0000-4000-8000-000000000002',
    agent_name: null,
    soul_prompt: null,
    authorization_status: 'not_started',
    phone_number: null,
    completed_agent_id: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

describe('deriveOnboardingStep', () => {
  it('returns name for missing session', () => {
    expect(deriveOnboardingStep(null)).toBe('name');
    expect(deriveOnboardingStep(undefined)).toBe('name');
  });

  it('returns name for a fresh draft without agent_name', () => {
    expect(deriveOnboardingStep(makeSession())).toBe('name');
  });

  it('returns soul when agent_name is set but soul_prompt is empty', () => {
    expect(deriveOnboardingStep(makeSession({ agent_name: 'Алекс' }))).toBe('soul');
  });

  it('returns telegram step for a draft with prompt and matching auth status', () => {
    const base = { agent_name: 'Алекс', soul_prompt: 'Дружелюбный и краткий' };
    expect(
      deriveOnboardingStep(makeSession({ ...base, authorization_status: 'not_started' }))
    ).toBe('telegram_credentials');
    expect(
      deriveOnboardingStep(makeSession({ ...base, authorization_status: 'code_requested' }))
    ).toBe('telegram_code');
    expect(
      deriveOnboardingStep(makeSession({ ...base, authorization_status: 'password_required' }))
    ).toBe('telegram_2fa');
  });

  it('returns finalize for an authorized draft without completed_agent_id', () => {
    const session = makeSession({
      agent_name: 'Алекс',
      soul_prompt: 'Дружелюбный и краткий',
      authorization_status: 'authorized',
      completed_agent_id: null,
    });
    expect(deriveOnboardingStep(session)).toBe('finalize');
  });
});
