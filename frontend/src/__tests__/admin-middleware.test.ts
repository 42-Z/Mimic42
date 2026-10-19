import { afterAll, beforeEach, expect, mock, test } from 'bun:test';
import { NextRequest } from 'next/server';

let signedIn = true;
let hasAgent = false;
let agentLookups = 0;

mock.module('@supabase/ssr', () => ({
  createServerClient: () => ({
    auth: {
      getUser: async () => ({
        data: { user: signedIn ? { id: 'user-id' } : null },
        error: null,
      }),
    },
    from: (table: string) => ({
      select: () => ({
        eq: () => ({
          limit: async () => {
            agentLookups += 1;
            if (table !== 'agents') throw new Error(`Unexpected table: ${table}`);
            return { data: hasAgent ? [{ id: 'agent-id' }] : [], error: null };
          },
        }),
      }),
    }),
  }),
}));

const { middleware } = await import('@/middleware');

beforeEach(() => {
  signedIn = true;
  hasAgent = false;
  agentLookups = 0;
});

afterAll(() => mock.restore());

test('signed-in administrators can open /admin without owning an agent', async () => {
  const response = await middleware(new NextRequest('https://mimic.test/admin'));

  expect(response.status).toBe(200);
  expect(response.headers.get('location')).toBeNull();
  expect(response.headers.get('x-middleware-next')).toBe('1');
  expect(agentLookups).toBe(0);
});

test('ordinary dashboard routes preserve the onboarding redirect without an agent', async () => {
  const response = await middleware(new NextRequest('https://mimic.test/dashboard'));

  expect(response.status).toBe(307);
  expect(response.headers.get('location')).toBe('https://mimic.test/onboarding');
  expect(agentLookups).toBe(1);
});

test('/administrator does not bypass the regular agent check', async () => {
  const response = await middleware(new NextRequest('https://mimic.test/administrator'));

  expect(response.status).toBe(307);
  expect(response.headers.get('location')).toBe('https://mimic.test/onboarding');
  expect(agentLookups).toBe(1);
});

test('the ordinary dashboard remains accessible when the user owns an agent', async () => {
  hasAgent = true;
  const response = await middleware(new NextRequest('https://mimic.test/dashboard'));

  expect(response.status).toBe(200);
  expect(response.headers.get('x-middleware-next')).toBe('1');
  expect(agentLookups).toBe(1);
});

test('the admin path still requires an authenticated Supabase user', async () => {
  signedIn = false;
  const response = await middleware(new NextRequest('https://mimic.test/admin'));

  expect(response.status).toBe(307);
  expect(response.headers.get('location')).toBe('https://mimic.test/login?redirect=%2Fadmin');
  expect(agentLookups).toBe(0);
});
