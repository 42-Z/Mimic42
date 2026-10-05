import { afterEach, beforeEach, describe, expect, mock, spyOn, test } from 'bun:test';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

const push = mock(() => {});
mock.module('next/navigation', () => ({ useRouter: () => ({ push }) }));

import {
  EMPTY_WARMUP,
  WarmupRestrictionNotice,
  WarmupSettingsSection,
  readWarmup,
} from '@/components/agent/WarmupSettings';
import { ToastProvider } from '@/components/ui/toast';
import { agentsApi, apiClient } from '@/lib/api';
import { agentSettingsSchema, warmupSchema } from '@/lib/validators';
import type { WarmupSettings, WarmupState } from '@/types';

const AGENT_ID = '2dbc9cfd-4860-4c43-8c95-653d5155de00';

function renderSection(initial: WarmupSettings) {
  const seen: { current: WarmupSettings } = { current: initial };
  function Harness() {
    const [value, setValue] = useState(initial);
    seen.current = value;
    return <WarmupSettingsSection value={value} onChange={(u) => setValue((p) => u(p))} />;
  }
  render(<Harness />);
  return seen;
}

function renderNotice() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <WarmupRestrictionNotice agentId={AGENT_ID} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe('readWarmup', () => {
  test('прогрев выключен, пока его явно не включили', () => {
    for (const settings of [null, undefined, {}, { warmup: 'on' }, { warmup: { enabled: 'yes' } }]) {
      expect(readWarmup(settings).enabled).toBe(false);
    }
    expect(readWarmup({})).toEqual(EMPTY_WARMUP);
  });

  test('из настроек читается только переключатель: ограничение ведёт сервер', () => {
    expect(
      readWarmup({
        warmup: { enabled: true, restricted_at: '2026-10-02T10:00:00+00:00', recovery: true },
      }),
    ).toEqual({ enabled: true });
  });
});

describe('WarmupSettingsSection', () => {
  test('переключатель включает прогрев', async () => {
    const user = userEvent.setup();
    const seen = renderSection({ enabled: false });

    await user.click(screen.getByRole('switch', { name: 'Прогрев аккаунта' }));

    expect(seen.current.enabled).toBe(true);
  });

  test('выбора собеседников в дашборде нет: он общий для сервера', () => {
    renderSection({ enabled: true });
    expect(screen.queryByText('С кем переписываться')).toBeNull();
  });
});

describe('WarmupRestrictionNotice', () => {
  beforeEach(() => push.mockClear());
  afterEach(() => mock.restore());

  const restricted: WarmupState = { restricted_at: '2026-10-02T10:00:00+00:00', recovery: false };

  test('без ограничения ничего не показывает', async () => {
    const get = spyOn(agentsApi, 'getWarmupState').mockResolvedValue({
      restricted_at: null,
      recovery: false,
    });
    renderNotice();

    await waitFor(() => expect(get).toHaveBeenCalledWith(AGENT_ID));
    expect(screen.queryByText('Аккаунт ограничен Telegram')).toBeNull();
  });

  test('«Восстановить» уходит запросом к серверу, а не записью настроек', async () => {
    spyOn(agentsApi, 'getWarmupState').mockResolvedValue(restricted);
    const start = spyOn(agentsApi, 'startWarmupRecovery').mockResolvedValue({
      ...restricted,
      recovery: true,
    });
    const settingsWrite = spyOn(apiClient, 'put');
    renderNotice();

    await userEvent.click(await screen.findByRole('button', { name: 'Восстановить перепиской' }));

    await waitFor(() => expect(start).toHaveBeenCalledWith(AGENT_ID));
    expect(await screen.findByText(/Режим восстановления включён:/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Восстановить перепиской' })).toBeNull();
    expect(settingsWrite).not.toHaveBeenCalled();
  });

  test('удаление просит подтверждения', async () => {
    spyOn(agentsApi, 'getWarmupState').mockResolvedValue(restricted);
    const remove = spyOn(agentsApi, 'remove').mockResolvedValue(undefined);
    renderNotice();

    await userEvent.click(await screen.findByRole('button', { name: 'Удалить агента' }));
    expect(remove).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: 'Точно удалить агента' }));
    await waitFor(() => expect(remove).toHaveBeenCalledTimes(1));
    expect(remove.mock.calls[0]?.[0]).toBe(AGENT_ID);
    await waitFor(() => expect(push).toHaveBeenCalledWith('/dashboard'));
  });

  test('при уже включённом восстановлении кнопок выбора нет', async () => {
    spyOn(agentsApi, 'getWarmupState').mockResolvedValue({ ...restricted, recovery: true });
    renderNotice();

    expect(await screen.findByText(/Режим восстановления включён:/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Удалить агента' })).toBeNull();
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
