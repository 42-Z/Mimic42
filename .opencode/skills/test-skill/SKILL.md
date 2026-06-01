---
name: test-skill
description: Use ONLY when writing, running, or debugging tests for Mimic42. Covers pytest, async tests, frontend vitest/playwright, test database setup, mocking Telethon/LangChain/Supabase, and CI test commands.
---

# Testing Guidelines — Mimic42

## Backend Tests (pytest)

### Running
```bash
cd /home/sasha42/Mimic42-main
uv run pytest
# Specific file
uv run pytest tests/test_agent_runtime.py
# With coverage
uv run pytest --cov=src/mimic42 --cov-report=html
```

### Async Tests
```python
import pytest

@pytest.mark.asyncio
async def test_agent_start():
    runtime = MockMimicAgentRuntime()
    await runtime.start()
    assert runtime.state == AgentRuntimeState.RUNNING
```

### Test Database
- Use `create_async_engine("sqlite+aiosqlite:///:memory:")` for unit tests
- Use migration-dropped test Supabase project for integration tests
- Never run tests against production database

### Mocking External Services
```python
from unittest.mock import AsyncMock, MagicMock

# Mock Telegram client
telegram_client = AsyncMock()
telegram_client.is_user_authorized.return_value = True

# Mock LangChain agent
langchain_agent = AsyncMock()
langchain_agent.ainvoke.return_value = {"messages": [AIMessage("hello")]}
```

## Frontend Tests

### Unit Tests (Vitest)
```bash
cd /home/sasha42/Mimic42-main/frontend
bun test
# Watch mode
bun test --watch
# UI mode
bun run test:ui
```

### Component Test Example
```tsx
import { render, screen } from '@testing-library/react'
import { AgentStatusBadge } from '@/components/agents/AgentStatusBadge'

test('shows running status', () => {
  render(<AgentStatusBadge state="running" />)
  expect(screen.getByText('АКТИВЕН')).toBeInTheDocument()
})
```

### E2E Tests (Playwright)
```bash
# Install browsers
npx playwright install
# Run E2E
bun run test:e2e
# Debug mode
npx playwright test --debug
```

### E2E Test Patterns
```ts
// Login helper
async function login(page: Page, email: string, password: string) {
  await page.goto('/login')
  await page.fill('[name=email]', email)
  await page.fill('[name=password]', password)
  await page.click('button[type=submit]')
  await page.waitForURL('/dashboard')
}

// Test onboarding flow
test('user can create agent', async ({ page }) => {
  await login(page, 'test@example.com', 'password')
  await page.click('text=Новый агент')
  await page.fill('[name=api_id]', '12345')
  // ...
})
```

## Test Data

### Fixtures (backend)
```python
@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        yield session
```

### Mock Supabase (frontend)
```ts
const mockSupabase = {
  auth: { getSession: vi.fn().mockResolvedValue({ data: { session: { access_token: 'mock' } } }) },
  from: vi.fn().mockReturnValue({
    select: vi.fn().mockReturnThis(),
    eq: vi.fn().mockReturnThis(),
    order: vi.fn().mockResolvedValue({ data: [], error: null }),
  }),
}
```

## CI/CD Testing

### Pre-commit checks
```bash
# Backend
uv run ruff check src/mimic42
uv run ruff format --check src/mimic42
uv run pytest

# Frontend
cd frontend && bun run typecheck
bun run lint
bun run test
```

## Testing Checklist

- [ ] New backend code has unit tests
- [ ] New frontend components have render tests
- [ ] Critical user paths have E2E tests
- [ ] Async code uses `pytest-asyncio` (backend) or `waitFor` (frontend)
- [ ] External API calls are mocked
- [ ] Database state is cleaned between tests
- [ ] Tests pass in CI before merge
