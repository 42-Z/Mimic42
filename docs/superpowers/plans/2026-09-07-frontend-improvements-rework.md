# Frontend-Improvements Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebase `feat/frontend-improvements` onto current `origin/main`, remove junk, verify backend+frontend, push result without opening a PR.

**Architecture:** Rebase (not merge) keeps history linear; junk removal via `git rm`; verification via repo's own commands (`pytest`/`ruff`/`ty` backend, `next build`/`tsc`/`vitest` frontend). Commits are selective — `AGENTS.md` working-tree change is UNTOUCHABLE (stays local, never committed, never pushed).

**Tech Stack:** Python 3.13 + FastAPI + SQLAlchemy (uv, ruff, ty, pytest), Next.js + TypeScript (bun, vitest), Supabase Postgres.

---

## File Structure

Modify (via rebase conflict resolution, only if conflicted):
- `BASE_SYSTEM_PROMPT.txt` — message-id awareness (main) vs branch version
- `src/mimic42/api/app.py` — conversation endpoint + pagination vs main's trigger/security changes
- `src/mimic42/core/agent_runtime.py` — raw_text/roles vs message-id + discussion tools
- `src/mimic42/core/agent_store.py`, `src/mimic42/core/memory.py`, `src/mimic42/core/onboarding.py`
- `src/mimic42/integrations/database_agent_store.py`, `database_memory.py`, `database_onboarding.py`, `telegram_tools.py`
- `frontend/src/app/(dashboard)/agent/[id]/page.tsx`, `dashboard/page.tsx`, `layout.tsx`, `onboarding/page.tsx`, `app/layout.tsx`
- `frontend/src/components/layout/Header.tsx`, `Sidebar.tsx`, `frontend/src/hooks/*`, `frontend/src/lib/api.ts`, `queryClient.ts`, `frontend/src/types/index.ts`, `frontend/package.json`, `frontend/bun.lock`, `.gitignore`
- `tests/core/test_agent_runtime.py`, `tests/core/test_memory.py`, `tests/integrations/test_telegram_tools.py`

Delete:
- `frontend/test_logs.js` — hardcoded localhost + uuid Playwright scratch script
- `skills-lock.json` — local skills lockfile, not project code
- `.agents/` (48 files) — downloaded skill docs, verify first that no project-owned file hides there

