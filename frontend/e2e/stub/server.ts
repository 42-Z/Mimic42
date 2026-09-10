#!/usr/bin/env bun
/**
 * Minimal Supabase-compatible stub for Playwright e2e tests.
 *
 * Implements just enough of GoTrue (`/auth/v1/*`) and PostgREST
 * (`/rest/v1/*`) for the app's actual request shapes — see the queries in
 * `src/hooks/*` and `src/lib/supabase/*`. Anything else returns 501 so
 * missing coverage fails loudly instead of silently passing.
 *
 * State is shared but partitioned by owner: every spec file logs in as its
 * own fixed user (see USERS) and only touches its own rows, so parallel
 * files never interfere. `POST /__reset__` reseeds everything (called once
 * from auth.setup); `PATCH /__row__ {table, id, patch}` emulates backend
 * side-effects on Supabase rows (the real FastAPI is mocked in e2e).
 *
 * The realtime websocket (`/realtime/v1/websocket`) is deliberately refused
 * with 404 — the UI must render its OFFLINE state.
 */

const PORT = Number(process.env.E2E_STUB_PORT ?? '54321');

// ── Fixed test identities ───────────────────────────────────────────────────
// One user per e2e area. Server-side code (middleware, route handlers) cannot
// see per-request test headers, so isolation is done by owner_id instead:
// every spec file logs in as its own user and only touches its own rows.

interface StubUser {
  id: string;
  email: string;
  password: string;
  accessToken: string;
  refreshToken: string;
}

const USERS: Record<string, StubUser> = {
  empty: {
    id: '11111111-1111-1111-1111-111111111111',
    email: 'e2e@mimic42.test',
    password: 'password123',
    accessToken: 'e2e-access-token-empty',
    refreshToken: 'e2e-refresh-token-empty',
  },
  full: {
    id: '22222222-2222-2222-2222-222222222222',
    email: 'e2e-full@mimic42.test',
    password: 'password123',
    accessToken: 'e2e-access-token-full',
    refreshToken: 'e2e-refresh-token-full',
  },
  flow: {
    id: '33333333-3333-3333-3333-333333333333',
    email: 'e2e-flow@mimic42.test',
    password: 'password123',
    accessToken: 'e2e-access-token-flow',
    refreshToken: 'e2e-refresh-token-flow',
  },
  '2fa': {
    id: '44444444-4444-4444-4444-444444444444',
    email: 'e2e-2fa@mimic42.test',
    password: 'password123',
    accessToken: 'e2e-access-token-2fa',
    refreshToken: 'e2e-refresh-token-2fa',
  },
  code: {
    id: '55555555-5555-5555-5555-555555555555',
    email: 'e2e-code@mimic42.test',
    password: 'password123',
    accessToken: 'e2e-access-token-code',
    refreshToken: 'e2e-refresh-token-code',
  },
};

function userByEmail(email: unknown): StubUser | null {
  if (typeof email !== 'string') return null;
  return Object.values(USERS).find((candidate) => candidate.email === email) ?? null;
}

function userByToken(token: string): StubUser | null {
  return (
    Object.values(USERS).find(
      (candidate) => candidate.accessToken === token || candidate.refreshToken === token,
    ) ?? null
  );
}

// ── Types ───────────────────────────────────────────────────────────────────

type Row = Record<string, unknown>;

type TableName =
  | 'agents'
  | 'agent_onboarding_sessions'
  | 'telegram_sessions'
  | 'message_threads'
  | 'agent_messages'
  | 'agent_events';

type ScenarioState = Record<TableName, Row[]>;

const TABLES: TableName[] = [
  'agents',
  'agent_onboarding_sessions',
  'telegram_sessions',
  'message_threads',
  'agent_messages',
  'agent_events',
];

// ── Auth fixtures ───────────────────────────────────────────────────────────

function userObject(user: StubUser): Row {
  const stamp = new Date().toISOString();
  return {
    id: user.id,
    aud: 'authenticated',
    role: 'authenticated',
    email: user.email,
    email_confirmed_at: stamp,
    phone: '',
    created_at: stamp,
    updated_at: stamp,
  };
}

