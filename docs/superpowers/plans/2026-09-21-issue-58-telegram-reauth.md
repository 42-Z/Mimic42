# Переавторизация Telegram-сессии агента (issue #58) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Когда Telegram-сессия агента перестала быть авторизованной, пользователь видит понятную ошибку на русском и может перепривязать аккаунт (телефон → код → 2FA) на отдельной странице, не теряя имя, характер, память и настройки агента.

**Architecture:** Рантайм при unauthorized-старте помечает `telegram_sessions.authorization_status='revoked'` — по этому статусу фронт показывает кнопку «Перепривязать». Перепривязка переиспользует существующий онбординг-сервис Telethon-логина (`send_code_request` → `sign_in(code, phone_code_hash)` → при `SessionPasswordNeededError` → `sign_in(password)`) и завершается новым методом стора `rebind_telegram_session`, который обновляет только строку `telegram_sessions`; `manager.reload_agent` пересобирает рантайм со свежей сессией. БД-миграций нет — колонки и enum-значения (`revoked`) уже существуют.

**Tech Stack:** FastAPI + SQLAlchemy (async), Telethon 1.43 (доки: https://docs.telethon.dev/en/stable/ — `AuthMethods.sign_in`: «password — 2FA password, should be used if a previous call raised SessionPasswordNeededError»; `phone_code_hash` из `send_code_request`; `StringSession.save()` хранит auth key, достаточный для логина без повторного кода), Next.js 14 + TanStack Query + Bun.

**Ветка:** `feat/issue-58-reauth` (создана). PR в `main`, описание закрывает issue #58 (`Closes #58`).

**Решения, принятые при брейншторминге:**
- Флоу перепривязки — отдельная страница `/agent/[id]/rebind` (не модал).
- После перепривязки агент остаётся остановленным (запуск — вручную).
- Фронт узнаёт о сломанной сессии по `telegram_sessions.authorization_status` (`revoked`/`error`), рантайм пишет `revoked` при неудачном старте.

---

## File Structure

| Файл | Действие | Ответственность |
|---|---|---|
| `src/mimic42/core/agent_runtime.py` | Modify | Русский текст исключения; запись `revoked` в `telegram_sessions` |
| `src/mimic42/core/onboarding.py` | Modify | Русский текст `TelegramAuthorizationIncompleteError`; метод `rebind_to_agent` |
| `src/mimic42/core/agent_store.py` | Modify | Протокол `rebind_telegram_session` + реализация InMemory |
| `src/mimic42/integrations/database_agent_store.py` | Modify | Реализация `rebind_telegram_session` на Postgres |
| `src/mimic42/api/app.py` | Modify | Русский 428-текст 2FA; хелпер ошибок Telegram-логина; эндпоинты rebind |
| `frontend/src/lib/telegram.ts` | Create | `needsRebind()` |
| `frontend/src/lib/api.ts` | Modify | `agentsApi.rebindTelegram`, `agentsApi.confirmRebind` |
| `frontend/src/hooks/useTelegramSession.ts` | Modify | `authorization_status` в `AgentDetails` |
| `frontend/src/app/(dashboard)/agent/[id]/rebind/page.tsx` | Create | Шаговый флоу перепривязки |
| `frontend/src/app/(dashboard)/dashboard/page.tsx` | Modify | Кнопка «Перепривязать» в плашке агента |
| `frontend/src/app/(dashboard)/agent/[id]/page.tsx` | Modify | Кнопка в AgentControls, TabActions, TabTelegram |
| `tests/api/fakes.py` | Modify | `FakeAgentManager(start_unauthorized=...)` |
| `tests/api/test_agents_api.py` | Modify | Тесты 428-текста и rebind-флоу |
| `tests/core/test_agent_runtime.py` | Modify | Проверка русского текста исключения |
| `tests/core/test_agent_store_rebind.py` | Create | InMemory-тесты rebind |
| `tests/core/test_onboarding_linkage.py` | Modify | Тесты `rebind_to_agent` |
| `tests/integration/test_telegram_session_status.py` | Create | DB-тест revoked-пометки |
| `tests/integration/test_database_agent_store.py` | Modify | DB-тест rebind-стора |

---

### Task 1: Русификация ошибок авторизации ✅ (коммиты `cc592e6`, `83a043e`, `4fb150d`)

**Files:**
- Modify: `src/mimic42/core/agent_runtime.py:253-255` (плюс константа `UNAUTHORIZED_SESSION_MESSAGE`)
- Modify: `src/mimic42/integrations/telethon_client.py` (текст при отсутствии session string + warning с agent_id)
- Modify: `src/mimic42/core/onboarding.py:317-320`
- Modify: `src/mimic42/api/app.py:428-432`
- Modify: `tests/api/fakes.py`
- Modify: `tests/api/test_agents_api.py`
- Modify: `tests/api/test_onboarding_api.py` (тесты 428 и 409)
- Modify: `tests/core/test_agent_runtime.py:147-158`
- Modify: `tests/integrations/test_telethon_client.py`

- [ ] **Step 1: Расширить FakeAgentManager флагом start_unauthorized**

В `tests/api/fakes.py` заменить конструктор и `start_agent`:

```python
class FakeAgentManager:
    def __init__(
        self,
        default_owner_id: UUID | None = None,
        *,
        start_unauthorized: bool = False,
    ) -> None:
        self._default_owner_id = default_owner_id
        self._start_unauthorized = start_unauthorized
        self.created: dict[UUID, FakeAgentRecord] = {}
        self.started: list[UUID] = []
        self.stopped: list[UUID] = []
        self.removed: list[UUID] = []
        self.reloaded: list[UUID] = []
        self.triggers: list[tuple[UUID, str, str]] = []

    async def start_agent(self, agent_id: UUID) -> None:
        if self._start_unauthorized:
            raise TelegramAuthorizationRequired(
                "Сессия Telegram не авторизована. Требуется повторная привязка Telegram-аккаунта."
            )
        self.started.append(agent_id)
        self.created[agent_id].state = AgentRuntimeState.RUNNING
```

Добавить импорт вверху файла:

```python
from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentRuntimeState,
    AgentStatus,
    AgentTrigger,
    AgentTriggerResult,
    TelegramAuthorizationRequired,
)
```

- [ ] **Step 2: Написать failing-тест на русский текст 428**

В `tests/api/test_agents_api.py` добавить тест (импорты уже есть в файле):

```python
@pytest.mark.asyncio
async def test_start_agent_reports_unauthorized_session_in_russian() -> None:
    manager = FakeAgentManager(start_unauthorized=True)
    owner_id = uuid4()
    app = create_app(manager=manager, auth_verifier=FakeAuthVerifier(owner_id))
    agent_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        await client.post(
            "/api/v1/agents",
            headers=AUTH_HEADERS,
            json={
                "agent_id": str(agent_id),
                "telegram_session_string": "1BQANOTEuMTA4LjUuMLB6LjE",
                "telegram_api_id": 12345,
                "telegram_api_hash": "hash",
                "soul_prompt": "Short replies",
            },
        )
        response = await client.post(
            f"/api/v1/agents/{agent_id}/start",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 428
    detail = response.json()["detail"]
    assert "не авторизована" in detail
    assert "повторная привязка" in detail
```

- [ ] **Step 3: Запустить тест, убедиться что падает**

Run: `uv run pytest tests/api/test_agents_api.py::test_start_agent_reports_unauthorized_session_in_russian -q`
Expected: FAIL — detail содержит английский текст «Telegram user session is not authorized...»

- [ ] **Step 4: Русифицировать исключение в рантайме**

В `src/mimic42/core/agent_runtime.py` заменить текст (строки 253-255):

```python
                if not await self._telegram_client.is_user_authorized():
                    logger.error("Telegram session not authorized")
                    raise TelegramAuthorizationRequired(
                        "Сессия Telegram не авторизована. "
                        "Требуется повторная привязка Telegram-аккаунта."
                    )
```

- [ ] **Step 5: Русифицировать 2FA-деталь и onboarding-ошибку**

В `src/mimic42/api/app.py` (обработчик `TelegramPasswordRequiredError` в `verify_telegram_code`):

```python
        except TelegramPasswordRequiredError as exc:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail=(
                    "Для этого аккаунта включена двухфакторная аутентификация. "
                    "Введите пароль 2FA."
                ),
            ) from exc
```

В `src/mimic42/core/onboarding.py`:

```python
class TelegramAuthorizationIncompleteError(RuntimeError):
    def __init__(self, onboarding_id: UUID) -> None:
        super().__init__("Онбординг-сессия не готова: завершите авторизацию в Telegram.")
        self.onboarding_id = onboarding_id
```

- [ ] **Step 6: Добавить проверку русского текста в core-тест рантайма**

В `tests/core/test_agent_runtime.py` заменить `test_runtime_refuses_unauthorized_userbot_session`:

```python
@pytest.mark.asyncio
async def test_runtime_refuses_unauthorized_userbot_session() -> None:
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=FakeTelegramClient(FakeTelegramAccount()),
        langchain_agent=FakeLangChainAgent(),
    )

    with pytest.raises(TelegramAuthorizationRequired, match="не авторизована"):
        await runtime.start()

    assert runtime.state is AgentRuntimeState.ERROR
```

- [ ] **Step 7: Запустить тесты, убедиться что проходят**

Run: `uv run pytest tests/api/test_agents_api.py tests/core/test_agent_runtime.py -q`
Expected: все PASS

- [ ] **Step 8: Commit**

```bash
git add src/mimic42/core/agent_runtime.py src/mimic42/core/onboarding.py src/mimic42/api/app.py tests/api/fakes.py tests/api/test_agents_api.py tests/core/test_agent_runtime.py
git commit -m "feat: report unauthorized telegram session in russian for users"
```

---

### Task 2: Рантайм помечает telegram_sessions как revoked ✅ (коммиты `5547894`, `61c824c`)

Telethon-контекст: `TelegramClient.connect()` succeeds даже для неавторизованной сессии (auth key есть), а `is_user_authorized()` возвращает `False` (https://docs.telethon.dev/en/stable/quick-references/client-reference.html, Users → is_user_authorized). Именно эту точку рантайм уже ловит — теперь она должна быть видна дэшборду.

**Files:**
- Modify: `src/mimic42/core/agent_runtime.py` (метод + вызов в `start`)
- Create: `tests/integration/test_telegram_session_status.py`

- [ ] **Step 1: Написать failing db-тест**

Создать `tests/integration/test_telegram_session_status.py` (каталог tests/integration автоматически получает маркер `db` — см. `conftest.py::pytest_collection_modifyitems`):

```python
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import MimicAgentRuntime, TelegramAuthorizationRequired
from mimic42.integrations.database_models import TelegramSessionModel
from mimic42.testing.slots import Slot
from mimic42.testing.telegram import FakeTelegramAccount

from ..core.test_agent_runtime import FakeLangChainAgent, FakeTelegramClient, make_config


async def test_unauthorized_start_marks_session_revoked(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("flow").user_id
    agent_id = uuid4()
    async with db_session_factory() as session:
        session.add(
            TelegramSessionModel(
                agent_id=agent_id,
                session_name=agent_id.hex,
                authorization_status="authorized",
            )
        )
        await session.commit()

    runtime = MimicAgentRuntime(
        config=make_config(agent_id, owner_id),
        telegram_client=FakeTelegramClient(FakeTelegramAccount()),
        langchain_agent=FakeLangChainAgent(),
        session_factory=db_session_factory,
    )

    with pytest.raises(TelegramAuthorizationRequired):
        await runtime.start()

    async with db_session_factory() as session:
        row = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
    assert row is not None
    assert row.authorization_status == "revoked"
    assert row.last_error is not None and "не авторизована" in row.last_error


async def test_authorized_start_keeps_session_status_untouched(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("flow").user_id
    agent_id = uuid4()
    async with db_session_factory() as session:
        session.add(
            TelegramSessionModel(
                agent_id=agent_id,
                session_name=agent_id.hex,
                authorization_status="authorized",
            )
        )
        await session.commit()

    runtime = MimicAgentRuntime(
        config=make_config(agent_id, owner_id),
        telegram_client=FakeTelegramClient(),
        langchain_agent=FakeLangChainAgent(),
        session_factory=db_session_factory,
    )

    await runtime.start()
    await runtime.stop()

    async with db_session_factory() as session:
        row = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
    assert row is not None
    assert row.authorization_status == "authorized"
    assert row.last_error is None
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `uv run pytest tests/integration/test_telegram_session_status.py -q -m db`
Expected: FAIL — первый тест: `authorization_status` остаётся `'authorized'`

- [ ] **Step 3: Реализовать запись revoked в рантайме**

В `src/mimic42/core/agent_runtime.py` добавить метод (после `_record_event`):

```python
    async def _mark_telegram_session_revoked(self, *, error: str) -> None:
        """Пометить telegram_sessions revoked: дэшборд предложит перепривязку.

        Ошибка записи не мешает основному исключению: статус агента и события
        фиксируются отдельно.
        """
        if self._session_factory is None:
            return
        try:
            from sqlalchemy import select

            from mimic42.integrations.database_models import TelegramSessionModel

            async with self._session_factory() as db_session:
                telegram_session = await db_session.scalar(
                    select(TelegramSessionModel).where(
                        TelegramSessionModel.agent_id == self.config.agent_id
                    )
                )
                if telegram_session is None:
                    logger.warning(
                        "No telegram_sessions row for agent %s, cannot mark revoked",
                        self.config.agent_id,
                    )
                    return
                telegram_session.authorization_status = "revoked"
                telegram_session.last_error = error
                await db_session.commit()
        except Exception:
            logger.warning("Failed to mark telegram session revoked", exc_info=True)
```

В `start()` в except-ветке (строки 259-273) добавить вызов после вычисления `reason`:

```python
            except Exception as e:
                logger.error(f"Failed to start agent {self.config.agent_id}: {e}", exc_info=True)
                self._state = AgentRuntimeState.ERROR
                reason = (
                    "unauthorized" if isinstance(e, TelegramAuthorizationRequired) else "exception"
                )
                if isinstance(e, TelegramAuthorizationRequired):
                    await self._mark_telegram_session_revoked(error=str(e))
                await self._record_event(
                    event_type="agent.start_failed",
                    status="failed",
                    payload={"reason": reason, "error_code": type(e).__name__},
                    error=str(e),
                    started_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                )
                raise
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `uv run pytest tests/integration/test_telegram_session_status.py tests/core/test_agent_runtime.py -q`
Expected: PASS (db-тесты требуют .env с тестовой базой; если их нет — см. «Проверка» в конце плана)

- [ ] **Step 5: Commit**

```bash
git add src/mimic42/core/agent_runtime.py tests/integration/test_telegram_session_status.py
git commit -m "feat(agent): mark telegram session revoked when userbot start finds it unauthorized"
```

---

### Task 3: AgentStore.rebind_telegram_session — протокол и InMemory ✅ (коммиты `e71e034`, `c3422c6`)

**Files:**
- Modify: `src/mimic42/core/agent_store.py` (Protocol + `InMemoryAgentStore`)
- Create: `tests/core/test_agent_store_rebind.py`

- [ ] **Step 1: Написать failing-тесты**

Создать `tests/core/test_agent_store_rebind.py`:

```python
from __future__ import annotations

from uuid import uuid4

import pytest

from mimic42.core.agent_store import InMemoryAgentStore
from mimic42.core.onboarding import OnboardingSession, TelegramLoginStatus


def _authorized_session(owner_id, onboarding_id, session_secret: str) -> OnboardingSession:
    return OnboardingSession(
        onboarding_id=onboarding_id,
        owner_id=owner_id,
        api_id=777,
        api_hash_secret="new-encrypted-hash",
        phone_number="+79990000001",
        authorization_status=TelegramLoginStatus.AUTHORIZED,
        session_secret=session_secret,
    )


@pytest.mark.asyncio
async def test_rebind_updates_session_and_keeps_profile() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    store = InMemoryAgentStore()
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="old-encrypted-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="old-encrypted-session",
            name="Mimic",
            soul_prompt="Soul",
        )
    )

    await store.rebind_telegram_session(
        agent_id, _authorized_session(owner_id, uuid4(), "new-encrypted-session")
    )

    config = await store.get_runtime_config(agent_id)
    assert config.telegram_api_id == 777
    assert config.telegram_api_hash == "new-encrypted-hash"
    assert config.telegram_session_string == "new-encrypted-session"
    assert config.name == "Mimic"
    assert config.soul_prompt == "Soul"


@pytest.mark.asyncio
async def test_rebind_unknown_agent_raises_key_error() -> None:
    store = InMemoryAgentStore()

    with pytest.raises(KeyError):
        await store.rebind_telegram_session(
            uuid4(), _authorized_session(uuid4(), uuid4(), "new-encrypted-session")
        )
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `uv run pytest tests/core/test_agent_store_rebind.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'rebind_telegram_session'`

- [ ] **Step 3: Добавить метод в Protocol и InMemoryAgentStore**

В `src/mimic42/core/agent_store.py` в Protocol `AgentStore` после `create_from_onboarding`:

```python
class AgentStore(Protocol):
    async def create_from_onboarding(self, session: OnboardingSession) -> AgentRecord: ...

    async def rebind_telegram_session(self, agent_id: UUID, session: OnboardingSession) -> None: ...
```

В `InMemoryAgentStore` после `create_from_onboarding`:

```python
    async def rebind_telegram_session(self, agent_id: UUID, session: OnboardingSession) -> None:
        """Заменить Telegram-сессию агента, не трогая профиль.

        Поля онбординга хранятся зашифрованными и кладутся как есть — так же,
        как их кладёт create_from_onboarding.
        """
        config = self._configs.get(agent_id)
        if config is None:
            raise KeyError(f"Agent {agent_id} does not have a runtime config")
        self._configs[agent_id] = config.model_copy(
            update={
                "telegram_api_id": session.api_id,
                "telegram_api_hash": session.api_hash_secret,
                "telegram_session_string": session.session_secret,
            }
        )
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `uv run pytest tests/core/test_agent_store_rebind.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mimic42/core/agent_store.py tests/core/test_agent_store_rebind.py
git commit -m "feat(store): rebind_telegram_session protocol and in-memory implementation"
```

---

### Task 4: DatabaseAgentStore.rebind_telegram_session ✅ (коммиты `c72fdf5`, `f6764f3`)

**Files:**
- Modify: `src/mimic42/integrations/database_agent_store.py`
- Modify: `tests/integration/test_database_agent_store.py`

- [ ] **Step 1: Написать failing db-тест**

В `tests/integration/test_database_agent_store.py` добавить (импорты `OnboardingSession`, `TelegramLoginStatus`, `uuid4`, `Slot`, `DatabaseAgentStore` уже есть):

```python
def _make_rebind_session(owner_id: UUID) -> OnboardingSession:
    return OnboardingSession(
        onboarding_id=uuid4(),
        owner_id=owner_id,
        api_id=777,
        api_hash_secret="new-encrypted-hash",
        phone_number="+79990000001",
        authorization_status=TelegramLoginStatus.AUTHORIZED,
        session_secret="new-encrypted-session",
    )


async def test_rebind_telegram_session_updates_session_and_keeps_profile(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()

    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(_make_session(owner_id, agent_id, "Mimic"))
    await store.rebind_telegram_session(agent_id, _make_rebind_session(owner_id))

    config = await store.get_runtime_config(agent_id)
    assert config.telegram_api_id == 777
    assert config.telegram_api_hash == "new-encrypted-hash"
    assert config.telegram_session_string == "new-encrypted-session"
    agents = await store.list_agents(owner_id=owner_id)
    assert [agent.name for agent in agents if agent.agent_id == agent_id] == ["Mimic"]

    async with db_session_factory() as session:
        row = await session.scalar(
            select(TelegramSessionModel).where(TelegramSessionModel.agent_id == agent_id)
        )
    assert row is not None
    assert row.authorization_status == "authorized"
    assert row.last_authorized_at is not None
    assert row.last_error is None


async def test_rebind_telegram_session_unknown_agent_raises_key_error(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    import pytest

    store = DatabaseAgentStore(db_session_factory)

    with pytest.raises(KeyError):
        await store.rebind_telegram_session(
            uuid4(), _make_rebind_session(clean_slot.persona("empty").user_id)
        )
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `uv run pytest tests/integration/test_database_agent_store.py -q -m db`
Expected: FAIL — `AttributeError: 'DatabaseAgentStore' object has no attribute 'rebind_telegram_session'`

- [ ] **Step 3: Реализовать метод**

В `src/mimic42/integrations/database_agent_store.py` после `create_from_onboarding`:

```python
    async def rebind_telegram_session(self, agent_id: UUID, session: OnboardingSession) -> None:
        """Заменить Telegram-сессию агента после перепривязки.

        Профиль (имя, характер, настройки, память) не трогается: обновляется
        только строка telegram_sessions. Строковая блокировка защищает от
        гонки с параллельным финалом онбординга того же агента.
        """
        if session.api_id is None or session.api_hash_secret is None:
            raise ValueError("Onboarding session is missing Telegram credentials")

        async with self._session_factory() as db_session:
            telegram_session = await db_session.scalar(
                select(TelegramSessionModel)
                .where(TelegramSessionModel.agent_id == agent_id)
                .with_for_update()
            )
            if telegram_session is None:
                raise KeyError(f"Agent {agent_id} does not have a telegram session")
            telegram_session.phone_number = session.phone_number
            telegram_session.api_id = session.api_id
            telegram_session.api_hash_ciphertext = session.api_hash_secret
            telegram_session.session_ciphertext = session.session_secret
            telegram_session.authorization_status = "authorized"
            telegram_session.last_authorized_at = _now()
            telegram_session.last_error = None
            await db_session.commit()
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `uv run pytest tests/integration/test_database_agent_store.py -q -m db`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mimic42/integrations/database_agent_store.py tests/integration/test_database_agent_store.py
git commit -m "feat(store): rebind telegram session rows in the database agent store"
```

---

### Task 5: Онбординг-сервис rebind_to_agent ✅ (коммиты `b46de14`, `1151305`, `dfe69e2`, `e609970`)

> **Поправка после ревью (финальный дизайн):** сниппеты ниже описывают
> промежуточные варианты. Итог:
> - `completed_agent_id` у агента уже занят строкой мастера (UNIQUE,
>   `20260519224500_agent_base.sql:82`), поэтому rebind-сессия не создаётся
>   заново, а **переиспользуется онбординг-строка самого агента**
>   (`OnboardingRepository.get_for_agent`: `id == agent_id` OR
>   `completed_agent_id == agent_id`). Для агентов без строки заводится новая
>   и сразу (одним save) помечается `completed_agent_id = agent_id` — мастер
>   онбординга никогда не видит черновиков перепривязки.
> - `AgentOnboardingService.start_rebind(agent_id, credentials)` — старт
>   перепривязки; `request_telegram_code` принимает keyword
>   `completed_agent_id` и сохраняет метку при обновлении существующей строки.
> - `rebind_to_agent(...)` **не удаляет** строку (повторная перепривязка
>   переиспользует её, confirm идемпотентен), проверяет owner → AUTHORIZED →
>   store и вызывает `rebind_telegram_session`.
> - `OnboardingRepository.delete` из промежуточного дизайна удалён.

**Files:**
- Modify: `src/mimic42/core/onboarding.py` (метод сервиса + `OnboardingRepository.delete`)
- Modify: `src/mimic42/integrations/database_onboarding.py` (`delete`)
- Modify: `tests/core/test_onboarding_linkage.py`
- Create: `tests/integration/test_rebind_flow.py`

- [ ] **Step 1: Написать failing-тесты**

В `tests/core/test_onboarding_linkage.py` добавить импорты и тесты:

```python
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.agent_store import InMemoryAgentStore
from mimic42.core.onboarding import (
    TelegramAuthorizationIncompleteError,
    # ... остальные существующие импорты остаются
)
```

```python
@pytest.mark.asyncio
async def test_rebind_to_agent_updates_store_and_marks_session_completed() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="new-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="new-session-string",
        )
    )
    store = InMemoryAgentStore()
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="old-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="old-session-string",
            name="Mimic",
            soul_prompt="Short calm replies",
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
        agent_store=store,
    )

    result = await service.rebind_to_agent(onboarding_id, agent_id)

    assert result.agent_id == agent_id
    assert result.state is AgentRuntimeState.STOPPED
    config = await store.get_runtime_config(agent_id)
    assert config.telegram_session_string == "new-session-string"
    assert config.telegram_api_hash == "new-hash"
    assert config.name == "Mimic"
    assert config.soul_prompt == "Short calm replies"
    saved = await repository.get(onboarding_id)
    assert saved.completed_agent_id == agent_id


