import { afterEach, mock } from 'bun:test';
import { GlobalRegistrator } from '@happy-dom/global-registrator';
import '@testing-library/jest-dom';
import { navigationMock, resetNavigationMock } from './next-navigation-mock';

// Register happy-dom globals (document, window, ...) for bun test.
GlobalRegistrator.register();

// Один мок на весь прогон: точечные `mock.module('next/navigation')` в тестах
// подменяли модуль целиком и оставляли соседние файлы без нужных экспортов.
mock.module('next/navigation', () => ({
  usePathname: () => navigationMock.pathname,
  useRouter: () => ({
    push: navigationMock.push,
    replace: navigationMock.replace,
    back: navigationMock.back,
    forward: () => undefined,
    refresh: navigationMock.refresh,
    prefetch: navigationMock.prefetch,
  }),
  useParams: () => navigationMock.params,
  useSearchParams: () => navigationMock.searchParams,
  redirect: () => undefined,
  notFound: () => undefined,
}));

// RTL auto-cleanup only registers when `afterEach` is a global; under bun it is
// module-scoped, so without this the DOM leaks across tests and files. Imported
// after the globals above so RTL binds to the registered document.
const { cleanup } = await import('@testing-library/react');
afterEach(() => {
  cleanup();
  resetNavigationMock();
});