function sessionObject(user: StubUser): Row {
  return {
    access_token: user.accessToken,
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    refresh_token: user.refreshToken,
    user: userObject(user),
  };
}

function bearer(req: Request): string | null {
  const header = req.headers.get('authorization');
  if (!header?.startsWith('Bearer ')) return null;
  return header.slice('Bearer '.length);
}

// ── Seeds ───────────────────────────────────────────────────────────────────

const AGENT_RUNNING = 'agent-running-1';
const AGENT_STOPPED = 'agent-stopped-2';

function mustUser(key: string): StubUser {
  const user = USERS[key];
  if (!user) throw new Error(`Unknown e2e user ${key}`);
  return user;
}

function seedAll(): ScenarioState {
  const stamp = new Date().toISOString();
  const full = mustUser('full');
  const twofa = mustUser('2fa');
  const code = mustUser('code');
  return {
    agents: [
      {
        id: AGENT_RUNNING,
        owner_id: full.id,
        name: 'Бегущий',
        status: 'running',
        soul_prompt: 'Короткие спокойные ответы.',
        settings: { reasoning_effort: 'high' },
        last_started_at: stamp,
        last_stopped_at: null,
        created_at: stamp,
        updated_at: stamp,
      },
      {
        id: AGENT_STOPPED,
        owner_id: full.id,
        name: 'Остановленный',
        status: 'stopped',
        soul_prompt: null,
        settings: null,
        last_started_at: null,
        last_stopped_at: stamp,
        created_at: stamp,
        updated_at: stamp,
      },
    ],
    agent_onboarding_sessions: [
      {
        id: 'draft-2fa-1',
        owner_id: twofa.id,
        agent_name: 'Тест',
        soul_prompt: '0123456789性格テスト so that it passes validation',
        authorization_status: 'password_required',
        phone_number: '+79990000000',
        completed_agent_id: null,
        created_at: stamp,
        updated_at: stamp,
      },
      {
        id: 'draft-code-1',
        owner_id: code.id,
        agent_name: 'Тест',
        soul_prompt: '0123456789性格テスト so that it passes validation',
        authorization_status: 'code_requested',
        phone_number: '+79990000000',
        completed_agent_id: null,
        created_at: stamp,
        updated_at: stamp,
      },
    ],
    telegram_sessions: [
      {
        id: 'ts-running-1',
        agent_id: AGENT_RUNNING,
        phone_number: '+79990000001',
        authorization_status: 'authorized',
        last_authorized_at: stamp,
        last_error: null,
        api_id: 12345,
        created_at: stamp,
        updated_at: stamp,
      },
    ],
    message_threads: [
      {
        id: 'thread-1',
        agent_id: AGENT_RUNNING,
        telegram_peer_id: '123',
        title: 'Тестовый чат',
        metadata: null,
        last_message_at: stamp,
        created_at: stamp,
        updated_at: stamp,
      },
    ],
    agent_messages: [
      {
        id: 'msg-1',
        agent_id: AGENT_RUNNING,
        role: 'user',
        content: 'Привет',
        direction: 'incoming',
        thread_id: 'thread-1',
        created_at: stamp,
        payload: null,
      },
      {
        id: 'msg-2',
        agent_id: AGENT_RUNNING,
        role: 'assistant',
        content: 'Здравствуйте!',
        direction: 'agent_response',
        thread_id: 'thread-1',
        created_at: stamp,
        payload: null,
      },
    ],
    agent_events: [
      {
        id: 'ev-1',
        agent_id: AGENT_RUNNING,
        event_type: 'tool.send_text_message',
        status: 'succeeded',
        error: null,
        payload: { turn_id: 't-1', peer: '123' },
        result: { success: true },
        created_at: stamp,
        started_at: stamp,
        completed_at: stamp,
      },
      {
        id: 'ev-2',
        agent_id: AGENT_RUNNING,
        event_type: 'tool.get_dialogs',
        status: 'failed',
        error: 'FloodWaitError',
        payload: { turn_id: 't-2', peer: '123' },
        result: null,
        created_at: stamp,
        started_at: stamp,
        completed_at: stamp,
      },
    ],
  };
}

let state: ScenarioState = seedAll();

// ── PostgREST subset ────────────────────────────────────────────────────────