@pytest.mark.asyncio
async def test_rebind_to_agent_requires_authorized_session() -> None:
    owner_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.CODE_REQUESTED,
        )
    )
    service = AgentOnboardingService(
        repository=repository,
        telegram_factory=_fake_telegram_factory(),
        agent_store=InMemoryAgentStore(),
    )

    with pytest.raises(TelegramAuthorizationIncompleteError):
        await service.rebind_to_agent(onboarding_id, uuid4())
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `uv run pytest tests/core/test_onboarding_linkage.py -q`
Expected: FAIL — `AttributeError: 'AgentOnboardingService' object has no attribute 'rebind_to_agent'`

- [ ] **Step 3: Реализовать метод в AgentOnboardingService**

В `src/mimic42/core/onboarding.py` после `finalize_agent`:

```python
    async def rebind_to_agent(self, onboarding_id: UUID, agent_id: UUID) -> AgentStatus:
        """Перенести авторизованную онбординг-сессию на существующего агента.

        Флоу перепривязки: Telegram-сессия обновляется, а имя, характер,
        память и настройки агента остаются прежними. completed_agent_id прячет
        использованную rebind-сессию от мастера онбординга (тот фильтрует
        черновики по is(completed_agent_id, null)).
        """
        session = await self._repository.get(onboarding_id)
        if session.authorization_status is not TelegramLoginStatus.AUTHORIZED:
            raise TelegramAuthorizationIncompleteError(onboarding_id)
        if self._agent_store is None:
            raise RuntimeError("Agent store is not configured")
        await self._agent_store.rebind_telegram_session(agent_id, session)
        session.completed_agent_id = agent_id
        await self._repository.save(session)
        return AgentStatus(
            agent_id=agent_id,
            owner_id=session.owner_id,
            state=AgentRuntimeState.STOPPED,
        )
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `uv run pytest tests/core/test_onboarding_linkage.py tests/core/test_agent_store_rebind.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mimic42/core/onboarding.py tests/core/test_onboarding_linkage.py
git commit -m "feat(onboarding): rebind an authorized session onto an existing agent"
```

---

### Task 6: API-эндпоинты перепривязки ✅ (коммиты `fa35c05`, `dfe69e2`, `e609970`)

> **Поправка после ревью:** старт перепривязки вызывает
> `onboarding_service.start_rebind(agent_id, credentials)` (переиспользует
> строку агента, см. Task 5), а не `request_telegram_code`. Оба эндпоинта
> возвращают 503 с русским detail, если `agent_store` не настроен. Confirm
> идемпотентен: строка не удаляется. ✅ (коммит `fa35c05`)

**Files:**
- Modify: `src/mimic42/api/app.py`
- Modify: `tests/api/test_agents_api.py`

- [ ] **Step 1: Написать failing-тест полного флоу**

В `tests/api/test_agents_api.py` добавить импорты и тест:

```python
from uuid import UUID, uuid4