Keep (branch's real work):
- `frontend/src/components/chat/ChatBubble.tsx`, `ConversationThread.tsx`, `TabLogsChat.tsx`
- `frontend/src/hooks/useConversation.ts`, `frontend/src/lib/toolLabels.ts`
- `supabase/migrations/20260601161000_allow_multiple_onboarding_sessions.sql`
- `supabase/migrations/20260601190000_remove_agent_messages_content_not_blank.sql`

Never touch / never commit:
- `AGENTS.md` — local-only change, must survive as uncommitted `M`

---

### Task 1: Checkout branch, preserve AGENTS.md

**Files:** none modified (working tree state only)

- [ ] **Step 1: Confirm preconditions on main**

```bash
git branch --show-current && git status -sb && git rev-parse HEAD && git rev-parse feat/frontend-improvements origin/feat/frontend-improvements
```

Expected: on `main`, `M AGENTS.md` is the ONLY change, HEAD `1265ef0`, both branch refs `27ef6d2` (local == remote, safe to rebase).

- [ ] **Step 2: Checkout the branch**

```bash
git checkout feat/frontend-improvements && git status -sb | head -5
```

Expected: `M AGENTS.md` carried over cleanly (branch never touched `AGENTS.md`, verified via empty `git diff main...branch -- AGENTS.md`).

- [ ] **Step 3: Record rollback point**

```bash
git rev-parse HEAD > /tmp/opencode/feat-impr-base.sha && cat /tmp/opencode/feat-impr-base.sha
```

Expected: prints `27ef6d2...`. If rebase goes bad later: `git rebase --abort`, or hard reset to this SHA (working tree AGENTS.md change must be stashed first — see Task 2 fallback).

---

### Task 2: Rebase onto origin/main

**Files:** conflict resolution only in files listed under "Modify" above.

- [ ] **Step 1: Fetch and start rebase**

```bash
git fetch origin && git rebase origin/main
```

Expected: either clean finish, or `CONFLICT` listing. Do NOT `git add -A` at any point.

- [ ] **Step 2: If conflicted — resolve each file, keeping BOTH sides**

```bash
git status -sb | grep '^UU'
```

For every `UU` file: open it, keep main's additions (message-id awareness, channel-discussion tools, `raw_user_text` handling) AND branch's additions (conversation endpoint, role normalization, toolLabels wiring). Never delete a hunk you don't understand — read both versions first. Then:

```bash
git add <resolved-file> && git rebase --continue
```

Repeat until `git status` shows `nothing to commit, working tree clean` (plus the pre-existing `M AGENTS.md`).

- [ ] **Step 3: Fallback — abort only if rebase is unrecoverable**

```bash
git rebase --abort && git rev-parse HEAD
```

Expected: HEAD back at SHA from Task 1 Step 3. STOP and report to user (fallback would be `git merge origin/main` instead — user's joint decision, do not merge unilaterally).

---

### Task 3: Remove junk files

**Files:**
- Delete: `frontend/test_logs.js`, `skills-lock.json`, `.agents/` (whole dir)

- [ ] **Step 1: Verify .agents contains no project-owned files**

```bash
git diff --name-only main...HEAD -- .agents | grep -v '^.agents/skills/' || echo "ONLY-SKILLS-DOCS"
```

Expected: `ONLY-SKILLS-DOCS` (only downloaded skill docs). If anything else shows up, STOP and report.

- [ ] **Step 2: Delete junk and amend into cleanup commit**

```bash
git rm -q frontend/test_logs.js skills-lock.json && git rm -rq .agents && git status -sb | head -10
```

Expected: deletions staged (`D` entries), nothing else staged.

- [ ] **Step 3: Check bun.lock / package.json churn is real**

```bash
git diff main...HEAD --stat -- frontend/bun.lock frontend/package.json
```

If `bun.lock` diff is pure version-noise from `bun install` (thousands of lines, no new deps in `package.json`), revert it: `git checkout main -- frontend/bun.lock`. If `package.json` gained real deps (vitest, playwright, etc.), keep it.

- [ ] **Step 4: Commit the cleanup**

```bash
git commit -m "chore(frontend-improvements): drop local scratch files (test_logs, skills-lock, .agents)"
```

Expected: commit created. Verify `AGENTS.md` NOT in it: `git show --name-only HEAD | grep AGENTS.md || echo "AGENTS-CLEAN"`.

---

### Task 4: Backend verification (uv, ruff, ty, pytest)

**Files:** read-only unless tests fail (then fix per systematic-debugging, never AGENTS.md).

- [ ] **Step 1: Run backend suite**

```bash
uv run pytest 2>&1 | tail -5
```

Expected: all green. If red — STOP, diagnose root cause from logs before any fix (systematic-debugging).

- [ ] **Step 2: Lint and types**

```bash
uv run ruff check . && uv run ty check
```

Expected: no errors. Fix only code issues in branch files.

---

### Task 5: Add missing backend tests (conversation endpoint)

**Files:**
- Modify: `tests/api/test_dashboard_api.py` (check exact filename exists first with `ls tests/api/`)

- [ ] **Step 1: Confirm current coverage gap**

```bash
grep -rn "conversation" tests/ | head -5 || echo "NO-CONVERSATION-TESTS"
```

Expected: `NO-CONVERSATION-TESTS` (branch added endpoint with ~zero tests).

- [ ] **Step 2: Write failing test for GET conversation**

Add to the dashboard api test file a test that calls `GET /api/v1/agents/{id}/conversation` with auth and asserts `200` + list shape. Run it:

```bash
uv run pytest tests/api/test_dashboard_api.py -v 2>&1 | tail -5
```

Expected: FAIL (proves the test exercises real code; if it passes immediately, strengthen assertions until it can fail for the wrong shape, then confirm pass on correct code).

- [ ] **Step 3: Commit test**

```bash
git add tests/api/test_dashboard_api.py && git commit -m "test(api): cover GET conversation endpoint"
```

---

### Task 6: Frontend verification (bun, tsc, vitest, build)

**Files:** read-only unless failures point at branch code.

- [ ] **Step 1: Install and typecheck**

```bash
bun install && bun run typecheck
```

Expected: `tsc --noEmit` clean.

- [ ] **Step 2: Unit tests and lint**

```bash
bun run test && bun run lint
```

Expected: `vitest run` green, lint clean.

- [ ] **Step 3: Production build**

```bash
bun run build 2>&1 | tail -5
```

Expected: `next build` succeeds.

---

### Task 7: Push, no PR, final report

- [ ] **Step 1: Final pre-push check**

```bash
git log --oneline origin/main..HEAD | wc -l && git show --name-only HEAD | grep AGENTS.md || echo "AGENTS-CLEAN" && git status -sb | head -5
```

Expected: commit count printed, `AGENTS-CLEAN`, working tree shows ONLY `M AGENTS.md`.

- [ ] **Step 2: Push with lease**

```bash
git push --force-with-lease origin feat/frontend-improvements
```

Expected: push accepted. If rejected (teammate pushed meanwhile) — STOP, report, do not force.

- [ ] **Step 3: Report, do NOT open PR**

Post the verification summary (pytest/ruff/ty/vitest/build results, commit list). PR is a joint decision — explicitly leave it to the user.

---

## Self-Review

1. **Spec coverage:** rebase (Tasks 1-2) ✓, junk removal (Task 3) ✓, backend verify (Task 4) ✓, tests gap (Task 5) ✓, frontend verify (Task 6) ✓, push-no-PR (Task 7) ✓, AGENTS.md protection (Tasks 1/3/7) ✓, shared-branch safety (lease + stop-on-reject) ✓.
2. **Placeholder scan:** all steps have exact commands, paths, expected outputs. No TBD/TODO. Task 5 Step 2 adapts to actual test file layout via `ls` first — acceptable, not a placeholder.
3. **Type consistency:** N/A (no new APIs defined; endpoint path `/api/v1/agents/{id}/conversation` matches existing `app.py` route from branch diff).
