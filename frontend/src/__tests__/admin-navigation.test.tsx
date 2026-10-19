import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { createElement, type ReactNode } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

let pathname = '/admin';

mock.module('next/navigation', () => ({
  usePathname: () => pathname,
}));

mock.module('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children?: ReactNode }) =>
    createElement('a', { href, ...props }, children),
}));

const { AdminNavigation } = await import('@/components/admin/AdminNavigation');
const { AdminPagination } = await import('@/components/admin/AdminPagination');

beforeEach(() => {
  pathname = '/admin';
});

afterEach(cleanup);

describe('AdminNavigation', () => {
  test('links to all four deep-linked sections and only marks the exact overview route active', () => {
    pathname = '/admin';
    const { rerender } = render(<AdminNavigation />);

    const links = screen.getAllByRole('link');
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/admin',
      '/admin/users',
      '/admin/presets',
      '/admin/telegram',
    ]);
    expect(links.filter((link) => link.getAttribute('aria-current') === 'page')).toHaveLength(1);
    expect(links[0]?.getAttribute('aria-current')).toBe('page');

    pathname = '/admin/users/11111111-1111-1111-1111-111111111111';
    rerender(<AdminNavigation />);
    expect(screen.getByRole('link', { name: 'Пользователи' }).getAttribute('aria-current')).toBe(
      'page',
    );
    expect(screen.getByRole('link', { name: 'Обзор' }).getAttribute('aria-current')).toBeNull();

    pathname = '/administrator';
    rerender(<AdminNavigation />);
    expect(screen.getAllByRole('link').every((link) => !link.hasAttribute('aria-current'))).toBe(
      true,
    );
  });
});

describe('AdminPagination', () => {
  test('reports page totals and sends previous/next selections', () => {
    const pages: number[] = [];
    render(
      <AdminPagination page={2} pageSize={25} total={101} onPageChange={(page) => pages.push(page)} />,
    );

    expect(screen.getByText('Страница 2 из 5')).toBeTruthy();
    expect(screen.getByText('Всего: 101')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Предыдущая страница' }));
    fireEvent.click(screen.getByRole('button', { name: 'Следующая страница' }));
    expect(pages).toEqual([1, 3]);
  });

  test('disabled page transitions are not keyboard-focusable', () => {
    render(
      <AdminPagination page={1} pageSize={25} total={0} onPageChange={() => undefined} />,
    );

    const previous = screen.getByRole('button', { name: 'Предыдущая страница' });
    const next = screen.getByRole('button', { name: 'Следующая страница' });
    expect(previous.hasAttribute('disabled')).toBe(true);
    expect(next.hasAttribute('disabled')).toBe(true);
    expect(screen.getByText('Страница 1 из 1')).toBeTruthy();
  });
});
