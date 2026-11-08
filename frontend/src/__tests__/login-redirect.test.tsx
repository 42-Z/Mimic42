import { afterEach, describe, expect, spyOn, test } from 'bun:test';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import LoginPage from '@/app/(auth)/login/page';
import { ToastProvider } from '@/components/ui/toast';
import * as supabaseClient from '@/lib/supabase/client';
import { navigationMock } from './next-navigation-mock';

afterEach(() => {
  restoreClient?.();
});

let restoreClient: (() => void) | undefined;

describe('login redirect', () => {
  const cases: [string | null, string][] = [
    [null, '/dashboard'],
    ['', '/dashboard'],
    ['/', '/'],
    ['/dashboard#activity', '/dashboard#activity'],
    ['/admin/users?search=a%2Bb#results', '/admin/users?search=a%2Bb#results'],
    ['javascript:alert(document.domain)', '/dashboard'],
    ['data:text/html,<script>alert(1)</script>', '/dashboard'],
    ['https://evil.example/path', '/dashboard'],
    ['//evil.example/path', '/dashboard'],
    ['/\\evil.example/path', '/dashboard'],
    ['/\t/evil.example/path', '/dashboard'],
    ['/\n/evil.example/path', '/dashboard'],
    ['/\r/evil.example/path', '/dashboard'],
    ['/\u0000/evil.example/path', '/dashboard'],
    ['/%2f%2fevil.example', '/dashboard'],
    ['/%5cevil.example', '/dashboard'],
    ['/%09/evil.example', '/dashboard'],
    ['/%252f%252fevil.example', '/dashboard'],
    ['/safe/..//evil.example', '/dashboard'],
    ['/safe/%2e%2e//evil.example', '/dashboard'],
    ['/dashboard?next=https%3A%2F%2Fexample.com#details', '/dashboard?next=https%3A%2F%2Fexample.com#details'],
    ['/agents/my%20agent?tab=activity#latest', '/agents/my%20agent?tab=activity#latest'],
    ['dashboard', '/dashboard'],
    [' /admin', '/dashboard'],
    ['https://mimic.test/admin', '/dashboard'],
    ['/%ZZ', '/dashboard'],
  ];

  test.each(cases)('routes %j to %s after successful login', async (redirect, expected) => {
    const signInSpy = spyOn(supabaseClient, 'getSupabaseClient').mockReturnValue({
      auth: { signInWithPassword: async () => ({ error: null }) },
    } as unknown as ReturnType<typeof supabaseClient.getSupabaseClient>);
    restoreClient = () => { signInSpy.mockRestore(); };
    if (redirect !== null) navigationMock.searchParams.set('redirect', redirect);

    render(<ToastProvider><LoginPage /></ToastProvider>);
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'login@example.com' } });
    fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'password123' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Войти' }).closest('form')!);

    await waitFor(() => expect(navigationMock.push).toHaveBeenCalledTimes(1));
    expect(navigationMock.push).toHaveBeenCalledWith(expected);
  });
});
