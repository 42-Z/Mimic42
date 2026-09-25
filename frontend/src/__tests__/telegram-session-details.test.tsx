import { describe, expect, test } from 'bun:test';
import { render, screen } from '@testing-library/react';
import { TelegramSessionDetails } from '@/components/agent/TelegramSessionDetails';
import type { TelegramSessionRow } from '@/types';

const session: TelegramSessionRow = {
  id: 'sess-1',
  agent_id: 'agent-1',
  username: 'mimic42',
  phone_number: '+79991234567',
  authorization_status: 'authorized',
  last_authorized_at: '2026-09-25T10:00:00Z',
  last_error: null,
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-25T10:00:00Z',
};

describe('TelegramSessionDetails', () => {
  test('показывает основные данные сессии', () => {
    render(<TelegramSessionDetails session={session} />);
    expect(screen.getByText('Статус авторизации')).toBeTruthy();
    expect(screen.getByText('Номер телефона')).toBeTruthy();
    expect(screen.getByText('@mimic42')).toBeTruthy();
  });

  test('не показывает API ID', () => {
    render(<TelegramSessionDetails session={session} />);
    expect(screen.queryByText(/API\s*ID/i)).toBeNull();
    expect(screen.queryByText('12345')).toBeNull();
  });

  test('не показывает API HASH', () => {
    render(<TelegramSessionDetails session={session} />);
    expect(screen.queryByText(/API\s*HASH/i)).toBeNull();
  });
});