from mimic42.core.onboarding import (
    AgentOnboardingService,
    InMemoryOnboardingRepository,
    OnboardingSession,
    TelegramLoginStatus,
)
from mimic42.config import Settings
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramAuthClientFactory
```

```python
def _seed_agent_in_store(store: InMemoryAgentStore, agent_id: UUID, owner_id: UUID) -> None:
    store._configs  # noqa: B018 — см. ниже; в тесте создаём через публичный метод
```

Убрать заготовку выше — тест использует `create_from_onboarding` напрямую:

```python
@pytest.mark.asyncio
async def test_rebind_flow_replaces_session_and_keeps_agent_profile() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    manager = FakeAgentManager()
    store = InMemoryAgentStore()
    onboarding_service = AgentOnboardingService(
        repository=InMemoryOnboardingRepository(),
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
        agent_store=store,
    )
    app = create_app(
        manager=manager,
        onboarding_service=onboarding_service,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
        settings=Settings(telegram_api_id=777, telegram_api_hash="deployment-hash"),
    )
    await store.create_from_onboarding(
        OnboardingSession(
            onboarding_id=agent_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="old-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="old-session",
            name="Mimic",
            soul_prompt="Short replies",
        )
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        start_response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind",
            headers=AUTH_HEADERS,
            json={"phone_number": "+79990000000"},
        )
        onboarding_id = UUID(start_response.json()["onboarding_id"])

        verify_response = await client.post(
            f"/api/v1/onboarding/{onboarding_id}/telegram/code",
            headers=AUTH_HEADERS,
            json={"code": "12345"},
        )

        confirm_response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind/confirm",
            headers=AUTH_HEADERS,
            json={"onboarding_id": str(onboarding_id)},
        )

    assert start_response.status_code == 201
    assert start_response.json()["authorization_status"] == "code_requested"
    assert verify_response.status_code == 200
    assert verify_response.json()["authorization_status"] == "authorized"

    assert confirm_response.status_code == 200
    assert confirm_response.json() == {
        "agent_id": str(agent_id),
        "owner_id": str(owner_id),
        "state": "stopped",
    }
    assert manager.reloaded == [agent_id]

    config = await store.get_runtime_config(agent_id)
    assert config.telegram_api_hash == "deployment-hash"
    assert config.telegram_session_string != "old-session"
    assert config.name == "Mimic"
    assert config.soul_prompt == "Short replies"


