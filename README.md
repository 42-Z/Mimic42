# Mimic42

Async base for a Telegram userbot agent platform:

- FastAPI API for dashboard-to-agent interaction.
- `MimicAgentRuntime` combines one Telethon user session and one LangChain agent.
- `AgentManager` keeps multiple async runtimes in one event loop.
- Database access is implemented with SQLAlchemy 2.0 async ORM models and repositories.
- Onboarding API requests a Telegram login code, verifies it, stores a session string, and
  finalizes the agent profile.
- Runtime listens for incoming Telegram messages and replies through the LangChain agent.
- Optional "first comment": a new broadcast-channel post gets an instant comment in the linked
  discussion group, picked at random from the agent's configured variants — no delay, no LLM call.
- The first Telegram tool is `set_reaction`, implemented through Telethon reactions.
- Supabase migration defines users, agents, Telegram sessions, message history, and realtime agent events.
- Short-term conversation context is loaded from Postgres for the last 3 hours and trimmed to
  65,536 estimated tokens before model calls.
- Long-term memory is stored in Mem0 through `MemoryClient`.

## Agent Onboarding Flow

Authenticated API requests must include a Supabase user access token. The backend accepts either
`Authorization: Bearer <jwt>` or a cookie named `mimic42_access_token`, `access_token`, or
`sb-access-token`. The token is verified locally through the project's Supabase JWKS endpoint; the
backend does not need the Supabase secret API key for this check.

1. `POST /api/v1/onboarding/telegram` with `phone_number` (`api_id` and `api_hash` are optional overrides for the deployment-wide Telegram application).
2. `POST /api/v1/onboarding/{id}/telegram/code` with Telegram `code` and optional `password`.
3. `POST /api/v1/onboarding/{id}/agent` with `name`, `soul_prompt`, optional `system_prompt`.
4. Dashboard controls runtime through `/api/v1/agents/{id}/start`, `/stop`, and
   `/messages/trigger`.

Dashboard data endpoints:

- `GET /api/v1/agents` lists the authenticated user's persisted agents.
- `GET /api/v1/agents/{id}/messages` returns recent message history.
- `GET /api/v1/agents/{id}/actions` returns recent agent events.

`api_hash`, `phone_code_hash`, and Telethon `StringSession` are backend secrets and must not be
sent back to the browser after the request that provides them.

## Development

```bash
uv sync --all-groups
uv run uvicorn mimic42.main:app --reload
uv run pytest
uv run ruff check .
uv run ty check
```

The API starts at `http://127.0.0.1:8000` by default.

The current `.env` names used by the backend are:

- `SUPABASE_URL` for local Supabase JWT verification.
- `DATABASE_CONNECTION_STRING` for the Supabase Postgres connection.
- `OPENROUTER_API_KEY` for model access.
- `MEM0_API_KEY` for long-term memory integration.
- `SECRET_KEY` for encrypting Telegram session strings before database storage.
- `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` for the Telegram application every agent logs in
  through. Onboarding asks the user only for a phone number; these values are the deployment-wide
  default, and requests may still override them per agent. Without them, onboarding answers
  `503`.

Generate `SECRET_KEY` with:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Each agent picks its model from the catalog in `src/mimic42/core/model_catalog.py` (mirrored in
`frontend/src/lib/models.ts`): GLM 5.3 Flash (default), DeepSeek V4 Flash, Ling 3.0 Flash VL and
Nemotron 3.5 Lightning, all through OpenRouter. A catalog model must support tool calling with a
required tool choice: the agent's structured reply is returned through a tool call, and a model
that cannot be forced to call it answers in plain text and never finishes the turn.

## Administration

The dashboard's `/admin` route is available only to profiles explicitly listed in
`public.admin_users`. Middleware still requires a valid login; the backend checks the role on each
admin API request. A profile does not need to own an agent to be an administrator. The role is
assigned manually in the database, never by a migration or from a client request.

To grant access, use the SQL editor for the intended Supabase project. First look up the target
profile and verify its email and UUID:

```sql
select id, email
from public.profiles
where email = '<confirmed-account-email>';
```

Only after confirming the returned profile, replace the placeholder with that exact UUID and insert
one role row:

