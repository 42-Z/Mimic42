import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { createElement, type ReactNode } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { AdminAccess } from '@/hooks/useAdminAccess';

let access: AdminAccess;
let retryCalls = 0;

mock.module('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children?: ReactNode }) =>
    createElement('a', { href, ...props }, children),
}));

const { AdminBoundaryContent } = await import('@/components/admin/AdminBoundary');

function setAccess(overrides: Partial<AdminAccess> = {}) {
  access = {
    userId: 'user-id',
    isLoading: false,
    isAdmin: false,
    isDenied: false,
    error: null,
    retry: () => {
      retryCalls += 1;
    },
    ...overrides,
  };
}

beforeEach(() => {
  retryCalls = 0;
  setAccess();
});

afterEach(cleanup);

describe('AdminBoundary', () => {
  test('keeps protected children unmounted while access is loading', () => {
    setAccess({ isLoading: true });

    render(
      <AdminBoundaryContent access={access}>
        <div data-testid="protected-content">Private admin page</div>
      </AdminBoundaryContent>,
    );

    expect(screen.getByRole('status', { name: 'Проверка административного доступа' })).toBeTruthy();
    expect(screen.queryByTestId('protected-content')).toBeNull();
  });

  test('shows an actionable access error without mounting protected children', () => {
    setAccess({ error: new Error('private upstream detail') });

    render(
      <AdminBoundaryContent access={access}>
        <div data-testid="protected-content">Private admin page</div>
      </AdminBoundaryContent>,
    );

    expect(screen.getByRole('alert').textContent).toContain('Не удалось проверить доступ');
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeTruthy();
    expect(screen.getByRole('alert').textContent).not.toContain('private upstream detail');
    expect(screen.queryByTestId('protected-content')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(retryCalls).toBe(1);
  });

  test('denies non-admin users and offers a link to their own dashboard', () => {
    setAccess({ isDenied: true });

    render(
      <AdminBoundaryContent access={access}>
        <div data-testid="protected-content">Private admin page</div>
      </AdminBoundaryContent>,
    );

    expect(screen.getByRole('heading', { name: 'Нет доступа' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'К своим агентам' }).getAttribute('href')).toBe(
      '/dashboard',
    );
    expect(screen.queryByTestId('protected-content')).toBeNull();
  });

  test('renders children only after the server confirms admin access', () => {
    setAccess({ isAdmin: true });

    render(
      <AdminBoundaryContent access={access}>
        <div data-testid="protected-content">Private admin page</div>
      </AdminBoundaryContent>,
    );

    expect(screen.getByTestId('protected-content').textContent).toBe('Private admin page');
  });
});
