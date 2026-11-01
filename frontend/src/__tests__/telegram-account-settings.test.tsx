import { afterEach, describe, expect, mock, spyOn, test } from 'bun:test';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { TelegramAccountSettings } from '@/components/agent/TelegramAccountSettings';
import { agentsApi } from '@/lib/api';
import { queryKeys } from '@/lib/queryClient';
import type { TelegramSessionRow } from '@/types';

const AGENT_ID = '11111111-1111-4111-8111-111111111111';

const session: TelegramSessionRow = {
  id: 'sess-1',
  agent_id: AGENT_ID,
  username: 'old_name',
  phone_number: '+79991234567',
  authorization_status: 'authorized',
  last_authorized_at: '2026-09-25T10:00:00Z',
  last_error: null,
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-25T10:00:00Z',
};

function renderSettings(overrides: Partial<TelegramSessionRow> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidate = spyOn(client, 'invalidateQueries');
  const view = render(
    <QueryClientProvider client={client}>
      <TelegramAccountSettings session={{ ...session, ...overrides }} agentId={AGENT_ID} />
    </QueryClientProvider>,
  );
  return { client, invalidate, view };
}

afterEach(() => {
  mock.restore();
});

describe('TelegramAccountSettings', () => {
  test('shows the session facts and the current username', () => {
    renderSettings();
    expect(screen.getByText('Статус авторизации')).toBeTruthy();
    expect(screen.getByText('AUTHORIZED')).toBeTruthy();
    expect(screen.getByText('Номер телефона')).toBeTruthy();
    expect((screen.getByLabelText('Юзернейм') as HTMLInputElement).value).toBe('old_name');
  });

  test('never renders Telegram application secrets', () => {
    renderSettings();
    expect(screen.queryByText(/API\s*ID/i)).toBeNull();
    expect(screen.queryByText(/API\s*HASH/i)).toBeNull();
  });

  test('saves the normalized name and refreshes the name caches', async () => {
    const change = spyOn(agentsApi, 'changeTelegramUsername').mockResolvedValue({
      username: 'new_name',
    });
    const user = userEvent.setup();
    const { invalidate } = renderSettings();

    const input = screen.getByLabelText('Юзернейм') as HTMLInputElement;
    await user.clear(input);
    await user.type(input, '@new_name');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() =>
      expect(change).toHaveBeenCalledWith(AGENT_ID, { username: 'new_name' }),
    );
    expect(await screen.findByText('Сохранено: @new_name')).toBeTruthy();
    expect(input.value).toBe('new_name');
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.telegram.byAgent(AGENT_ID) });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.agents.all });
  });

  test('a background refresh does not overwrite the typed name', async () => {
    const user = userEvent.setup();
    const { client, view } = renderSettings();

    const input = screen.getByLabelText('Юзернейм') as HTMLInputElement;
    await user.clear(input);
    await user.type(input, 'typed_name');

    view.rerender(
      <QueryClientProvider client={client}>
        <TelegramAccountSettings session={{ ...session, username: 'server_name' }} agentId={AGENT_ID} />
      </QueryClientProvider>,
    );

    expect(input.value).toBe('typed_name');
  });

  test('an invalid name stays in the form and never reaches the API', async () => {
    const change = spyOn(agentsApi, 'changeTelegramUsername');
    const user = userEvent.setup();
    renderSettings();

    const input = screen.getByLabelText('Юзернейм') as HTMLInputElement;
    await user.clear(input);
    await user.type(input, 'bad name');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    expect(change).not.toHaveBeenCalled();
    expect(screen.getByText(/Нужны 5-32 символа/)).toBeTruthy();
  });

  test('does not read the password state until the form is opened', async () => {
    const state = spyOn(agentsApi, 'getTelegramPasswordState').mockResolvedValue({
      has_password: false,
    });
    const user = userEvent.setup();
    renderSettings();

    expect(state).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Настроить' }));

    await waitFor(() => expect(state).toHaveBeenCalledWith(AGENT_ID));
    expect(await screen.findByLabelText('Пароль')).toBeTruthy();
  });

  test('installs a password without putting it into the mutation cache', async () => {
    spyOn(agentsApi, 'getTelegramPasswordState').mockResolvedValue({ has_password: false });
    const change = spyOn(agentsApi, 'changeTelegramPassword').mockResolvedValue({ changed: true });
    const user = userEvent.setup();
    const { client } = renderSettings();

    await user.click(screen.getByRole('button', { name: 'Настроить' }));
    const input = (await screen.findByLabelText('Пароль')) as HTMLInputElement;
    await user.type(input, 'new_secret');
    await user.click(screen.getByRole('button', { name: 'Установить пароль' }));

    await waitFor(() =>
      expect(change).toHaveBeenCalledWith(AGENT_ID, { new_password: 'new_secret' }),
    );
    expect(await screen.findByText('Пароль установлен')).toBeTruthy();
    expect(input.value).toBe('');
    expect(client.getMutationCache().getAll()).toHaveLength(0);
  });

  test('changing a password confirms the current one and clears both fields', async () => {
    spyOn(agentsApi, 'getTelegramPasswordState').mockResolvedValue({ has_password: true });
    const change = spyOn(agentsApi, 'changeTelegramPassword').mockResolvedValue({ changed: true });
    const user = userEvent.setup();
    renderSettings();

    await user.click(screen.getByRole('button', { name: 'Настроить' }));
    const current = (await screen.findByLabelText('Текущий пароль')) as HTMLInputElement;
    const next = screen.getByLabelText('Новый пароль') as HTMLInputElement;
    await user.type(current, 'old_secret');
    await user.type(next, 'new_secret');
    await user.click(screen.getByRole('button', { name: 'Сменить пароль' }));

    await waitFor(() =>
      expect(change).toHaveBeenCalledWith(AGENT_ID, {
        current_password: 'old_secret',
        new_password: 'new_secret',
      }),
    );
    expect(await screen.findByText('Пароль изменён')).toBeTruthy();
    expect(current.value).toBe('');
    expect(next.value).toBe('');
  });

  test('a wrong current password keeps the typed values for a retry', async () => {
    spyOn(agentsApi, 'getTelegramPasswordState').mockResolvedValue({ has_password: true });
    spyOn(agentsApi, 'changeTelegramPassword').mockRejectedValue({
      message: 'Неверный текущий облачный пароль. Пароль не изменён.',
    });
    const user = userEvent.setup();
    renderSettings();

    await user.click(screen.getByRole('button', { name: 'Настроить' }));
    const current = (await screen.findByLabelText('Текущий пароль')) as HTMLInputElement;
    const next = screen.getByLabelText('Новый пароль') as HTMLInputElement;
    await user.type(current, 'wrong_secret');
    await user.type(next, 'new_secret');
    await user.click(screen.getByRole('button', { name: 'Сменить пароль' }));

    expect(
      await screen.findByText('Неверный текущий облачный пароль. Пароль не изменён.'),
    ).toBeTruthy();
    expect(current.value).toBe('wrong_secret');
    expect(next.value).toBe('new_secret');
  });

  test('a failed state read shows the error and no password form', async () => {
    spyOn(agentsApi, 'getTelegramPasswordState').mockRejectedValue({
      status: 428,
      message: 'Сессия Telegram недействительна. Требуется повторная привязка Telegram-аккаунта.',
    });
    const user = userEvent.setup();
    renderSettings();

    await user.click(screen.getByRole('button', { name: 'Настроить' }));

    expect(
      await screen.findByText(
        'Сессия Telegram недействительна. Требуется повторная привязка Telegram-аккаунта.',
      ),
    ).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Перепривязать Telegram' }).getAttribute('href')).toBe(
      `/agent/${AGENT_ID}/rebind`,
    );
    expect(screen.queryByLabelText('Пароль')).toBeNull();
  });
});
