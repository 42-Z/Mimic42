import { describe, it, expect } from 'bun:test';
import {
  agentIdSchema, phoneNumberSchema, loginSchema,
  telegramCredentialsSchema, agentSettingsSchema,
} from '@/lib/validators';

describe('agentIdSchema — path traversal protection', () => {
  it('accepts valid UUIDs', () => {
    expect(agentIdSchema.safeParse('abc123-def').success).toBe(true);
    expect(agentIdSchema.safeParse('agent_1').success).toBe(true);
    expect(agentIdSchema.safeParse('ABCDEF123').success).toBe(true);
  });

  it('rejects path traversal attempts', () => {
    expect(agentIdSchema.safeParse('../etc/passwd').success).toBe(false);
    expect(agentIdSchema.safeParse('../../secret').success).toBe(false);
    expect(agentIdSchema.safeParse('agent/../../').success).toBe(false);
  });

  it('rejects XSS in agent ID', () => {
    expect(agentIdSchema.safeParse('<script>alert(1)</script>').success).toBe(false);
    expect(agentIdSchema.safeParse('agent<img onerror=1>').success).toBe(false);
    expect(agentIdSchema.safeParse('id"onmouseover="alert').success).toBe(false);
  });

  it('rejects null bytes and special chars', () => {
    expect(agentIdSchema.safeParse('agent\x00id').success).toBe(false);
    expect(agentIdSchema.safeParse('agent id').success).toBe(false);
    expect(agentIdSchema.safeParse('agent;ls').success).toBe(false);
  });

  it('rejects empty string', () => {
    expect(agentIdSchema.safeParse('').success).toBe(false);
  });

  it('rejects overly long IDs', () => {
    expect(agentIdSchema.safeParse('a'.repeat(65)).success).toBe(false);
  });
});

describe('phoneNumberSchema', () => {
  it('accepts valid E.164 numbers', () => {
    expect(phoneNumberSchema.safeParse('+79991234567').success).toBe(true);
    expect(phoneNumberSchema.safeParse('+12125551234').success).toBe(true);
    expect(phoneNumberSchema.safeParse('+44207946001').success).toBe(true);
  });

  it('prepends the plus sign when it is missing', () => {
    // Форму проверяет только формат. Существует ли номер в Telegram, решает Telegram.
    const result = phoneNumberSchema.safeParse('79991234567');
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data).toBe('+79991234567');
    }
  });

  it('rejects invalid formats', () => {
    expect(phoneNumberSchema.safeParse('+0123456789').success).toBe(false);
    expect(phoneNumberSchema.safeParse('+abc').success).toBe(false);
    expect(phoneNumberSchema.safeParse('').success).toBe(false);
  });

  it('rejects too short / too long', () => {
    expect(phoneNumberSchema.safeParse('+1234').success).toBe(false);
    expect(phoneNumberSchema.safeParse(`+${'1'.repeat(20)}`).success).toBe(false);
  });
});

describe('loginSchema', () => {
  it('accepts valid credentials', () => {
    const result = loginSchema.safeParse({ email: 'user@example.com', password: 'secret123' });
    expect(result.success).toBe(true);
  });

  it('rejects invalid email', () => {
    expect(loginSchema.safeParse({ email: 'notanemail', password: 'pass' }).success).toBe(false);
    expect(loginSchema.safeParse({ email: '', password: 'pass' }).success).toBe(false);
  });

  it('rejects empty password', () => {
    expect(loginSchema.safeParse({ email: 'a@b.com', password: '' }).success).toBe(false);
  });
});

describe('telegramCredentialsSchema', () => {
  const valid = { phone_number: '+79991234567' };

  it('accepts a valid phone number', () => {
    expect(telegramCredentialsSchema.safeParse(valid).success).toBe(true);
  });

  it('rejects a phone that is not a number at all', () => {
    expect(telegramCredentialsSchema.safeParse({ phone_number: 'not-a-phone' }).success).toBe(false);
  });

  it('does not carry api credentials to the backend', () => {
    const result = telegramCredentialsSchema.safeParse({
      ...valid,
      api_id: '12345678',
      api_hash: 'abcdef1234567890abcdef1234567890',
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data).toEqual(valid);
    }
  });
});

describe('agentSettingsSchema', () => {
  it('accepts valid settings', () => {
    const result = agentSettingsSchema.safeParse({
      name: 'My Agent',
      soul_prompt: 'Some personality',
      system_prompt: 'You are an AI assistant',
      model: 'z-ai/glm-5.3-flash',
    });
    expect(result.success).toBe(true);
  });

  it('rejects an unknown model', () => {
    const result = agentSettingsSchema.safeParse({
      name: 'My Agent',
      soul_prompt: 'Some personality',
      model: 'google/gemini-3.1-flash-lite',
    });
    expect(result.success).toBe(false);
  });

  it('rejects a missing model', () => {
    const result = agentSettingsSchema.safeParse({
      name: 'My Agent',
      soul_prompt: 'Some personality',
    });
    expect(result.success).toBe(false);
  });

  it('rejects empty name', () => {
    expect(agentSettingsSchema.safeParse({ name: '', soul_prompt: '', system_prompt: '' }).success).toBe(false);
  });

  it('rejects too long soul_prompt', () => {
    expect(agentSettingsSchema.safeParse({
      name: 'Agent',
      soul_prompt: 'x'.repeat(50_001),
      system_prompt: '',
    }).success).toBe(false);
  });

  it('trims whitespace from name', () => {
    const result = agentSettingsSchema.safeParse({
      name: '  My Agent  ',
      soul_prompt: '',
      system_prompt: '',
      model: 'z-ai/glm-5.3-flash',
    });
    if (result.success) {
      expect(result.data.name).toBe('My Agent');
    }
  });
});