```sql
insert into public.admin_users (user_id)
values ('<confirmed-profile-uuid>'::uuid)
on conflict (user_id) do nothing;
```

To revoke access, delete only that profile's role row:

```sql
delete from public.admin_users
where user_id = '<confirmed-profile-uuid>'::uuid;
```

Use a verified operator account; never substitute your own account or the first profile returned.
Keep real emails and UUIDs out of migrations, source control, and screenshots. The local dashboard
is normally `http://localhost:3000/admin`; if Next.js selects another port, use the URL printed by
its dev server.

### Telegram application credentials

The shared Telegram application pair is resolved from the saved database row first. Server
environment variables `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` are used only when no saved row
exists. A database read or decryption failure is an error, not a reason to fall back to the
environment. The HASH is encrypted with `SECRET_KEY`; keep that key available and unchanged across
API restarts and replicas. The admin form is write-only: it shows whether a HASH exists, never its
saved or encrypted value.

Changing the shared pair affects new Telegram connections that use platform defaults (including
new onboarding and rebinds); a complete per-agent override still takes precedence. Existing agent
sessions keep their current credentials and are not migrated. If the application is rolled back, do
not drop the settings or audit tables and do not delete the saved row to force an environment
fallback. Restore a previous pair by explicitly saving its known API ID and HASH in the admin form;
a saved HASH cannot be recovered from that form or from the status API.

## Tracing (Braintrust)

Agent turn tracing is off by default and enabled with a key:

```bash
BRAINTRUST_API_KEY=...        # Braintrust project key
BRAINTRUST_PROJECT=Mimic42    # Prod and Dev keep separate projects
```

With the key, every agent turn lands in Braintrust as a single trace: the root span
`turn {peer}` (incoming message, reply, `agent_id`, `turn_id`, `peer`, model) with model
calls (tokens, latency) and Telegram tools nested under it. The `turn.completed` and
`turn.failed` dashboard events carry `trace_url` — a link straight into the trace.

Without a key the tracing module is a no-op: the agent works as before and nothing is
sent anywhere. Braintrust failures never fail an agent turn.

Manual check: put `BRAINTRUST_API_KEY` into `.env`, run the agent in Dev, send it a
message and open the project in the Braintrust UI — a turn trace should appear with the
`turn {peer}`, LLM call, and tool spans.

## Tests

```bash
uv run pytest                  # everything except the layers below, ~45 seconds
uv run pytest -m db            # 62 tests against the real Mimic42 Dev database
uv run pytest -m e2e           # browser e2e: test server + frontend + Playwright
uv run pytest -m real_tg       # live Telegram: checker account talks to a real mimic, ~12 minutes
uv run pytest -m real_llm      # agent behaviour on a real model through OpenRouter, spends tokens
cd frontend && bunx tsc --noEmit && bun test
```

`real_tg` and `real_llm` never run in the regular CI job. `real_tg` has a manual workflow
(`Real Telegram Tests`); `real_llm` runs only locally. `real_llm` checks the weakest catalog model
by default; set `MIMIC_WEAK_MODEL` to another slug to check that one instead.

Live Telegram tests share one checker account and one mimic, so only one run may use them at a
time. A run takes a Postgres advisory lock in the Dev database and stops immediately if another run
already holds it; the lock is released when its connection closes, so a crashed run does not block
anyone.

Tests load `.env` and `.env.test` themselves — no `source` needed. The local `.env` points at the
**Mimic42 Dev** project; production values live only in `/etc/mimic42.env` on the server and are
never committed. The only test-specific name left is `TEST_USER_PASSWORD` (e2e login and account
bootstrap); everything else is shared with the application — see `.env.example` for both sections.

Database tests carry the `db` marker and are excluded by default: they lease a test-account slot and
purge that slot's data before running, so they only start on an explicit `-m db`. If the settings
are missing, such a run fails with an explanation instead of reporting a green no-op.

Account bootstrap reuses the application's Dev service-role key (`SUPABASE_SERVICE_ROLE_KEY` in
`.env`, the same key media storage uses) and refuses to run against anything but Dev.

```bash
uv run python scripts/test_env_bootstrap.py
```