@pytest.mark.asyncio
async def test_rebind_confirm_rejects_foreign_onboarding_session() -> None:
    owner_id = uuid4()
    foreign_owner = uuid4()
    agent_id = uuid4()
    store = InMemoryAgentStore()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=foreign_owner,
            authorization_status=TelegramLoginStatus.AUTHORIZED,
        )
    )
    onboarding_service = AgentOnboardingService(
        repository=repository,
        telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
        agent_store=store,
    )
    app = create_app(
        manager=FakeAgentManager(),
        onboarding_service=onboarding_service,
        agent_store=store,
        auth_verifier=FakeAuthVerifier(owner_id),
        settings=Settings(telegram_api_id=777, telegram_api_hash="deployment-hash"),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind/confirm",
            headers=AUTH_HEADERS,
            json={"onboarding_id": str(onboarding_id)},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rebind_confirm_requires_completed_authorization() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    onboarding_id = uuid4()
    repository = InMemoryOnboardingRepository()
    await repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            authorization_status=TelegramLoginStatus.CODE_REQUESTED,
        )
    )
    app = create_app(
        manager=FakeAgentManager(),
        onboarding_service=AgentOnboardingService(
            repository=repository,
            telegram_factory=FakeTelegramAuthClientFactory(FakeTelegramAccount()),
            agent_store=InMemoryAgentStore(),
        ),
        agent_store=InMemoryAgentStore(),
        auth_verifier=FakeAuthVerifier(owner_id),
        settings=Settings(telegram_api_id=777, telegram_api_hash="deployment-hash"),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        await client.post(
            "/api/v1/agents",
            headers=AUTH_HEADERS,
            json={
                "agent_id": str(agent_id),
                "telegram_session_string": "1BQANOTEuMTA4LjUuMLB6LjE",
                "telegram_api_id": 12345,
                "telegram_api_hash": "hash",
                "soul_prompt": "Short replies",
            },
        )
        response = await client.post(
            f"/api/v1/agents/{agent_id}/telegram/rebind/confirm",
            headers=AUTH_HEADERS,
            json={"onboarding_id": str(onboarding_id)},
        )

    assert response.status_code == 409
    assert "авторизация" in response.json()["detail"].lower()
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `uv run pytest tests/api/test_agents_api.py -q`
Expected: FAIL — новые rebind-эндпоинты дают 404/405 (маршрутов нет)

- [ ] **Step 3: Вынести общую обработку ошибок Telegram-логина**

В `src/mimic42/api/app.py` добавить модели запросов рядом с `TelegramLoginRequest`:

```python
class TelegramRebindRequest(BaseModel):
    phone_number: str = Field(min_length=5)


class TelegramRebindConfirmRequest(BaseModel):
    onboarding_id: UUID
```

Добавить хелпер (после `_resolve_telegram_app`) и переписать лесенку ошибок в `request_telegram_code` на него:

```python
def _telegram_login_http_error(exc: Exception) -> HTTPException | None:
    """Перевести ошибку Telegram-логина в понятный пользователю ответ.

    Возвращает None для незнакомых исключений — эндпоинт пробрасывает их как есть.
    """
    from telethon.errors import (
        ApiIdInvalidError,
        ApiIdPublishedFloodError,
        FloodWaitError,
        PhoneNumberBannedError,
        PhoneNumberInvalidError,
        RPCError,
    )

    if isinstance(exc, ApiIdInvalidError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Telegram отклонил приложение сервера: "
                "неверная комбинация TELEGRAM_API_ID и TELEGRAM_API_HASH."
            ),
        )
    if isinstance(exc, ApiIdPublishedFloodError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Telegram заблокировал приложение сервера как опубликованное. "
                "Замените TELEGRAM_API_ID и TELEGRAM_API_HASH."
            ),
        )
    if isinstance(exc, PhoneNumberBannedError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот номер заблокирован в Telegram.",
        )
    if isinstance(exc, PhoneNumberInvalidError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Неверный формат номера телефона. "
                "Используйте международный формат (например, +79991234567)."
            ),
        )
    if isinstance(exc, FloodWaitError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Слишком много попыток. Telegram просит подождать {exc.seconds} сек.",
        )
    if isinstance(exc, RPCError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка Telegram: {exc.message}",
        )
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return None
```

В `request_telegram_code` заменить try/except на:

```python
        try:
            return await _get_onboarding_service(app).request_telegram_code(
                credentials,
                onboarding_id=payload.onboarding_id,
            )
        except OnboardingNotFoundError as exc:
            raise _onboarding_not_found(exc.onboarding_id) from exc
        except OnboardingOwnershipError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Onboarding session belongs to another user",
            ) from exc
        except Exception as exc:
            translated = _telegram_login_http_error(exc)
            if translated is not None:
                raise translated from exc
            raise exc
```

- [ ] **Step 4: Добавить эндпоинты rebind**

В `src/mimic42/api/app.py` после эндпоинта `create_agent` (перед `get_agent`):

```python
    @app.post(
        "/api/v1/agents/{agent_id}/telegram/rebind",
        response_model=OnboardingPublicStatus,
        status_code=status.HTTP_201_CREATED,
    )
    async def rebind_agent_telegram(
        agent_id: UUID,
        payload: TelegramRebindRequest,
        current_user: CurrentUserDep,
    ) -> OnboardingPublicStatus:
        """Начать перепривязку: запросить код Telegram для существующего агента.

        Онбординг-сессия создаётся новая: код/2FA идут по стандартным
        onboarding-эндпоинтам, а на confirm сессия переносится на агента.
        """
        await _ensure_runtime_owner(app, agent_id=agent_id, user_id=current_user.user_id)
        api_id, api_hash = _resolve_telegram_app(app_settings, None, None)
        credentials = TelegramCredentials(
            owner_id=current_user.user_id,
            api_id=api_id,
            api_hash=api_hash,
            phone_number=payload.phone_number,
        )
        try:
            return await _get_onboarding_service(app).request_telegram_code(credentials)
        except Exception as exc:
            translated = _telegram_login_http_error(exc)
            if translated is not None:
                raise translated from exc
            raise exc

    @app.post(
        "/api/v1/agents/{agent_id}/telegram/rebind/confirm",
        response_model=AgentStatus,
    )
    async def confirm_agent_telegram_rebind(
        agent_id: UUID,
        payload: TelegramRebindConfirmRequest,
        current_user: CurrentUserDep,
    ) -> AgentStatus:
        """Завершить перепривязку: применить новую сессию к существующему агенту.

        Имя, характер, память и настройки не меняются. Рантайм пересобирается
        из свежего конфига: старый держал сломанную сессию в памяти.
        """
        try:
            await _ensure_runtime_owner(app, agent_id=agent_id, user_id=current_user.user_id)
        except AgentNotFoundError as exc:
            raise _not_found(exc.agent_id) from exc
        try:
            status_result = await _get_onboarding_service(app).get_status(payload.onboarding_id)
        except OnboardingNotFoundError as exc:
            raise _onboarding_not_found(payload.onboarding_id) from exc
        # Единый 404 — не раскрываем существование чужой сессии.
        try:
            _ensure_owner(status_result.owner_id, current_user.user_id)
        except HTTPException:
            raise _onboarding_not_found(payload.onboarding_id) from None
        try:
            result = await _get_onboarding_service(app).rebind_to_agent(
                payload.onboarding_id,
                agent_id,
                owner_id=current_user.user_id,
            )
        except OnboardingOwnershipError as exc:
            raise _onboarding_not_found(payload.onboarding_id) from exc
        except TelegramAuthorizationIncompleteError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Авторизация Telegram не завершена. Введите код подтверждения.",
            ) from exc
        manager = _get_agent_manager(app)
        # Останавливаем до пересборки: reload_agent перезапускает RUNNING-агента,
        # а по решению из issue агент остаётся остановленным.
        try:
            await manager.stop_agent(agent_id)
        except Exception:
            logger.exception("Failed to stop agent %s before rebind reload", agent_id)
        try:
            await manager.reload_agent(agent_id)
        except Exception:
            # Перепривязка уже применена в базе; reload_agent вынимает старый
            # рантайм из реестра до close, так что следующий start соберётся
            # из свежего конфига.
            logger.exception("Failed to reload agent %s after rebind", agent_id)
        return result
```

- [ ] **Step 5: Запустить тесты, убедиться что проходят**

Run: `uv run pytest tests/api -q`
Expected: PASS (включая существующие onboarding-тесты — поведение ошибок не изменилось)

- [ ] **Step 6: Commit**

```bash
git add src/mimic42/api/app.py tests/api/test_agents_api.py
git commit -m "feat(api): rebind endpoints to replace an agent's telegram session"
```

---

### Task 7: Фронт — API-клиент, хук деталей, needsRebind ✅ (коммиты `b3fae28`, `3b32049`)

**Files:**
- Create: `frontend/src/lib/telegram.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/hooks/useTelegramSession.ts`

- [ ] **Step 1: Создать lib/telegram.ts**

```ts
import type { TelegramAuthorizationStatus } from '@/types';

/** Сессия недействительна: Telegram отозвал её или при старте случилась ошибка. */
export function needsRebind(status: TelegramAuthorizationStatus | null | undefined): boolean {
  return status === 'revoked' || status === 'error';
}
```

- [ ] **Step 2: Добавить методы в agentsApi**

В `frontend/src/lib/api.ts` внутри `agentsApi` после `reload`:

```ts
  /** POST /api/v1/agents/:id/telegram/rebind — запросить код для перепривязки */
  rebindTelegram: (id: string, body: { phone_number: string }) =>
    apiClient
      .post<OnboardingPublicStatus>(`/agents/${id}/telegram/rebind`, body)
      .then((r) => r.data),

  /** POST /api/v1/agents/:id/telegram/rebind/confirm — применить новую сессию */
  confirmRebind: (id: string, body: { onboarding_id: string }) =>
    apiClient
      .post<AgentStatus>(`/agents/${id}/telegram/rebind/confirm`, body)
      .then((r) => r.data),
```

- [ ] **Step 3: Расширить AgentDetails статусом сессии**

В `frontend/src/hooks/useTelegramSession.ts` заменить интерфейс и запрос:

```ts
export interface AgentDetails {
  phone_number: string | null;
  authorization_status: TelegramAuthorizationStatus | null;
  last_started_at: string | null;
}
```

В `useAgentsDetails` заменить select сессий и сборку:

```ts
        supabase
          .from('telegram_sessions')
          .select('agent_id, phone_number, authorization_status')
          .in('agent_id', agentIds),
```

```ts
      for (const row of sessionsResult.data ?? []) {
        details[row.agent_id] = {
          ...(details[row.agent_id] ?? { last_started_at: null }),
          phone_number: row.phone_number ?? null,
          authorization_status: row.authorization_status ?? null,
        };
      }
```

Также при инициализации `details` из агентов добавить явный null:

```ts
      for (const row of agentsResult.data ?? []) {
        details[row.id] = {
          phone_number: null,
          authorization_status: null,
          last_started_at: row.last_started_at ?? null,
        };
      }
```

- [ ] **Step 4: Проверить типы**

Run (в каталоге `frontend`): `bun run typecheck`
Expected: без ошибок

- [ ] **Step 5: Пробрасывать русский detail для 428 и 409**

Код-ревью Task 1 нашёл: интерцептор `frontend/src/lib/api.ts:83-84` жёстко подменяет `detail` на «Требуется 2FA пароль.» — локализованные тексты не доходят до пользователя. Также 409 («Конфликт: ресурс уже существует.») скрывает русский detail rebind-конфликта. Заменить кейсы 409/428:

```ts
      case 409:
        message = (typeof detail === 'string' && detail) || 'Конфликт: ресурс уже существует.';
        break;
      case 422:
        message = formatValidationError(detail);
        break;
      case 428:
        message = (typeof detail === 'string' && detail) || 'Требуется 2FA пароль.';
        break;
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/telegram.ts frontend/src/lib/api.ts frontend/src/hooks/useTelegramSession.ts
git commit -m "feat(frontend): rebind api methods and session status in agent details"
```

---

### Task 8: Фронт — страница перепривязки /agent/[id]/rebind

**Files:**
- Create: `frontend/src/app/(dashboard)/agent/[id]/rebind/page.tsx`

- [ ] **Step 1: Создать страницу**

```tsx
'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { agentIdSchema } from '@/lib/validators';
import { useTelegramSession } from '@/hooks/useTelegramSession';
import { agentsApi, onboardingApi } from '@/lib/api';
import { queryKeys } from '@/lib/queryClient';
import { needsRebind } from '@/lib/telegram';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, Spinner } from '@/components/ui/card';
import { useToast } from '@/components/ui/toast';
import { maskPhoneNumber } from '@/lib/sanitize';
import {
  telegramCredentialsSchema,
  telegramCodeSchema,
  telegram2FASchema,
} from '@/lib/validators';
import type { ApiError } from '@/types';
import { Bot, CheckCircle2, Link2, MessageSquare, ShieldCheck } from 'lucide-react';
import Link from 'next/link';

type RebindStep = 'phone' | 'code' | '2fa' | 'done';

export default function RebindPage() {
  const params = useParams();
  const rawId = params['id'] as string;
  const parsed = agentIdSchema.safeParse(rawId);
  if (!parsed.success) {
    return <div className="p-8 font-mono text-crimson-400">Недопустимый ID агента</div>;
  }
  return <RebindPageContent agentId={parsed.data} />;
}

function RebindPageContent({ agentId }: { agentId: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data: session, isLoading } = useTelegramSession(agentId);

  const [step, setStep] = useState<RebindStep>('phone');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [onboardingId, setOnboardingId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [isPending, setIsPending] = useState(false);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: queryKeys.telegram.byAgent(agentId) });
    qc.invalidateQueries({ queryKey: queryKeys.agents.lists() });
    qc.invalidateQueries({ queryKey: queryKeys.agents.detail(agentId) });
  };

  const handlePhone = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = telegramCredentialsSchema.safeParse({ phone_number: phoneNumber });
    if (!result.success) {
      setError(result.error.issues[0]?.message ?? 'Ошибка');
      return;
    }
    setError('');
    setIsPending(true);
    try {
      const status = await agentsApi.rebindTelegram(agentId, {
        phone_number: result.data.phone_number,
      });
      setOnboardingId(status.onboarding_id);
      setStep('code');
    } catch (err: unknown) {
      toast((err as ApiError).message ?? 'Не удалось отправить код', 'error');
      setError((err as ApiError).message ?? '');
    } finally {
      setIsPending(false);
    }
  };

  const handleCode = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = telegramCodeSchema.safeParse({ code });
    if (!result.success) {
      setError(result.error.issues[0]?.message ?? 'Ошибка');
      return;
    }
    if (!onboardingId) { toast('Сессия перепривязки не найдена', 'error'); return; }
    setError('');
    setIsPending(true);
    try {
      const status = await onboardingApi.submitCode(onboardingId, { code });
      if (status.authorization_status === 'authorized') {
        await finishRebind();
        return;
      }
      setStep('2fa');
    } catch (err: unknown) {
      const apiError = err as ApiError;
      if (apiError.status === 428) {
        setStep('2fa');
      } else {
        setError(apiError.message ?? 'Неверный код');
        toast(apiError.message ?? 'Неверный код', 'error');
      }
    } finally {
      setIsPending(false);
    }
  };

  const handle2FA = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = telegram2FASchema.safeParse({ password });
    if (!result.success) {
      setError(result.error.issues[0]?.message ?? 'Ошибка');
      return;
    }
    if (!onboardingId) { toast('Сессия перепривязки не найдена', 'error'); return; }
    setError('');
    setIsPending(true);
    try {
      await onboardingApi.submitCode(onboardingId, { code, password: result.data.password });
      await finishRebind();
    } catch (err: unknown) {
      setError((err as ApiError).message ?? 'Неверный пароль 2FA');
      toast((err as ApiError).message ?? 'Неверный пароль 2FA', 'error');
    } finally {
      setIsPending(false);
    }
  };

  const finishRebind = async () => {
    if (!onboardingId) return;
    try {
      await agentsApi.confirmRebind(agentId, { onboarding_id: onboardingId });
      invalidate();
      setStep('done');
    } catch (err: unknown) {
      toast((err as ApiError).message ?? 'Не удалось завершить перепривязку', 'error');
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="max-w-xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center gap-4">
        <div className="h-10 w-10 rounded-sm bg-plasma-950 border border-plasma-800 flex items-center justify-center">
          <Link2 className="h-5 w-5 text-plasma-400" />
        </div>
        <div>
          <h1 className="font-display text-xl font-bold text-void-100">Перепривязка Telegram</h1>
          <p className="font-mono text-xs text-void-500 mt-0.5">
            Сессия недействительна — введите код заново. Имя, память и настройки сохранятся.
          </p>
        </div>
      </div>

      {!needsRebind(session?.authorization_status) && session && (
        <Card variant="glass" padding="md" className="border-neon-900">
          <p className="font-mono text-xs text-neon-400">
            Сессия уже авторизована. Перепривязка не требуется — можно запустить агента.
          </p>
        </Card>
      )}

      {step === 'phone' && (
        <form onSubmit={handlePhone} className="space-y-6">
          <StepBadge step="1" label="Номер телефона" icon={Bot} />
          <Input
            label="Номер телефона"
            type="tel"
            placeholder="+79991234567"
            value={phoneNumber}
            onChange={(e) => setPhoneNumber(e.target.value)}
            error={error}
            hint={session?.phone_number ? `Текущий номер: ${maskPhoneNumber(session.phone_number)}` : 'В формате E.164 с кодом страны'}
            autoFocus
          />
          <Button type="submit" isLoading={isPending} size="lg" className="w-full">
            Получить код →
          </Button>
        </form>
      )}

      {step === 'code' && (
        <form onSubmit={handleCode} className="space-y-6">
          <StepBadge step="2" label="Код из Telegram" icon={MessageSquare} />
          <Input
            label="Код подтверждения"
            type="text"
            inputMode="numeric"
            placeholder="12345"
            maxLength={8}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
            error={error}
            autoFocus
            className="text-center text-xl tracking-[0.5em]"
          />
          <Button type="submit" isLoading={isPending} size="lg" className="w-full">
            Подтвердить →
          </Button>
        </form>
      )}

      {step === '2fa' && (
        <form onSubmit={handle2FA} className="space-y-6">
          <StepBadge step="3" label="Пароль 2FA" icon={ShieldCheck} />
          <div className="p-4 rounded-sm bg-amber-950/20 border border-amber-900/50">
            <p className="font-mono text-xs text-amber-400">
              Это пароль 2FA от Telegram, а не от вашего устройства
            </p>
          </div>
          <Input
            label="Пароль 2FA"
            type="password"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={error}
            autoFocus
          />
          <Button type="submit" isLoading={isPending} size="lg" className="w-full">
            Подтвердить →
          </Button>
        </form>
      )}

      {step === 'done' && (
        <Card variant="glass" padding="lg" className="space-y-4 text-center">
          <CheckCircle2 className="h-12 w-12 text-neon-400 mx-auto" />
          <h2 className="font-display text-lg font-bold text-void-100">Telegram перепривязан</h2>
          <p className="font-mono text-sm text-void-500">
            Агент пока остановлен — запустите его на странице агента.
          </p>
          <Button onClick={() => router.push(`/agent/${agentId}`)} size="lg" className="w-full">
            К агенту →
          </Button>
        </Card>
      )}

      <div className="text-center">
        <Link
          href={`/agent/${agentId}`}
          className="font-mono text-xs text-void-500 hover:text-void-200 transition-colors"
        >
          ← Вернуться к агенту
        </Link>
      </div>
    </div>
  );
}

function StepBadge({
  step,
  label,
  icon: Icon,
}: {
  step: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="h-8 w-8 rounded-sm bg-plasma-950 border border-plasma-800 flex items-center justify-center">
        <Icon className="h-4 w-4 text-plasma-400" />
      </div>
      <div className="font-mono text-xs text-plasma-500 uppercase tracking-widest">
        Шаг {step} — {label}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Проверить типы и линт**

Run (в каталоге `frontend`): `bun run typecheck && bun run lint`
Expected: без ошибок

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/(dashboard)/agent/[id]/rebind/page.tsx"
git commit -m "feat(frontend): rebind wizard page for expired telegram sessions"
```

---

### Task 9: Фронт — кнопка «Перепривязать» в UI агента ✅ (коммиты `cf27727`, `7ef9ad4`, `461bb6b`)

**Files:**
- Modify: `frontend/src/app/(dashboard)/dashboard/page.tsx`
- Modify: `frontend/src/app/(dashboard)/agent/[id]/page.tsx`

- [ ] **Step 1: Кнопка в плашке агента на дашборде**

В `frontend/src/app/(dashboard)/dashboard/page.tsx` в `AgentCard`:

1) Добавить импорты:

