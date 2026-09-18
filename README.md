# Mimic42

Async base for a Telegram userbot agent platform:

- FastAPI API for dashboard-to-agent interaction.
- `MimicAgentRuntime` combines one Telethon user session and one LangChain agent.
- `AgentManager` keeps multiple async runtimes in one event loop.
- Database access is implemented with SQLAlchemy 2.0 async ORM models and repositories.
- Onboarding API requests a Telegram login code, verifies it, stores a session string, and
  finalizes the agent profile.
- Runtime listens for incoming Telegram messages and replies through the LangChain agent.
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

The current backend model is global, not per-agent: `openrouter/free`.

## Tests

```bash
uv run pytest                  # everything except the database, ~30 seconds
uv run pytest -m db            # 38 tests against the real Mimic42 Dev database, ~6 minutes
uv run pytest -m e2e           # browser e2e: test server + frontend + Playwright
cd frontend && bunx tsc --noEmit && bun test
```

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