/** Postgres column defaults the app depends on (the stub has no schema). */
const TABLE_DEFAULTS: Partial<Record<TableName, Row>> = {
  agent_onboarding_sessions: {
    agent_name: null,
    soul_prompt: null,
    authorization_status: 'not_started',
    phone_number: null,
    completed_agent_id: null,
  },
};

function likeMatch(value: string, pattern: string): boolean {
  const parts = pattern.split('%');
  if (parts.length === 1) return value === pattern;
  const first = parts[0] ?? '';
  if (first && !value.startsWith(first)) return false;
  let pos = first.length;
  for (let i = 1; i < parts.length - 1; i++) {
    const part = parts[i] ?? '';
    if (!part) continue;
    const idx = value.indexOf(part, pos);
    if (idx < 0) return false;
    pos = idx + part.length;
  }
  const last = parts[parts.length - 1] ?? '';
  if (last && !value.endsWith(last)) return false;
  return true;
}

function stripQuotes(value: string): string {
  return value.length >= 2 && value.startsWith('"') && value.endsWith('"')
    ? value.slice(1, -1)
    : value;
}

function matchRow(row: Row, params: URLSearchParams): boolean {
  for (const [key, raw] of params) {
    if (key === 'select' || key === 'order' || key === 'limit' || key === 'offset') continue;
    const dot = raw.indexOf('.');
    if (dot < 0) continue;
    const op = raw.slice(0, dot);
    const operand = raw.slice(dot + 1);
    const actual = row[key];
    const actualStr = actual === null || actual === undefined ? '' : String(actual);
    switch (op) {
      case 'eq':
        if (actualStr !== operand) return false;
        break;
      case 'neq':
        if (actualStr === operand) return false;
        break;
      case 'in': {
        const list = operand.startsWith('(') && operand.endsWith(')')
          ? operand.slice(1, -1).split(',').map(stripQuotes)
          : [stripQuotes(operand)];
        if (!list.includes(actualStr)) return false;
        break;
      }
      case 'gte':
        if (actualStr < operand) return false;
        break;
      case 'lte':
        if (actualStr > operand) return false;
        break;
      case 'gt':
        if (actualStr <= operand) return false;
        break;
      case 'lt':
        if (actualStr >= operand) return false;
        break;
      case 'like':
      case 'ilike': {
        const haystack = op === 'ilike' ? actualStr.toLowerCase() : actualStr;
        const needle = op === 'ilike' ? operand.toLowerCase() : operand;
        if (!likeMatch(haystack, needle)) return false;
        break;
      }
      case 'is':
        if (operand === 'null' ? actual !== null && actual !== undefined : actualStr !== operand) {
          return false;
        }
        break;
      default:
        break;
    }
  }
  return true;
}

function sortRows(rows: Row[], orderParam: string | null): Row[] {
  if (!orderParam) return rows;
  const keys = orderParam.split(',').map((part) => {
    const [col = '', dir = 'asc'] = part.split('.');
    return { col, desc: dir === 'desc' };
  });
  return [...rows].sort((a, b) => {
    for (const { col, desc } of keys) {
      const av = a[col];
      const bv = b[col];
      const as = av === null || av === undefined ? '' : String(av);
      const bs = bv === null || bv === undefined ? '' : String(bv);
      if (as === bs) continue;
      return (as < bs ? -1 : 1) * (desc ? -1 : 1);
    }
    return 0;
  });
}

function projectRow(row: Row, select: string | null): Row {
  if (!select || select === '*') return { ...row };
  const out: Row = {};
  for (const col of select.split(',')) {
    const key = col.trim();
    if (key) out[key] = key in row ? row[key] : null;
  }
  return out;
}

function corsHeaders(req?: Request): Record<string, string> {
  // Test stub: echo any requested headers back. Localhost only, no credentials.
  const requested = req?.headers.get('access-control-request-headers');
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, PUT, DELETE, HEAD, OPTIONS',
    'Access-Control-Allow-Headers':
      requested ??
      'authorization, apikey, content-type, x-client-info, x-supabase-api-version, prefer, range, x-e2e-scenario',
    'Access-Control-Expose-Headers': 'Content-Range',
  };
}