```tsx
import { needsRebind } from '@/lib/telegram';
```

в список импортов lucide-react добавить `Link2`:

```tsx
import {
  MessageSquare, Activity, AlertTriangle, Users,
  Play, Square, RefreshCw, Wifi, WifiOff, Bot, Plus, Settings, Link2,
} from 'lucide-react';
```

2) В `AgentCard` вычислить и разветвить кнопки:

```tsx
function AgentCard({ agent, details }: { agent: AgentRecord; details?: { phone_number: string | null; last_started_at: string | null } }) {
  const { mutate: start, isPending: starting } = useStartAgent();
  const { mutate: stop, isPending: stopping } = useStopAgent();
  const { toast } = useToast();

  const canStart = agent.state === 'stopped' || agent.state === 'error';
  const canStop = agent.state === 'running';
  const rebind = needsRebind(details?.authorization_status);
```

Сигнатуру пропса `details` расширить: `details?: { phone_number: string | null; authorization_status: TelegramAuthorizationStatus | null; last_started_at: string | null }` и добавить импорт `import type { AgentRecord, TelegramAuthorizationStatus } from '@/types';`

3) Заменить блок кнопок:

```tsx
      <div className="flex items-center gap-2 pt-1">
        {rebind ? (
          <Link href={`/agent/${agent.agent_id}/rebind`} className="flex-1">
            <Button
              variant="outline" size="sm" className="w-full"
              leftIcon={<Link2 className="h-3.5 w-3.5" />}
            >
              Перепривязать
            </Button>
          </Link>
        ) : (
          <Button
            variant="success" size="sm"
            onClick={handleStart}
            disabled={!canStart}
            isLoading={starting}
            leftIcon={<Play className="h-3.5 w-3.5" />}
          >
            Запустить
          </Button>
        )}
        {!rebind && (
          <Button
            variant="danger" size="sm"
            onClick={handleStop}
            disabled={!canStop}
            isLoading={stopping}
            leftIcon={<Square className="h-3.5 w-3.5" />}
          >
            Стоп
          </Button>
        )}
        <div className="flex-1" />
        <Link href={`/agent/${agent.agent_id}`} aria-label="Настройки агента">
          <Button variant="ghost" size="sm" className="px-2">
            <Settings className="h-4 w-4" />
          </Button>
        </Link>
      </div>
```

