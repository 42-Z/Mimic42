import { mock } from 'bun:test';

/**
 * Управляемое состояние общего мока `next/navigation`.
 *
 * `mock.module` в Bun действует на весь процесс, поэтому отдельные тестовые
 * файлы не должны переопределять модуль только своими экспортами: следующий
 * файл получит неполный модуль. Все тесты меняют это состояние.
 */
export const navigationMock = {
  pathname: '/',
  params: {} as Record<string, string | string[]>,
  searchParams: new URLSearchParams(),
  push: mock((_href: string) => {}),
  replace: mock((_href: string) => {}),
  back: mock(() => {}),
  refresh: mock(() => {}),
  prefetch: mock(() => {}),
};

export function resetNavigationMock(): void {
  navigationMock.pathname = '/';
  navigationMock.params = {};
  navigationMock.searchParams = new URLSearchParams();
  navigationMock.push.mockClear();
  navigationMock.replace.mockClear();
  navigationMock.back.mockClear();
  navigationMock.refresh.mockClear();
  navigationMock.prefetch.mockClear();
}