function json(data: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return Response.json(data, {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders(), ...headers },
  });
}

function handleRest(req: Request, state: ScenarioState, table: TableName): Promise<Response> | Response {
  const url = new URL(req.url);
  const rows = state[table];
  const select = url.searchParams.get('select');

  if (req.method === 'GET' || req.method === 'HEAD') {
    const matched = sortRows(
      rows.filter((row) => matchRow(row, url.searchParams)),
      url.searchParams.get('order'),
    );
    const offset = Number(url.searchParams.get('offset') ?? '0') || 0;
    const limitRaw = url.searchParams.get('limit');
    const limit = limitRaw === null ? matched.length : Number(limitRaw) || 0;
    const page = matched.slice(offset, offset + limit);
    const total = matched.length;

    const prefer = req.headers.get('prefer') ?? '';
    const headers: Record<string, string> = {};
    if (prefer.includes('count=')) {
      const end = page.length === 0 ? '*' : String(offset + page.length - 1);
      headers['Content-Range'] = page.length === 0 ? `*/${total}` : `${offset}-${end}/${total}`;
    }
    if (req.method === 'HEAD') {
      return new Response(null, { status: 200, headers: { ...corsHeaders(), ...headers } });
    }

    const accept = req.headers.get('accept') ?? '';
    if (accept.includes('application/vnd.pgrst.object+json')) {
      if (page.length === 0) {
        return json(
          {
            code: 'PGRST116',
            message: 'JSON object requested, multiple (or no) rows returned',
            details: 'The result contains 0 rows',
            hint: null,
          },
          406,
        );
      }
      const first = page[0];
      if (!first) return json(null);
      return json(projectRow(first, select), 200, headers);
    }
    return json(page.map((row) => projectRow(row, select)), 200, headers);
  }

  if (req.method === 'POST') {
    return req.json().then((body: unknown) => {
      const incoming = (Array.isArray(body) ? body : [body]) as Row[];
      const inserted = incoming.map((row) => {
        // Mirror Postgres column defaults the app relies on.
        const fresh: Row = { ...(TABLE_DEFAULTS[table] ?? {}), ...row };
        if (fresh['id'] === undefined || fresh['id'] === null) {
          fresh['id'] = crypto.randomUUID();
        }
        rows.push(fresh);
        return projectRow(fresh, select);
      });
      return json(inserted, 201);
    }) as Promise<Response>;
  }

  if (req.method === 'PATCH') {
    return req.json().then((patch: unknown) => {
      const updated = rows
        .filter((row) => matchRow(row, url.searchParams))
        .map((row) => {
          Object.assign(row, patch as Row);
          return projectRow(row, select);
        });
      return json(updated);
    }) as Promise<Response>;
  }

  if (req.method === 'DELETE') {
    const kept = rows.filter((row) => !matchRow(row, url.searchParams));
    state[table] = kept;
    return json([]);
  }

  return json({ message: `Method ${req.method} not supported in e2e stub` }, 501);
}

// ── GoTrue subset ───────────────────────────────────────────────────────────