- [ ] **Step 2: Кнопка в шапке страницы агента (AgentControls)**

В `frontend/src/app/(dashboard)/agent/[id]/page.tsx` в `AgentControls` добавить хук и развилку:

```tsx
import { useTelegramSession } from '@/hooks/useTelegramSession';
import { needsRebind } from '@/lib/telegram';
import Link from 'next/link';
import { Link2 } from 'lucide-react';

function AgentControls({ agentId, state }: { agentId: string; state?: string }) {
  const { toast } = useToast();
  const { mutate: start, isPending: starting } = useStartAgent();
  const { mutate: stop, isPending: stopping } = useStopAgent();
  const { data: telegramSession } = useTelegramSession(agentId);
  const rebind = needsRebind(telegramSession?.authorization_status);
  const [stopConfirm, setStopConfirm] = useState(false);

  if (rebind) {
    return (
      <div className="flex items-center gap-2">
        <Link href={`/agent/${agentId}/rebind`}>
          <Button variant="outline" size="sm" leftIcon={<Link2 className="h-3.5 w-3.5" />}>
            Перепривязать
          </Button>
        </Link>
      </div>
    );
  }

  return (
    /* существующая разметка без изменений */
  );
}
```

- [ ] **Step 3: Действие в TabActions**

В `TabActions` заменить первый элемент массива `actions` (условное перепривязывание):

