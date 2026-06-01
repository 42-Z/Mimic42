---
name: supabase
description: Use ONLY when working with Mimic42 database schema, Supabase migrations, PostgreSQL, RLS policies, realtime subscriptions, or the DatabaseShortTermMemory integration. Covers SQL migrations, enum types, table constraints, and the relationship between SQLAlchemy models and Supabase tables.
---

# Supabase / PostgreSQL Guidelines — Mimic42

## Connection

- **Database URL**: `postgresql+asyncpg://...` (async SQLAlchemy)
- **Supabase JS Client**: used by frontend for direct table access and realtime
- **Migrations**: raw SQL in `supabase/migrations/YYYYMMDD_HHMMSS_description.sql`

## Migration Rules

1. **Always use `IF EXISTS` / `IF NOT EXISTS`** for idempotent migrations
2. **Always include rollback** in comments if operation is destructive
3. **Name format**: `YYYYMMDD_HHMMSS_description.sql`
4. **Order matters**: migrations run sequentially by filename
5. **Test locally** with `supabase migration up` before committing

### Safe migration template
```sql
-- Forward
ALTER TABLE public.agents ADD COLUMN IF NOT EXISTS new_field text;

-- Rollback (document only, don't run automatically)
-- ALTER TABLE public.agents DROP COLUMN IF EXISTS new_field;
```

## Enum Types

Project uses PostgreSQL enums for constrained fields:

| Enum | Values | Used in |
|------|--------|---------|
| `agent_runtime_status` | draft, stopped, starting, running, stopping, error | `agents.status` |
| `telegram_authorization_status` | not_started, code_requested, password_required, authorized, revoked, error | `telegram_sessions.authorization_status` |
| `agent_message_direction` | incoming, outgoing, dashboard_trigger, agent_response, tool_call, tool_result | `agent_messages.direction` |
| `agent_event_status` | pending, running, succeeded, failed, cancelled | `agent_events.status` |

**Rule**: Never change enum values without a migration. Never insert invalid enum values.

## RLS Policies

Every table has RLS enabled. All policies follow the pattern:

```sql
-- SELECT: user can read their own data
USING (owner_id = auth.uid())

-- INSERT/UPDATE/DELETE: user can modify their own data
WITH CHECK (owner_id = auth.uid())

-- Cross-table references: use EXISTS subquery
USING (
  EXISTS (
    SELECT 1 FROM public.agents
    WHERE agents.id = table.agent_id
      AND agents.owner_id = auth.uid()
  )
)
```

**Critical tables with RLS**:
- `profiles` — auth.users mirror
- `agents` — core agent data
- `agent_onboarding_sessions` — onboarding state
- `telegram_sessions` — Telegram credentials (encrypted)
- `agent_messages` — conversation history
- `agent_events` — activity log
- `message_threads` — conversation threads

## SQLAlchemy ↔ Supabase Mapping

| SQLAlchemy Model | Supabase Table | Notes |
|------------------|----------------|-------|
| `AgentModel` | `public.agents` | `settings` is JSONB |
| `AgentOnboardingSessionModel` | `public.agent_onboarding_sessions` | `owner_id` dropped unique constraint for multi-agent |
| `TelegramSessionModel` | `public.telegram_sessions` | Secrets encrypted with Fernet |
| `AgentMessageModel` | `public.agent_messages` | `payload` is JSONB with peer, structured_response |
| `AgentEventModel` | `public.agent_events` | `actor_user_id` for dashboard actions |
| `MessageThreadModel` | `public.message_threads` | `telegram_peer_id` + `agent_id` unique |

## Realtime

Tables in `supabase_realtime` publication:
- `public.agent_messages`
- `public.agent_events`

**Frontend**: `useRealtimeFeed(agentId)` subscribes to both tables and merges with historical data.

## Common Queries

### Count messages for agent
```sql
SELECT COUNT(*) FROM agent_messages WHERE agent_id = '<uuid>';
```

### Recent messages with structured response fallback
```sql
SELECT 
  id, agent_id, peer, role, content, direction, created_at,
  COALESCE(
    NULLIF(content, ''),
    payload->'structured_response'->>'text'
  ) as display_content
FROM agent_messages
WHERE agent_id = '<uuid>'
ORDER BY created_at DESC
LIMIT 50;
```

### Failed events today
```sql
SELECT * FROM agent_events 
WHERE agent_id = '<uuid>' 
  AND status = 'failed'
  AND created_at >= CURRENT_DATE;
```

## Testing Database Changes

1. Run migration: `npx supabase migration up`
2. Verify schema in Supabase Studio → Table Editor
3. Test RLS: login as different user, verify access denied
4. Test with backend: `uv run pytest` or manual API call
5. Test with frontend: check network tab for 403/404 errors

## Security Checklist

- [ ] RLS enabled on all new tables
- [ ] Policies use `auth.uid()` not `current_user`
- [ ] No `security definer` functions without explicit reason
- [ ] Encrypted fields (`api_hash_ciphertext`, `session_ciphertext`) never exposed in API responses
- [ ] Migrations are idempotent (`IF EXISTS`)