async function handleAuth(req: Request, pathname: string, url: URL): Promise<Response> {
  if (req.method === 'POST' && pathname === '/auth/v1/token') {
    const grant = url.searchParams.get('grant_type');
    if (grant === 'password') {
      const body = (await req.json().catch(() => ({}))) as { email?: unknown; password?: unknown };
      const user = userByEmail(body.email);
      if (user && body.password === user.password) {
        return json(sessionObject(user));
      }
      return json(
        { error: 'invalid_grant', error_description: 'Invalid login credentials' },
        400,
      );
    }
    if (grant === 'refresh_token') {
      const body = (await req.json().catch(() => ({}))) as { refresh_token?: unknown };
      const user =
        typeof body.refresh_token === 'string' ? userByToken(body.refresh_token) : null;
      if (user) return json(sessionObject(user));
      return json(
        { error: 'invalid_grant', error_description: 'Invalid refresh token' },
        400,
      );
    }
    if (grant === 'pkce') {
      return json(
        { error: 'invalid_grant', error_description: 'PKCE code exchange failed in e2e stub' },
        400,
      );
    }
    return json({ error: 'unsupported_grant_type' }, 400);
  }

  if (req.method === 'POST' && pathname === '/auth/v1/signup') {
    const body = (await req.json().catch(() => ({}))) as { email?: unknown };
    const user = userByEmail(body.email) ?? mustUser('empty');
    return json({ user: userObject(user), session: null });
  }

  if (req.method === 'POST' && pathname === '/auth/v1/recover') {
    return json({});
  }

  if (req.method === 'GET' && pathname === '/auth/v1/user') {
    const user = bearer(req) ? userByToken(bearer(req) as string) : null;
    if (user) return json(userObject(user));
    return json({ msg: 'invalid JWT: unable to parse or verify signature' }, 401);
  }

  if (req.method === 'PUT' && pathname === '/auth/v1/user') {
    const user = bearer(req) ? userByToken(bearer(req) as string) : null;
    if (user) return json({ user: userObject(user) });
    return json({ msg: 'invalid JWT: unable to parse or verify signature' }, 401);
  }

  if (pathname === '/auth/v1/logout') {
    return new Response(null, { status: 204, headers: corsHeaders() });
  }

  return json({ message: `Auth endpoint ${req.method} ${pathname} not implemented in e2e stub` }, 501);
}

// ── Server ──────────────────────────────────────────────────────────────────

Bun.serve({
  port: PORT,
  fetch(req: Request): Response | Promise<Response> {
    const url = new URL(req.url);
    const pathname = url.pathname;
    const logLine = `${req.method} ${pathname}`;
    if (process.env.E2E_STUB_LOG === '1' && !pathname.startsWith('/__')) {
      // eslint-disable-next-line no-console
      console.log(`[stub] ${logLine}${url.search.slice(0, 160)}`);
    }
    const logged = async (res: Response | Promise<Response>): Promise<Response> => {
      const out = await res;
      if (process.env.E2E_STUB_LOG === '1' && !pathname.startsWith('/__')) {
        // eslint-disable-next-line no-console
        console.log(`[stub] <- ${out.status} ${logLine}`);
      }
      return out;
    };
    return logged(handleFetch(req));
  },
});

function handleFetch(req: Request): Response | Promise<Response> {
  const url = new URL(req.url);
  const pathname = url.pathname;

  if (req.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders(req) });
  }

  if (req.method === 'GET' && pathname === '/__health__') {
    return json({ ok: true });
  }

  if (req.method === 'POST' && pathname === '/__reset__') {
    state = seedAll();
    return json({ ok: true });
  }

  if (req.method === 'PATCH' && pathname === '/__row__') {
    return req.json().then((body: unknown) => {
      const { table, id, patch } = (body as { table?: unknown; id?: unknown; patch?: unknown }) ?? {};
      if (
        typeof table !== 'string' ||
        !TABLES.includes(table as TableName) ||
        typeof id !== 'string' ||
        typeof patch !== 'object' ||
        patch === null
      ) {
        return json({ message: 'expected {table, id, patch}' }, 400);
      }
      const rows = state[table as TableName];
      const row = rows.find((candidate) => candidate['id'] === id);
      if (!row) return json({ message: 'row not found' }, 404);
      Object.assign(row, patch as Row);
      return json({ ok: true });
    }) as Promise<Response>;
  }

  if (pathname === '/realtime/v1/websocket' || pathname.startsWith('/realtime/')) {
    // Realtime is out of scope for e2e: refuse the socket so the UI
    // deterministically renders its OFFLINE state.
    return new Response('realtime disabled in e2e stub', { status: 404 });
  }

  if (pathname.startsWith('/auth/v1/')) {
    return handleAuth(req, pathname, url);
  }

  if (pathname.startsWith('/rest/v1/')) {
    const table = pathname.slice('/rest/v1/'.length).split('/')[0] as TableName;
    if (!TABLES.includes(table)) {
      return json({ message: `Unknown table ${table} in e2e stub` }, 404);
    }
    return handleRest(req, state, table);
  }

  return json({ message: `Not implemented in e2e stub: ${req.method} ${pathname}` }, 501);
}

// eslint-disable-next-line no-console
console.log(`[e2e-stub] listening on http://127.0.0.1:${PORT}`);