```tsx
  const { data: telegramSession } = useTelegramSession(agentId);
  const rebind = needsRebind(telegramSession?.authorization_status);

  const startAction = rebind
    ? {
        title: 'Перепривязать Telegram',
        desc: 'Сессия недействительна. Введите код заново — память и настройки сохранятся',
        icon: Link2,
        color: 'text-amber-400',
        bg: 'bg-amber-950/40 border-amber-900',
        action: () => router.push(`/agent/${agentId}/rebind`),
        loading: false,
        label: 'Перепривязать',
        variant: 'default' as const,
        destructive: false,
      }
    : {
        title: 'Запустить агента',
        desc: 'Агент начнёт получать и отвечать на сообщения в Telegram',
        icon: Play,
        color: 'text-neon-400',
        bg: 'bg-neon-950/40 border-neon-900',
        action: () => start(agentId, {
          onSuccess: () => toast('Агент запускается', 'success'),
          onError: (e: unknown) => toast((e as ApiError).message, 'error'),
        }),
        loading: starting,
        label: 'Запустить',
        variant: 'success' as const,
        destructive: false,
      };

  const actions = [
    startAction,
    // ... остальные три действия без изменений
  ];
```

- [ ] **Step 4: Оживить кнопку на вкладке Telegram**

В `TabTelegram` заменить неактивную кнопку «Переподключить»:

