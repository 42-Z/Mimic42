import { afterEach } from 'bun:test';
import { GlobalRegistrator } from '@happy-dom/global-registrator';
import '@testing-library/jest-dom';

// Register happy-dom globals (document, window, ...) for bun test.
GlobalRegistrator.register();

// RTL auto-cleanup only registers when `afterEach` is a global; under bun it is
// module-scoped, so without this the DOM leaks across tests and files. Imported
// after the globals above so RTL binds to the registered document.
const { cleanup } = await import('@testing-library/react');
afterEach(() => {
  cleanup();
});
