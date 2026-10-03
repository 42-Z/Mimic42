import { describe, expect, test } from 'bun:test';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import {
  EMPTY_WARMUP,
  WarmupSettingsSection,
  readWarmup,
} from '@/components/agent/WarmupSettings';
import { agentSettingsSchema, warmupSchema } from '@/lib/validators';

function renderSection(initial: { enabled: boolean }) {
  const seen: { current: { enabled: boolean } } = { current: initial };
  function Harness() {
    const [value, setValue] = useState(initial);
    seen.current = value;
    return <WarmupSettingsSection value={value} onChange={(u) => setValue((p) => u(p))} />;
  }
  render(<Harness />);
  return seen;
}

describe('readWarmup', () => {
  test('прогрев выключен, пока его явно не включили', () => {
    for (const settings of [null, undefined, {}, { warmup: 'on' }, { warmup: { enabled: 'yes' } }]) {
      expect(readWarmup(settings).enabled).toBe(false);
    }
    expect(readWarmup({})).toEqual(EMPTY_WARMUP);
  });

  test('читает включение, ограничение и режим восстановления', () => {
    expect(
      readWarmup({
        warmup: { enabled: true, restricted_at: '2026-10-02T10:00:00+00:00', recovery: true },
      }),
    ).toEqual({ enabled: true, restricted_at: '2026-10-02T10:00:00+00:00', recovery: true });
  });

  test('мусор вместо ограничения не ломает форму', () => {
    const parsed = readWarmup({ warmup: { enabled: true, restricted_at: 5, recovery: 'да' } });
    expect(parsed).toEqual({ enabled: true, restricted_at: null, recovery: false });
  });
});

describe('WarmupSettingsSection', () => {
  test('переключатель включает прогрев', async () => {
    const user = userEvent.setup();
    const seen = renderSection({ enabled: false });

    await user.click(screen.getByRole('switch', { name: 'Прогрев аккаунта' }));

    expect(seen.current.enabled).toBe(true);
  });

  test('выбора собеседников в дашборде больше нет', () => {
    renderSection({ enabled: true });
    expect(screen.queryByText('С кем переписываться')).toBeNull();
  });
});

describe('схема настроек', () => {
  test('принимает настройки без прогрева и с ним', () => {
    const base = { name: 'Аня', soul_prompt: '', model: 'x/y' };
    expect(agentSettingsSchema.safeParse(base).success).toBe(true);
    expect(agentSettingsSchema.safeParse({ ...base, warmup: { enabled: true } }).success).toBe(true);
    expect(warmupSchema.safeParse({ enabled: 'да' }).success).toBe(false);
  });
});