```tsx
        <Link href={`/agent/${agentId}/rebind`}>
          <Button variant="outline" size="sm" leftIcon={<RefreshCw className="h-3.5 w-3.5" />}>
            Перепривязать
          </Button>
        </Link>
```

- [ ] **Step 5: Проверить типы и линт**

Run (в каталоге `frontend`): `bun run typecheck && bun run lint`
Expected: без ошибок

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app
git commit -m "feat(frontend): offer session rebind instead of start when telegram session is broken"
```

---

### Task 10: Полная проверка, PR

**Files:** без изменений кода

- [ ] **Step 1: Бэкенд — линтер и типы**

```bash
uv run ruff check .
uv run ty check src tests
```
Expected: без ошибок

- [ ] **Step 2: Бэкенд — юнит-тесты**

```bash
uv run pytest tests/api tests/core tests/integrations testing -q
```
Expected: все PASS

- [ ] **Step 3: Бэкенд — db-тесты (нужен .env с тестовой базой)**

```bash
uv run pytest -m db tests/integration/test_telegram_session_status.py tests/integration/test_database_agent_store.py -q
```
Expected: PASS. Тесты берут слот тестовой базы автоматически (conftest), real_tg-замок не нужен.

- [ ] **Step 4: Фронтенд — линт, типы, юнит-тесты**

```bash
cd frontend && bun run lint && bun run typecheck && bun test
```
Expected: без ошибок

- [ ] **Step 5: Push и PR**

```bash
git push -u origin feat/issue-58-reauth
gh pr create --title "feat: перепривязка Telegram-сессии агента" --body "Closes #58

- Ошибки авторизации на русском (тосты, логи активности, 428/409 детали)
- Рантайм помечает telegram_sessions как revoked при unauthorized-старте
- Флоу перепривязки: /agent/[id]/rebind (телефон → код → 2FA) поверх стандартного онбординг-логина Telethon
- Новые эндпоинты: POST /agents/{id}/telegram/rebind, POST /agents/{id}/telegram/rebind/confirm
- rebind_telegram_session в AgentStore (InMemory + Database): обновляется только telegram_sessions, профиль и память не трогаются
- Кнопка «Перепривязать» вместо «Запустить» на дашборде, в шапке агента, в «Управлении» и на вкладке Telegram"
```

- [ ] **Step 6: После merge — проверить CI/деплой**

Смотреть `.github/workflows/ci.yml` (тесты + линтеры) и `deploy.yml` (автодеплой по merge в main). После деплоя руками проверить, что прод-база не требует миграций (их нет) — фича включится сама.

---

## Самопроверка плана

- **Покрытие issue:** пункт 1 (русские ошибки) — Task 1; пункт 2 (кнопка «Перепривязать» в плашке и в «Действиях») — Task 9; пункт 3 (повторный онбординг с сохранением памяти/имени/настроек) — Tasks 3-6, 8.
- **Миграции БД:** не нужны — `telegram_authorization_status` уже содержит `revoked` (database_models.py:37-45).
- **Telethon:** Telethon-слой не меняется; перепривязка идёт через тот же `AgentOnboardingService.request_telegram_code`/`verify_telegram_code`, что соответствует документации (`sign_in(password=...)` после `SessionPasswordNeededError`, `phone_code_hash` из `send_code_request`).
- **Согласованность типов:** `AgentDetails.authorization_status` (Task 7) используется в Task 9; `rebind_telegram_session` в протоколе (Task 3) реализуется в Task 4 и потребляется сервисом из Task 5 и API из Task 6.
