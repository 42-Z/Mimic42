# Единая лента «Активность» + медиа в Storage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Объединить вкладки «Активность»/«Чат» в одну ленту ходов (issue #59) с корректным порядком, рабочими фильтрами, видимыми финальными ответами и просматриваемыми медиа через Supabase Storage.

**Architecture:** Бэкенд отдаёт ходы через курсорную пагинацию (`before=<ts>`) и сохраняет медиа (входящие, `view_image`) в приватный бакет `agent-media`; фронт рендерит единую ленту newest-first из одного источника + realtime. base64 в логи больше не попадает (санитизация в `ActivityMiddleware`).

**Tech Stack:** FastAPI, SQLAlchemy, Telethon, supabase-py (Storage), Next.js, TanStack Query, bun test, pytest.

Спека: `docs/superpowers/specs/2026-09-16-activity-feed-design.md`

## Task 0: Ветка

- [ ] **Step 1: Создать рабочую ветку (все коммиты Tasks 1-15 идут в неё)**

```bash
git checkout -b feat/unified-activity-feed
```

---

## File Structure

Backend:
- Create: `src/mimic42/core/media.py` — `MediaFile`, протокол `MediaUploader`
- Create: `src/mimic42/integrations/supabase_media.py` — `SupabaseMediaStorage`
- Modify: `src/mimic42/config.py` — `supabase_service_key`
- Modify: `src/mimic42/integrations/database_memory.py` — `save_messages(media=...)`
- Modify: `src/mimic42/core/agent_runtime.py` — захват медиа в `_process_media_and_text`, `AgentTrigger.media`
- Modify: `src/mimic42/core/manager.py` — инъекция uploader в runtime/tools
- Modify: `src/mimic42/integrations/telegram_tools.py` — `view_image` грузит медиа, `build_telegram_langchain_tools(media_uploader=...)`
- Modify: `src/mimic42/integrations/activity_middleware.py` — `_sanitize_result` (strip base64)
- Modify: `src/mimic42/core/agent_store.py` — `ConversationTurn.turn_id/incoming_media`, `get_conversation` → курсор, `ConversationPage`
- Modify: `src/mimic42/integrations/database_agent_store.py` — курсорная пагинация
- Modify: `src/mimic42/api/app.py` — conversation endpoint, media endpoint, delete cleanup
- Test: `tests/integrations/test_supabase_media.py`, `tests/integrations/test_database_memory_media.py`, `tests/core/test_runtime_media.py`, `tests/integrations/test_activity_middleware_sanitize.py`, `tests/integrations/test_agent_store_conversation.py`, `tests/api/test_media_endpoint.py`
- Migration: `supabase/migrations/<ts>_agent_media_bucket.sql`

Frontend:
- Modify: `frontend/src/types/index.ts` — `MediaItem`, `ConversationTurn.turn_id/incoming_media`
- Modify: `frontend/src/lib/api.ts` — `getConversation(before)`, `getMedia`
- Create: `frontend/src/hooks/useActivityFeed.ts` (замена `useConversation.ts`)
- Create: `frontend/src/hooks/useMediaUrl.ts`
- Modify: `frontend/src/lib/activity/normalize.ts` — `incomingMedia`, structured-ответы, fallback ответа из `tool.send_text_message`, `turnToActivityItem`
- Create: `frontend/src/components/activity/MediaContent.tsx`
- Modify: `frontend/src/components/activity/TurnCard.tsx` — порядок внутри блока, медиа
- Create: `frontend/src/components/activity/TabActivity.tsx` (замена `TabLogs.tsx` и `TabLogsChat.tsx`)
- Delete: `frontend/src/components/agent/TabLogs.tsx`, `frontend/src/components/chat/*`, `frontend/src/hooks/useConversation.ts`
- Modify: `frontend/src/app/(dashboard)/agent/[id]/page.tsx`, `frontend/src/app/(dashboard)/dashboard/page.tsx`
- Test: `frontend/src/__tests__/activity.test.ts`, e2e `frontend/e2e/agent.spec.ts`

---

### Task 1: MediaUploader + SupabaseMediaStorage + конфиг

**Files:**
- Create: `src/mimic42/core/media.py`
- Create: `src/mimic42/integrations/supabase_media.py`
- Modify: `src/mimic42/config.py`
- Modify: `.env.example`
- Test: `tests/integrations/test_supabase_media.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integrations/test_supabase_media.py
from types import SimpleNamespace
from uuid import uuid4

from mimic42.integrations.supabase_media import MAX_MEDIA_BYTES, SupabaseMediaStorage


class FakeBucket:
    def __init__(self, store: dict[str, bytes]) -> None:
        self._store = store

    def upload(self, *, file: bytes, path: str, file_options: dict | None = None) -> None:
        self._store[path] = bytes(file)

    def download(self, path: str) -> bytes:
        if path not in self._store:
            raise KeyError(path)
        return self._store[path]

    def list(self, prefix: str) -> list[dict]:
        return [
            {"name": p.removeprefix(prefix + "/")}
            for p in self._store
            if p.startswith(prefix + "/")
        ]

    def remove(self, paths: list[str]) -> None:
        for p in paths:
            self._store.pop(p, None)


def build_storage(monkeypatch: object, store: dict[str, bytes]) -> SupabaseMediaStorage:
    bucket = FakeBucket(store)
    fake = SimpleNamespace(storage=SimpleNamespace(from_=lambda _name: bucket))
    monkeypatch.setattr("supabase.create_client", lambda *a, **k: fake)
    return SupabaseMediaStorage(
        supabase_url="https://example.supabase.co", service_key="service-key"
    )


async def test_upload_stores_file_and_returns_metadata(monkeypatch) -> None:
    store: dict[str, bytes] = {}
    storage = build_storage(monkeypatch, store)
    agent_id = uuid4()
    media = await storage.upload(
        agent_id=agent_id, filename="photo.jpeg", data=b"\xff\xd8jpg", mime_type="image/jpeg", kind="photo"
    )
    assert media is not None
    assert media.kind == "photo"
    assert media.storage_path.startswith(f"{agent_id}/")
    assert media.storage_path.endswith("/photo.jpeg")
    assert media.size == len(b"\xff\xd8jpg")
    assert store[media.storage_path] == b"\xff\xd8jpg"


async def test_upload_skips_oversized(monkeypatch) -> None:
    store: dict[str, bytes] = {}
    storage = build_storage(monkeypatch, store)
    media = await storage.upload(
        agent_id=uuid4(), filename="big.bin", data=b"x" * (MAX_MEDIA_BYTES + 1), mime_type="application/octet-stream", kind="doc"
    )
    assert media is None
    assert store == {}


async def test_open_and_remove_prefix(monkeypatch) -> None:
    store: dict[str, bytes] = {}
    storage = build_storage(monkeypatch, store)
    agent_id = uuid4()
    media = await storage.upload(agent_id=agent_id, filename="a.txt", data=b"hi", mime_type="text/plain", kind="doc")
    assert media is not None
    assert await storage.open(media.storage_path) == b"hi"
    assert await storage.open(f"{agent_id}/missing.txt") is None
    await storage.remove_prefix(agent_id)
    assert store == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integrations/test_supabase_media.py -v`
Expected: FAIL — `ModuleNotFoundError: mimic42.integrations.supabase_media`

- [ ] **Step 3: Write implementation**

```python
# src/mimic42/core/media.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


@dataclass(slots=True)
class MediaFile:
    """Metadata of one archived media item (Telegram attachment or tool view)."""

    kind: str  # photo | sticker | voice | round | doc
    name: str
    mime_type: str
    size: int
    storage_path: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "mime_type": self.mime_type,
            "size": self.size,
            "storage_path": self.storage_path,
        }


class MediaUploader(Protocol):
    async def upload(
        self,
        *,
        agent_id: UUID,
        filename: str,
        data: bytes,
        mime_type: str,
        kind: str = "doc",
    ) -> MediaFile | None: ...

    async def open(self, path: str) -> bytes | None: ...

    async def remove_prefix(self, agent_id: UUID) -> None: ...
```

```python
# src/mimic42/integrations/supabase_media.py
from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

from mimic42.core.media import MediaFile

logger = logging.getLogger("mimic42.media")

MAX_MEDIA_BYTES = 20 * 1024 * 1024
BUCKET = "agent-media"


class SupabaseMediaStorage:
    """Media files for the activity feed in a private Supabase Storage bucket.

    All access goes through the backend with the service role key; the bucket
    has no anon/authenticated policies, so the dashboard can only read files
    via the media API endpoint. supabase-py is synchronous — every call is
    wrapped in asyncio.to_thread so the event loop never blocks.
    """

    def __init__(self, *, supabase_url: str, service_key: str) -> None:
        from supabase import create_client

        self._storage = create_client(supabase_url, service_key).storage

    def _bucket(self) -> Any:
        return self._storage.from_(BUCKET)

    async def upload(
        self,
        *,
        agent_id: UUID,
        filename: str,
        data: bytes,
        mime_type: str,
        kind: str = "doc",
    ) -> MediaFile | None:
        if not data:
            return None
        if len(data) > MAX_MEDIA_BYTES:
            logger.warning("Media %s too large (%d bytes), skipping", filename, len(data))
            return None
        safe_name = filename.replace("/", "_") or "file"
        path = f"{agent_id}/{uuid4()}/{safe_name}"
        try:
            await asyncio.to_thread(
                lambda: self._bucket().upload(
                    file=data,
                    path=path,
                    file_options={"content-type": mime_type, "upsert": "false"},
                )
            )
        except Exception:
            logger.warning("Failed to upload media %s", path, exc_info=True)
            return None
        return MediaFile(
            kind=kind, name=safe_name, mime_type=mime_type, size=len(data), storage_path=path
        )

    async def open(self, path: str) -> bytes | None:
        try:
            blob = await asyncio.to_thread(lambda: self._bucket().download(path))
        except Exception:
            logger.warning("Failed to download media %s", path, exc_info=True)
            return None
        return bytes(blob) if isinstance(blob, (bytes, bytearray)) else None

    async def remove_prefix(self, agent_id: UUID) -> None:
        try:
            items = await asyncio.to_thread(lambda: self._bucket().list(str(agent_id)))
            paths = [f"{agent_id}/{item['name']}" for item in items if item.get("name")]
            if paths:
                await asyncio.to_thread(lambda: self._bucket().remove(paths))
        except Exception:
            logger.warning("Failed to clean media for agent %s", agent_id, exc_info=True)
```

Modify `src/mimic42/config.py` — add after `supabase_url`:

```python
    supabase_service_key: str | None = Field(
        default=None, validation_alias="SUPABASE_SERVICE_ROLE_KEY"
    )
```

Modify `.env.example` — add after `SUPABASE_URL=`:

```
# Service-ключ Supabase для записи медиа из логов в Storage (agent-media)
SUPABASE_SERVICE_ROLE_KEY=
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integrations/test_supabase_media.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests
uv run ty check
git add src/mimic42/core/media.py src/mimic42/integrations/supabase_media.py src/mimic42/config.py .env.example tests/integrations/test_supabase_media.py
git commit -m "feat: media uploader protocol and supabase storage service"
```

---

### Task 2: Миграция бакета agent-media

**Files:**
- Create: `supabase/migrations/<timestamp>_agent_media_bucket.sql`

- [ ] **Step 1: Create the migration with the Supabase CLI**

Run: `supabase migration new agent_media_bucket`
Expected: creates `supabase/migrations/<timestamp>_agent_media_bucket.sql`

- [ ] **Step 2: Write the SQL**

```sql
-- Приватный бакет для медиа из ленты активности: файлы читает только бэкенд
-- (service_role), дашборд ходит через /agents/{id}/media/*.
insert into storage.buckets (id, name, public, file_size_limit)
values ('agent-media', 'agent-media', false, 20971520)
on conflict (id) do update
    set file_size_limit = excluded.file_size_limit,
        public = false;
```

- [ ] **Step 3: Apply locally and verify**

Run: `supabase db push --local`
Then: `supabase db query "select id, public, file_size_limit from storage.buckets where id = 'agent-media'"`
Expected: `agent-media | false | 20971520`. Если локальный стек не запущен — применить SQL через MCP `execute_sql` к Dev-проекту и тем же запросом проверить.

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations
git commit -m "feat: agent-media storage bucket migration"
```

---

### Task 3: save_messages пишет payload["media"]

**Files:**
- Modify: `src/mimic42/integrations/database_memory.py:62-120`
- Test: `tests/integration/test_database_memory_media.py`

- [ ] **Step 1: Write the failing test**

Тесты в `tests/integration/` автоматически получают маркер `db`
(`conftest.py:77-81`); запуск против базы Dev: `uv run pytest -m db tests/integration/...`.

```python
# tests/integration/test_database_memory_media.py
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.integrations.database_memory import DatabaseShortTermMemory
from mimic42.integrations.database_models import AgentMessageModel

MEDIA = [
    {"kind": "photo", "name": "photo.jpeg", "mime_type": "image/jpeg",
     "size": 3, "storage_path": "00000000-0000-0000-0000-000000000000/u1/photo.jpeg"},
]


async def test_save_messages_attaches_media_to_incoming_row(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = DatabaseShortTermMemory(db_session_factory)
    agent_id = uuid4()
    await store.save_messages(
        agent_id=agent_id,
        peer="12345",
        messages=[{"role": "assistant", "content": "Ответ"}],
        peer_name="Ivan",
        raw_user_text="Привет",
        media=MEDIA,
    )

    async with db_session_factory() as session:
        row = await session.scalar(
            select(AgentMessageModel)
            .where(AgentMessageModel.agent_id == agent_id)
            .where(AgentMessageModel.direction == "incoming")
            .order_by(AgentMessageModel.created_at.desc())
            .limit(1)
        )
        assert row is not None
        assert row.content == "Привет"
        assert row.payload.get("media") == MEDIA


async def test_save_messages_attaches_media_when_incoming_row_deduped(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = DatabaseShortTermMemory(db_session_factory)
    agent_id = uuid4()
    messages = [{"role": "user", "content": "Привет"},
                {"role": "assistant", "content": "Ответ"}]
    await store.save_messages(agent_id=agent_id, peer="12345", messages=messages,
                              raw_user_text="Привет", media=MEDIA)
    # Второй вызов: raw_user_text совпадает с последним user-контентом —
    # дедуп не создаёт incoming-строку, медиа должны лечь на user-строку цикла
    await store.save_messages(agent_id=agent_id, peer="12345", messages=messages,
                              raw_user_text="Привет", media=MEDIA)

    async with db_session_factory() as session:
        rows = list(
            await session.scalars(
                select(AgentMessageModel)
                .where(AgentMessageModel.agent_id == agent_id)
                .where(AgentMessageModel.direction == "incoming")
                .order_by(AgentMessageModel.created_at.asc())
            )
        )
        assert any("media" in row.payload for row in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -m db tests/integration/test_database_memory_media.py -v`
Expected: FAIL — `TypeError: save_messages() got an unexpected keyword argument 'media'`

- [ ] **Step 3: Implement**

В `save_messages` добавить параметр и вложение:

```python
    async def save_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        messages: list[dict[str, Any]],
        structured_response: dict[str, Any] | None = None,
        peer_name: str = "",
        agent_name: str = "",
        raw_user_text: str = "",
        turn_id: str | None = None,
        thread_id: UUID | None = None,
        media: list[dict[str, Any]] | None = None,
    ) -> None:
```

В начале метода: `media_attached = False`. В ветке `if raw_user_text and ...`
после формирования `user_payload`:

```python
                if media:
                    user_payload["media"] = media
                    media_attached = True
```

В цикле по messages — вложение на первую user-строку, если входящая строка не
создавалась (дедуп):

```python
                if media and not media_attached and role in ("user", "human"):
                    payload["media"] = media
                    media_attached = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -m db tests/integration/test_database_memory_media.py -v`
Expected: PASS

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run ty check
git add src/mimic42/integrations/database_memory.py tests/integration/test_database_memory_media.py
git commit -m "feat: persist message media metadata in payload"
```

---

### Task 4: Рантайм сохраняет входящие медиа

**Files:**
- Modify: `src/mimic42/core/agent_runtime.py` (`AgentTrigger:63`, `_process_media_and_text:1040`, обработчик ~701, `trigger_message` ~542)
- Modify: `src/mimic42/core/manager.py` (`_build_runtime_with_memory`, `_build_runtime`)
- Test: `tests/core/test_runtime_media.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_runtime_media.py
from mimic42.core.media import MediaFile
from mimic42.core.agent_runtime import _process_media_and_text


class FakeClient:
    async def download_media(self, message, file=None, **kwargs):
        file.write(b"JPEGDATA")
        return file


class FakeEvent:
    def __init__(self) -> None:
        self.client = FakeClient()
        self.message = SimpleNamespace(
            media=SimpleNamespace(photo=SimpleNamespace(id=1)),
            raw_text="",
        )

    def __getattr__(self, name):
        return None


class FakeUploader:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes]] = []

    async def upload(self, *, agent_id, filename, data, mime_type, kind="doc"):
        self.uploads.append((filename, data))
        return MediaFile(kind=kind, name=filename, mime_type=mime_type, size=len(data), storage_path=f"{agent_id}/x/{filename}")


async def test_photo_message_uploads_and_returns_media() -> None:
    uploader = FakeUploader()
    text, media = await _process_media_and_text(
        FakeEvent(), "", media_uploader=uploader, agent_id=uuid4()
    )
    assert text.startswith("[Фото id=")
    assert len(media) == 1
    assert media[0].kind == "photo"
    assert uploader.uploads[0] == ("photo.jpeg", b"JPEGDATA")
```

(Адаптируйте фейковое сообщение к реальному пути `format_media_object`:
`photo:{id}:{access_hash}:{ref_hex}:{dc_id}` — соберите `SimpleNamespace` с
`types.Photo`-подобным объектом, как это уже делают существующие тесты
`tests/integrations/test_telegram_tools.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_runtime_media.py -v`
Expected: FAIL — unexpected keyword `media_uploader`

- [ ] **Step 3: Implement**

`_process_media_and_text` меняет подпись и возвращает кортеж:

```python
async def _process_media_and_text(
    event: TelegramEventLike,
    text: str,
    *,
    http_client: Any | None = None,
    media_uploader: MediaUploader | None = None,
    agent_id: UUID | None = None,
) -> tuple[str, list[MediaFile]]:
    message = getattr(event, "message", None)
    if not message or not getattr(message, "media", None):
        return text, []

    media_files: list[MediaFile] = []

    async def _archive(kind: str, filename: str, mime_type: str, data: bytes) -> None:
        if media_uploader is None or not data:
            return
        try:
            archived = await media_uploader.upload(
                agent_id=cast(UUID, agent_id),
                filename=filename,
                data=data,
                mime_type=mime_type,
                kind=kind,
            )
        except Exception:
            logger.warning("Media archiving failed for %s", filename, exc_info=True)
            return
        if archived is not None:
            media_files.append(archived)
```

(Дальше по тексту каждой ветки `if/elif` — вставка `_archive` в существующие
ветки photo/sticker/voice/round/doc; список ниже.)

Каждая ветка: скачивание в `bytes` + `_archive(...)` + прежний текст-маркер.
- photo: `data = await event.client.download_media(message, file=bytes)` →
  `_archive("photo", "photo.jpeg", "image/jpeg", data)` → вернуть `[Фото id=...]`.
- sticker: то же (`"sticker.webp"`, `image/webp`).
- voice/round: `file_bytes` уже скачан → `_archive("voice"|"round", filename, mime)` перед транскрипцией; filename как сейчас (`voice.ogg`/`video.mp4`).
- doc: `file_bytes` уже скачан → `_archive("doc", filename, mime из doc.mime_type, file_bytes)` (в т.ч. для запрещённых расширений — файл всё равно архивируется).

В обработчике (~701):

```python
            text, media_files = await _process_media_and_text(
                event, raw_text, http_client=self._http_client,
                media_uploader=self._media_uploader, agent_id=self.config.agent_id,
            )
```

`AgentTrigger` — добавить поле:

```python
    media: list[dict[str, Any]] = Field(default_factory=list)
```

В вызове `AgentTrigger(...)` (~924): `media=[m.as_payload() for m in media_files],`.
В `trigger_message` (~542) в `save_messages(...)`: `media=trigger.media or None,`.

`MimicAgentRuntime.__init__`: параметр `media_uploader: MediaUploader | None = None`,
`self._media_uploader = media_uploader`.

`manager.py`: в `AgentManager.__init__` — `media_uploader: MediaUploader | None = None`,
публичный атрибут `self.media_uploader = media_uploader` (нужен media-endpoint'у в
`app.py`), в `_build_runtime_with_memory` и `_build_runtime` передавать
`media_uploader=self.media_uploader` в `MimicAgentRuntime(...)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_runtime_media.py -v`
Expected: PASS

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run ty check
git add src/mimic42/core/agent_runtime.py src/mimic42/core/manager.py tests/core/test_runtime_media.py
git commit -m "feat: archive incoming media to storage from agent runtime"
```

---

### Task 5: Проводка uploader в create_app и AgentManager

**Files:**
- Modify: `src/mimic42/api/app.py:156-173` (сигнатура `create_app`, конструкция `AgentManager`)

- [ ] **Step 1: Implement**

В `create_app` добавить параметр `media_uploader: MediaUploader | None = None`
(нужен и для тестов, и для подавления билда Storage в юнит-тестах):

```python
def create_app(
    *,
    manager: AgentManagerLike | None = None,
    onboarding_service: AgentOnboardingService | None = None,
    agent_store: AgentStore | None = None,
    auth_verifier: AuthVerifier | None = None,
    settings: Settings | None = None,
    telegram_factory: TelegramAuthClientFactory | None = None,
    telegram_client_factory: TelegramClientFactory | None = None,
    langchain_agent_factory: LangChainAgentFactory | None = None,
    long_term_memory: LongTermMemoryLike | None = None,
    media_uploader: MediaUploader | None = None,
) -> FastAPI:
```

В теле `create_app` (рядом с `app_manager = manager or AgentManager(...)`):

```python
    app_media_storage = media_uploader
    if app_manager is not None and app_manager.media_uploader is None:
        if app_settings.supabase_url and app_settings.supabase_service_key:
            app_manager.media_uploader = SupabaseMediaStorage(
                supabase_url=app_settings.supabase_url,
                service_key=app_settings.supabase_service_key,
            )
        app_media_storage = app_manager.media_uploader
```

Импорты: `from mimic42.core.media import MediaUploader` и
`from mimic42.integrations.supabase_media import SupabaseMediaStorage`.
`AgentManager.media_uploader` — публичный атрибут из Task 4.

- [ ] **Step 2: Run full backend suite**

Run: `uv run pytest tests/core tests/api -q`
Expected: PASS (без новых падений)

- [ ] **Step 3: Commit**

```bash
git add src/mimic42/api/app.py
git commit -m "feat: wire supabase media storage into agent manager"
```

---

### Task 6: view_image сохраняет медиа; middleware чистит base64

**Files:**
- Modify: `src/mimic42/integrations/telegram_tools.py:243-252` (конструктор), `:669-734` (`view_image`), `:2462-2468` (`build_telegram_langchain_tools`)
- Modify: `src/mimic42/core/manager.py` (оба вызова `build_telegram_langchain_tools`)
- Modify: `src/mimic42/integrations/activity_middleware.py`
- Test: `tests/integrations/test_activity_middleware_sanitize.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integrations/test_activity_middleware_sanitize.py
from mimic42.integrations.activity_middleware import _sanitize_result


def test_data_urls_are_replaced_with_marker() -> None:
    result = {"items": [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + "A" * 500}},
        {"type": "media_ref", "storage_path": "ag/1/x.jpeg"},
    ]}
    cleaned = _sanitize_result(result)
    item = cleaned["items"][0]
    assert "_omitted" in item["image_url"]["url"]
    assert cleaned["items"][1] == {"type": "media_ref", "storage_path": "ag/1/x.jpeg"}


def test_short_strings_and_non_base64_are_kept() -> None:
    result = {"text": "привет", "small": "data:x"}
    assert _sanitize_result(result) == result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integrations/test_activity_middleware_sanitize.py -v`
Expected: FAIL — `ImportError: cannot import name '_sanitize_result'`

- [ ] **Step 3: Implement middleware sanitizer**

В `activity_middleware.py`:

```python
_BASE64_DATA_URL_MIN = 400


def _sanitize_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Replace inline base64 payloads with markers so logs stay compact.

    Media bytes are archived to Storage by the tools themselves; the
    `media_ref` items (storage_path) survive sanitization.
    """
    if result is None:
        return None

    def clean(value: Any) -> Any:
        if isinstance(value, str):
            if value.startswith("data:") and len(value) > _BASE64_DATA_URL_MIN:
                return '{"_omitted": "base64 media, archived in Storage"}'
            return value
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(result)
```

В `awrap_tool_call` заменить `result=result` на `result=_sanitize_result(result)`
(строки 115-129; переменная уже вычислена `_classify_tool_output`).

- [ ] **Step 4: view_image + проводка**

`TelegramToolbox.__init__` — добавить параметр и логгер (в `telegram_tools.py`
сейчас нет `logger` — добавить `import logging` и
`logger = logging.getLogger("mimic42.telegram_tools")` рядом с импортами):

```python
    def __init__(
        self,
        client: Any,
        agent_id: UUID | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        media_uploader: MediaUploader | None = None,
    ) -> None:
        self._client = client
        self._agent_id = agent_id
        self._session_factory = session_factory
        self._last_send_text_message: dict[str, datetime] = {}
        self._media_uploader = media_uploader
```

`view_image` после `data = await self._client.download_media(media_obj, file=bytes)`:

```python
            storage_path: str | None = None
            if self._media_uploader is not None and self._agent_id is not None:
                try:
                    archived = await self._media_uploader.upload(
                        agent_id=self._agent_id,
                        filename=f"view_{media_type}_{obj_id}." + mime_type.split("/")[-1],
                        data=data,
                        mime_type=mime_type,
                        kind=media_type,
                    )
                    storage_path = archived.storage_path if archived else None
                except Exception:
                    logger.warning("view_image media upload failed", exc_info=True)
            items: list[dict[str, Any]] = []
            if storage_path:
                items.append({
                    "type": "media_ref",
                    "storage_path": storage_path,
                    "mime_type": mime_type,
                    "size": len(data),
                    "name": f"view_{media_type}_{obj_id}",
                })
            items.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{base64_str}"},
            })
            return items
```

`build_telegram_langchain_tools` — параметры `(client, agent_id=None,
session_factory=None, media_uploader=None)`, передать в конструктор. В `manager.py`
оба вызова (`_build_runtime_with_memory`, `_build_runtime`) добавить
`media_uploader=self.media_uploader`.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/integrations/test_activity_middleware_sanitize.py tests/integrations/test_telegram_tools.py -v`
Expected: PASS

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check src tests && uv run ty check
git add src/mimic42/integrations/telegram_tools.py src/mimic42/integrations/activity_middleware.py src/mimic42/core/manager.py tests/integrations/test_activity_middleware_sanitize.py
git commit -m "feat: archive viewed images and strip base64 from activity log"
```

---

### Task 7: Курсорная пагинация get_conversation

**Files:**
- Modify: `src/mimic42/core/agent_store.py:98-104` (Protocol), `:60-72` (`ConversationTurn`), `:189-241` (InMemory)
- Modify: `src/mimic42/integrations/database_agent_store.py:220-336`
- Modify: `tests/integration/test_database_agent_store.py:159-239` (существующий тест под новую сигнатуру)
- Test: `tests/integration/test_agent_store_conversation.py`

- [ ] **Step 1: Write the failing test**

Формат seed'а повторяет `tests/integration/test_database_agent_store.py:159-220`
(AgentModel + AgentMessageModel + AgentEventModel; тесты в `tests/integration/`
маркер `db` получают автоматически — запуск `uv run pytest -m db ...`).

```python
# tests/integration/test_agent_store_conversation.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.integrations.database_models import (
    AgentEventModel,
    AgentMessageModel,
    AgentModel,
)


async def _seed(db_session_factory, owner_id, base: datetime) -> None:
    agent_id = uuid4()
    async with db_session_factory() as session:
        session.add(AgentModel(id=agent_id, owner_id=owner_id, name="Mimic",
                               status=AgentRuntimeState.STOPPED.value, soul_prompt="Soul"))
        await session.commit()
    async with db_session_factory() as session:
        for i, offset in enumerate((2, 1, 0)):
            t = base + timedelta(minutes=i * 10)
            session.add(AgentMessageModel(agent_id=agent_id, direction="incoming",
                role="user", content=f"turn-{offset}", payload={"peer": "chat", "turn_id": f"t{offset}"},
                created_at=t))
            session.add(AgentEventModel(agent_id=agent_id, event_type="tool.get_dialogs",
                status="succeeded", payload={"turn_id": f"t{offset}"},
                created_at=t + timedelta(seconds=1), started_at=t, completed_at=t + timedelta(seconds=1)))
            session.add(AgentMessageModel(agent_id=agent_id, direction="agent_response",
                role="assistant", content=f"reply-{offset}", payload={"peer": "chat", "turn_id": f"t{offset}"},
                created_at=t + timedelta(seconds=2)))
        await session.commit()


async def test_cursor_pagination_no_duplicates_no_gaps(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot,
) -> None:
    from mimic42.integrations.database_agent_store import DatabaseAgentStore

    owner_id = clean_slot.persona("twofa").user_id
    base = datetime(2026, 5, 19, 23, 30, tzinfo=UTC)
    await _seed(db_session_factory, owner_id, base)
    store = DatabaseAgentStore(db_session_factory)
    agent_id = (await store.list_agents(owner_id=owner_id))[0].agent_id

    page1 = await store.get_conversation(agent_id=agent_id, limit=2)
    assert len(page1.turns) == 2
    assert page1.next_before is not None

    page2 = await store.get_conversation(agent_id=agent_id, limit=2, before=page1.next_before)
    assert len(page2.turns) == 1

    ids = {turn.id for turn in page1.turns} | {turn.id for turn in page2.turns}
    assert len(ids) == 3  # ни дубликатов, ни потерь


async def test_turns_are_newest_first_with_turn_identity(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    base = datetime(2026, 5, 19, 23, 30, tzinfo=UTC)
    await _seed(db_session_factory, owner_id, base)
    store = DatabaseAgentStore(db_session_factory)
    agent_id = (await store.list_agents(owner_id=owner_id))[0].agent_id

    page = await store.get_conversation(agent_id=agent_id, limit=10)
    assert [turn.timestamp for turn in page.turns] == sorted(
        [turn.timestamp for turn in page.turns], reverse=True
    )
    assert all(turn.turn_id for turn in page.turns)
    # tools из хода лежат в том же ходе, что и его incoming
    assert all(turn.tools[0].name == "tool.get_dialogs" for turn in page.turns)
```

Плюс обновить существующий `test_database_conversation_groups_messages_and_tool_events`
(`tests/integration/test_database_agent_store.py:159-239`): вызовы
`get_conversation` теперь возвращают `ConversationPage` — заменить
`turns = await store.get_conversation(...)` на `page = await ...` и обращаться через
`page.turns` (лимитный ассерт: `page.turns[0].outgoing == "proactive"`).

- [ ] **Step 3: Implement store protocol + InMemory**

`core/agent_store.py`:

```python
class ConversationTurn(BaseModel):
    """A single conversation turn: incoming + outgoing + metadata + tools."""

    id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    timestamp: datetime
    peer_id: str
    peer_name: str = ""
    agent_name: str = ""
    incoming: str = ""
    outgoing: str = ""
    direction: str = ""
    turn_id: str | None = None
    incoming_media: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[ToolCallRecord] = Field(default_factory=list)


class ConversationPage(BaseModel):
    turns: list[ConversationTurn] = Field(default_factory=list)
    next_before: datetime | None = None
```

Protocol:

```python
    async def get_conversation(
        self,
        *,
        agent_id: UUID,
        limit: int = 50,
        before: datetime | None = None,
    ) -> ConversationPage: ...
```

`InMemoryAgentStore.get_conversation` — сигнатура под новый протокол
(`before` вместо `offset`), существующая группировка сохраняется, финал:

```python
        turns.sort(key=lambda t: t.timestamp, reverse=True)
        page = turns[:limit]
        next_before = page[-1].timestamp if page else None
        return ConversationPage(turns=page, next_before=next_before)
```

- [ ] **Step 4: Implement DatabaseAgentStore**

`database_agent_store.get_conversation` переписать:

```python
    async def get_conversation(
        self,
        *,
        agent_id: UUID,
        limit: int = 50,
        before: datetime | None = None,
    ) -> ConversationPage:
        msg_fetch = limit * 4 + 60
        evt_fetch = limit * 8 + 120
        # Хелпер `_message_content` (строки 261-266 текущего метода) сохраняется:
        # пустой content у assistant разворачивается из payload.structured_response.
        async with self._session_factory() as db_session:
            msg_q = (
                select(AgentMessageModel)
                .where(AgentMessageModel.agent_id == agent_id)
                .order_by(AgentMessageModel.created_at.desc())
                .limit(msg_fetch)
            )
            evt_q = (
                select(AgentEventModel)
                .where(AgentEventModel.agent_id == agent_id)
                .where(AgentEventModel.event_type.not_in(["start_agent", "stop_agent"]))
                .order_by(AgentEventModel.created_at.desc())
                .limit(evt_fetch)
            )
            if before is not None:
                msg_q = msg_q.where(AgentMessageModel.created_at < before)
                evt_q = evt_q.where(AgentEventModel.created_at < before)
            recent_messages = list(reversed(list(await db_session.scalars(msg_q))))
            recent_events = list(reversed(list(await db_session.scalars(evt_q))))
        timeline = [
            ("msg", msg.created_at, msg) for msg in recent_messages
        ] + [("evt", evt.created_at, evt) for evt in recent_events]
        timeline.sort(key=lambda x: x[1])
        turns: list[ConversationTurn] = []
        current_turn: ConversationTurn | None = None
        for item_type, _ts, item in timeline:
            if item_type == "msg":
                msg = item
                content = _message_content(msg)
                media = [m for m in (msg.payload.get("media") or []) if isinstance(m, dict)]
                if msg.direction in ("incoming", "dashboard_trigger"):
                    if current_turn is not None:
                        turns.append(current_turn)
                    current_turn = ConversationTurn(
                        id=msg.id, agent_id=agent_id, timestamp=msg.created_at,
                        peer_id=str(msg.payload.get("peer", "")),
                        peer_name=str(msg.payload.get("peer_name", "")),
                        agent_name=str(msg.payload.get("agent_name", "")),
                        incoming=content, direction="incoming",
                        turn_id=str(msg.payload.get("turn_id") or "") or None,
                        incoming_media=media,
                    )
                elif msg.direction in ("agent_response", "outgoing"):
                    if current_turn is not None and current_turn.direction == "incoming":
                        current_turn.outgoing = content
                        current_turn.direction = "both"
                    else:
                        if current_turn is not None:
                            turns.append(current_turn)
                        current_turn = ConversationTurn(
                            id=msg.id, agent_id=agent_id, timestamp=msg.created_at,
                            peer_id=str(msg.payload.get("peer", "")),
                            peer_name=str(msg.payload.get("peer_name", "")),
                            agent_name=str(msg.payload.get("agent_name", "")),
                            outgoing=content, direction="outgoing",
                            turn_id=str(msg.payload.get("turn_id") or "") or None,
                        )
            else:
                evt = item
                duration_ms = 0.0
                if evt.started_at and evt.completed_at:
                    duration_ms = (evt.completed_at - evt.started_at).total_seconds() * 1000
                tool = ToolCallRecord(
                    id=evt.id,
                    name=evt.event_type,
                    status=evt.status,
                    payload=evt.payload or {},
                    result=evt.result,
                    error=evt.error,
                    duration_ms=duration_ms,
                    created_at=evt.created_at,
                )
                if current_turn is not None:
                    current_turn.tools.append(tool)
                else:
                    current_turn = ConversationTurn(
                        id=evt.id, agent_id=agent_id, timestamp=evt.created_at,
                        peer_id=str((evt.payload or {}).get("parent_peer", "")),
                        direction="tools", tools=[tool],
                    )
        if current_turn is not None:
            turns.append(current_turn)
        turns.sort(key=lambda t: t.timestamp, reverse=True)
        page = turns[:limit]
        next_before = None
        if page:
            next_before = page[-1].timestamp
        return ConversationPage(turns=page, next_before=next_before)
```

Ключевое отличие от текущего кода: нет `turns.reverse()` поверх offset/limit —
пагинация через `before` на обоих запросах, курсор = timestamp самого старого
хода страницы. Next-страница запрашивает строго старше курсора → ни ход не
разрезается (все элементы хода ≥ его timestamp), ни дубли.

Важно: `testing/server.py` и все прочие вызовы `get_conversation` обновляются под
новую сигнатуру (`before=` вместо `offset=`, возврат `ConversationPage`) — проверить
`rg -n "get_conversation" src tests`.

Важно: окно `msg_fetch`/`evt_fetch` может оборвать самый старый ход страницы
(таксономия ходов неполна) — приемлемо: элемент-«сирота» группируется в
tools-only ход, как сейчас; для главного сценария (limit ≤ 200) окна покрывают
4 ход-кратный запас.

- [ ] **Step 5: Run tests**

Run: `uv run pytest -m db tests/integration/test_agent_store_conversation.py tests/integration/test_database_agent_store.py -v`
Expected: PASS

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check src tests && uv run ty check
git add src/mimic42/core/agent_store.py src/mimic42/integrations/database_agent_store.py tests/integration/test_agent_store_conversation.py tests/integration/test_database_agent_store.py
git commit -m "feat: cursor-based conversation pagination with turn identity"
```

---

### Task 8: API — conversation endpoint и media endpoint

**Files:**
- Modify: `src/mimic42/api/app.py:156-167` (параметр `create_app`), `:495-506`
- Test: `tests/api/test_media_endpoint.py`

- [ ] **Step 1: Write the failing test**

Паттерн — как в `tests/api/test_dashboard_api.py:21-52`
(`create_app(agent_store=..., auth_verifier=FakeAuthVerifier(owner_id))` +
httpx `ASGITransport` + `AUTH_HEADERS`). Для медиа в `create_app` добавляется
параметр `media_uploader` (см. Step 2); тестовый фейк реализует протокол
`MediaUploader` в памяти.

```python
# tests/api/test_media_endpoint.py
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.agent_store import AgentRecord, InMemoryAgentStore
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier


class FakeMediaStorage:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    async def upload(self, *, agent_id, filename, data, mime_type, kind="doc"):
        return None

    async def open(self, path: str) -> bytes | None:
        return self._files.get(path)

    async def remove_prefix(self, agent_id) -> None:
        self._files.clear()


def _store_with_agent(owner_id, agent_id) -> InMemoryAgentStore:
    return InMemoryAgentStore(agents=[
        AgentRecord(agent_id=agent_id, owner_id=owner_id, name="Mimic",
                    state=AgentRuntimeState.STOPPED),
    ])


@pytest.mark.asyncio
async def test_media_returns_file_for_owner() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    path = f"{agent_id}/{uuid4()}/img.jpeg"
    app = create_app(
        agent_store=_store_with_agent(owner_id, agent_id),
        auth_verifier=FakeAuthVerifier(owner_id),
        media_uploader=FakeMediaStorage({path: b"IMG"}),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.get(f"/api/v1/agents/{agent_id}/media/{path}", headers=AUTH_HEADERS)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/jpeg")
    assert resp.content == b"IMG"


@pytest.mark.asyncio
async def test_media_rejects_path_of_other_agent() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    app = create_app(
        agent_store=_store_with_agent(owner_id, agent_id),
        auth_verifier=FakeAuthVerifier(owner_id),
        media_uploader=FakeMediaStorage({"other-agent/1/x.jpeg": b"X"}),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.get(
            f"/api/v1/agents/{agent_id}/media/other-agent/1/x.jpeg", headers=AUTH_HEADERS
        )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_media_404_when_file_missing() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    app = create_app(
        agent_store=_store_with_agent(owner_id, agent_id),
        auth_verifier=FakeAuthVerifier(owner_id),
        media_uploader=FakeMediaStorage({}),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.get(
            f"/api/v1/agents/{agent_id}/media/{agent_id}/nowhere.jpeg", headers=AUTH_HEADERS
        )

    assert resp.status_code == 404
```

- [ ] **Step 2: Implement conversation page endpoint**

В `app.py` заменить endpoint `get_agent_conversation`:

```python
    @app.get("/api/v1/agents/{agent_id}/conversation", response_model=ConversationPage)
    async def get_agent_conversation(
        agent_id: UUID,
        current_user: CurrentUserDep,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        before: Annotated[datetime | None, Query()] = None,
    ) -> ConversationPage:
        store = _get_agent_store(app)
        if store is None:
            return ConversationPage()
        await _ensure_agent_owner(store, agent_id=agent_id, user_id=current_user.user_id)
        return await store.get_conversation(agent_id=agent_id, limit=limit, before=before)
```

- [ ] **Step 3: Implement media endpoint**

```python
    @app.get("/api/v1/agents/{agent_id}/media/{media_path:path}")
    async def get_agent_media(
        agent_id: UUID,
        media_path: str,
        current_user: CurrentUserDep,
    ) -> Response:
        store = _get_agent_store(app)
        media_storage = getattr(_get_agent_manager(app), "media_uploader", None)
        if store is None or media_storage is None:
            raise HTTPException(status_code=404, detail="Медиа недоступно")
        await _ensure_agent_owner(store, agent_id=agent_id, user_id=current_user.user_id)
        # Объект обязан лежать внутри папки агента — иначе доступ к чужому файлу.
        if not media_path.startswith(f"{agent_id}/"):
            raise HTTPException(status_code=403, detail="Нет доступа к этому файлу")
        data = await media_storage.open(media_path)
        if data is None:
            raise HTTPException(status_code=404, detail="Файл не найден")
        mime = media_path.rsplit(".", 1)[-1].lower()
        content_types = {
            "jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "gif": "image/gif", "ogg": "audio/ogg",
            "mp4": "video/mp4", "pdf": "application/pdf",
        }
        return Response(
            content=data,
            media_type=content_types.get(mime, "application/octet-stream"),
        )
```

`AgentManager.media_uploader` — публичный атрибут, добавлен в Task 4.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/api -v`
Expected: PASS

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src tests && uv run ty check
git add src/mimic42/api/app.py tests/api/test_media_endpoint.py
git commit -m "feat: conversation page endpoint and media streaming endpoint"
```

---

### Task 9: Удаление медиа при удалении агента

**Files:**
- Modify: `src/mimic42/api/app.py` (endpoint удаления агента — найдите `delete_agent`)

- [ ] **Step 1: Implement**

В месте, где после успешного `delete_agent` вызывается остановка рантайма, добавить
нефатальную очистку Storage:

```python
        media_storage = getattr(_get_agent_manager(app), "media_uploader", None)
        if media_storage is not None:
            try:
                await media_storage.remove_prefix(agent_id)
            except Exception:
                logger.warning("Failed to remove media for agent %s", agent_id, exc_info=True)
```

- [ ] **Step 2: Run suite + commit**

```bash
uv run pytest tests/api -v
uv run ruff check src
git add src/mimic42/api/app.py
git commit -m "feat: remove stored media when agent is deleted"
```

---

### Task 10: Фронт — типы, api, хуки

**Files:**
- Modify: `frontend/src/types/index.ts:63-85`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/hooks/useActivityFeed.ts`
- Create: `frontend/src/hooks/useMediaUrl.ts`
- Delete: `frontend/src/hooks/useConversation.ts`

- [ ] **Step 1: Types**

В `types/index.ts` добавить (рядом с `ToolCallRecord`):

```ts
export interface MediaItem {
  kind: 'photo' | 'sticker' | 'voice' | 'round' | 'doc';
  name: string;
  mime_type: string;
  size: number;
  storage_path: string | null;
}
```

`ConversationTurn` — добавить:

```ts
  turn_id: string | null;
  incoming_media: MediaItem[];
```

- [ ] **Step 2: api.ts**

Заменить `getConversation` (блобы медиа запрашивает сам `useMediaUrl` через
`apiClient` — отдельный хелпер не нужен):

```ts
  async getConversation(agentId: string, limit: number, before?: string | null) {
    const params: Record<string, unknown> = { limit };
    if (before) params.before = before;
    const { data } = await apiClient.get<{ turns: ConversationTurn[]; next_before: string | null }>(
      `/agents/${agentId}/conversation`, { params });
    return data;
  },
```

- [ ] **Step 3: useActivityFeed.ts (курсорная бесконечная лента)**

```ts
'use client';

import { useInfiniteQuery } from '@tanstack/react-query';
import { agentsApi } from '@/lib/api';
import { queryKeys, HISTORICAL_STALE_TIME } from '@/lib/queryClient';
import { agentIdSchema } from '@/lib/validators';

const PAGE_SIZE = 50;

export function useActivityFeed(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useInfiniteQuery({
    queryKey: queryKeys.conversation.byAgent(agentId),
    queryFn: ({ pageParam }) => agentsApi.getConversation(agentId, PAGE_SIZE, pageParam ?? null),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_before ?? undefined,
    enabled: isValidId,
    staleTime: HISTORICAL_STALE_TIME,
  });
}

export const ACTIVITY_PAGE_SIZE = PAGE_SIZE;
```

- [ ] **Step 4: useMediaUrl.ts**

```ts
'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

/**
 * Загружает медиа-файл из activity-логов (с JWT) и отдаёт object URL.
 */
export function useMediaUrl(agentId: string, storagePath: string | null | undefined) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let revoked = false;
    let created: string | null = null;
    if (!storagePath) {
      setUrl(null);
      return;
    }
    apiClient
      .get(`/agents/${agentId}/media/${storagePath}`, { responseType: 'blob' })
      .then((res) => {
        if (revoked) return;
        created = URL.createObjectURL(res.data);
        setUrl(created);
      })
      .catch(() => setUrl(null));
    return () => {
      revoked = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [agentId, storagePath]);

  return url;
}
```

- [ ] **Step 5: Verify build**

Run: `bun run typecheck`
Expected: PASS (пока не удалён useConversation — удалите его вместе со старым
контейнером в Task 11; сейчас просто не импортируйте новый хук в старый код)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/lib/api.ts frontend/src/hooks/useActivityFeed.ts frontend/src/hooks/useMediaUrl.ts
git commit -m "feat(front): cursor activity feed and media url hooks"
```

---

### Task 11: normalize — единый построитель блоков

**Files:**
- Modify: `frontend/src/lib/activity/normalize.ts`
- Test: `frontend/src/__tests__/activity.test.ts`

- [ ] **Step 1: Failing tests (bun test)**

Добавить в `frontend/src/__tests__/activity.test.ts` (стиль проверок — как в
существующих тестах файла):

```ts
import { describe, it, expect } from 'bun:test';
import { buildActivityFeed, turnToActivityItem } from '@/lib/activity/normalize';
import type { ConversationTurn } from '@/types';

describe('activity feed', () => {
  it('resolves structured_response text as the response', () => {
    const items = buildActivityFeed(
      [{ id: '1', role: 'assistant', content: '', created_at: '2026-01-01T00:00:00Z',
         direction: 'agent_response', payload: { turn_id: 't1', structured_response: { text: 'Привет!' } } }],
      [],
    );
    expect(items[0].response?.content).toBe('Привет!');
  });

  it('falls back to a successful send_text_message tool call', () => {
    const items = buildActivityFeed(
      [{ id: '2', role: 'user', content: 'Вопрос', created_at: '2026-01-01T00:00:00Z',
         direction: 'incoming', payload: { turn_id: 't2' } }],
      [{ id: 'e1', event_type: 'tool.send_text_message', status: 'succeeded',
         created_at: '2026-01-01T00:00:05Z', payload: { turn_id: 't2', args: { message: 'Ответ тулзой' } } }],
    );
    expect(items[0].response?.content).toBe('Ответ тулзой');
  });

  it('carries incoming media from payload', () => {
    const items = buildActivityFeed(
      [{ id: '3', role: 'user', content: '[Фото id=photo:1:2:aa:5]', created_at: '2026-01-01T00:00:00Z',
         direction: 'incoming', payload: { turn_id: 't3', media: [
           { kind: 'photo', name: 'photo.jpeg', mime_type: 'image/jpeg', size: 3, storage_path: 'ag/1/p.jpeg' },
         ] } }],
      [],
    );
    expect(items[0].incomingMedia?.length).toBe(1);
    expect(items[0].incomingMedia?.[0].storage_path).toBe('ag/1/p.jpeg');
  });

  it('maps a backend turn into an ActivityItem preserving media', () => {
    const turn = {
      id: 'm1', agent_id: 'a', timestamp: '2026-01-01T00:00:00Z', turn_id: 't9',
      peer_id: '1', peer_name: 'Аня', agent_name: 'Мими', incoming: 'Привет',
      outgoing: 'Привет-привет', direction: 'both', tools: [], incoming_media: [
        { kind: 'photo', name: 'p.jpeg', mime_type: 'image/jpeg', size: 3, storage_path: 'ag/1/p.jpeg' },
      ],
    } as unknown as ConversationTurn;
    const item = turnToActivityItem(turn);
    expect(item.incomingMedia?.[0].storage_path).toBe('ag/1/p.jpeg');
    expect(item.response?.content).toBe('Привет-привет');
    expect(item.id).toBe('turn:t9');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun test src/__tests__/activity.test.ts`
Expected: FAIL — `incomingMedia is undefined` / `turnToActivityItem is not a function`

- [ ] **Step 3: Implement in normalize.ts**

`ActivityMessagePart` — добавить `media?: MediaItem[]`. `ActivityItem` — добавить
`incomingMedia?: MediaItem[]`.

`buildTurn`: после `responseMsg` вычислить structured-текст и fallback тулзы:

```ts
  const structuredOf = (msg: MessageLike | undefined): string => {
    const sr = msg?.payload?.structured_response;
    if (sr && typeof sr === 'object' && typeof (sr as { text?: unknown }).text === 'string') {
      return (sr as { text: string }).text;
    }
    return '';
  };

  let responseContent = responseMsg ? responseMsg.content : '';
  if (!responseContent && responseMsg) responseContent = structuredOf(responseMsg);
  if (!responseContent) {
    const sentTool = sortedEvents.find(
      (e) => e.event_type === 'tool.send_text_message' && e.status === 'succeeded',
    );
    const args = sentTool?.payload?.args;
    if (args && typeof args.message === 'string') responseContent = args.message;
  }
```

`response: responseMsg || responseContent ? { id: responseMsg?.id ?? responseId, content: responseContent, createdAt: ... } : null`.
Для отсутствующего responseMsg используйте `createdAt` найденного тулза-события.

`incomingMedia` — из payload входящего сообщения:

```ts
const mediaOf = (msg: MessageLike | undefined): MediaItem[] => {
  const media = msg?.payload?.media;
  return Array.isArray(media) ? (media as MediaItem[]) : [];
};
```

В `buildTurn` вернуть `incomingMedia: mediaOf(incomingMsg)`.

Новый маппер (переиспользует `toAction`, чтобы подписи/статусы совпадали с rest-вариантом; `ToolCallRecord.name` с бэкенда — это `event_type`, вида `tool.send_text_message`):

```ts
export function turnToActivityItem(turn: ConversationTurn): ActivityItem {
  const createdAt = new Date(turn.timestamp).toISOString();
  const toActionRow = (tool: ToolCallRecord) =>
    toAction({
      id: tool.id,
      event_type: tool.name,
      status: tool.status,
      created_at: tool.created_at,
      error: tool.error,
      payload: (tool.payload ?? null) as Record<string, unknown> | null,
      result: (tool.result ?? null) as Record<string, unknown> | null,
      started_at: tool.created_at,
      completed_at: tool.created_at,
    } as unknown as EventLike);

  return {
    kind: 'turn',
    id: turn.turn_id ? `turn:${turn.turn_id}` : `msg:${turn.id}`,
    agentId: turn.agent_id,
    turnId: turn.turn_id ?? null,
    peer: turn.peer_id,
    peerTitle: turn.peer_name || null,
    createdAt,
    endedAt: null,
    failed: turn.tools.some((t) => t.status === 'failed'),
    incoming: turn.incoming
      ? { id: turn.id, content: turn.incoming, createdAt, media: turn.incoming_media ?? [] }
      : null,
    response: turn.outgoing
      ? { id: `${turn.id}-out`, content: turn.outgoing, createdAt }
      : null,
    trigger: null,
    incomingMedia: turn.incoming_media ?? [],
    actions: turn.tools.map(toActionRow),
  };
}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `bun test src/__tests__/activity.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/activity/normalize.ts frontend/src/__tests__/activity.test.ts
git commit -m "feat(front): unified turn builder with responses and media"
```

---

### Task 12: MediaContent + лайтбокс

**Files:**
- Create: `frontend/src/components/activity/MediaContent.tsx`

- [ ] **Step 1: Implement**

```tsx
'use client';

import { useState } from 'react';
import { File } from 'lucide-react';
import { useMediaUrl } from '@/hooks/useMediaUrl';
import { Modal } from '@/components/ui/modal';
import type { MediaItem } from '@/types';

const IMAGE_KINDS = new Set(['photo', 'sticker']);

function MediaView({ agentId, item }: { agentId: string; item: MediaItem }) {
  const url = useMediaUrl(agentId, item.storage_path);

  if (!item.storage_path) {
    return (
      <span className="inline-flex items-center gap-1.5 font-mono text-[10px] text-void-500 border border-void-700 rounded-sm px-2 py-1">
        <File className="h-3 w-3" />
        {item.name} (файл не сохранён)
      </span>
    );
  }
  if (!url) {
    return <span className="font-mono text-[10px] text-void-600">Загрузка медиа…</span>;
  }

  if (IMAGE_KINDS.has(item.kind)) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={url} alt={item.name} className="max-h-40 rounded-sm border border-void-800" />
    );
  }
  if (item.kind === 'voice') {
    return <audio controls src={url} className="h-9 max-w-full" />;
  }
  if (item.kind === 'round') {
    return <video controls src={url} className="max-w-40 rounded-sm border border-void-800" />;
  }
  return (
    <a
      href={url}
      download={item.name}
      className="inline-flex items-center gap-1.5 font-mono text-[10px] text-plasma-400 hover:text-plasma-300 border border-void-800 px-2 py-1 rounded-sm"
    >
      <File className="h-3 w-3" />
      {item.name} · {Math.max(1, Math.round(item.size / 1024))} КБ
    </a>
  );
}

export function MediaContent({ agentId, items }: { agentId: string; items: MediaItem[] }) {
  const [preview, setPreview] = useState<MediaItem | null>(null);
  if (!items?.length) return null;

  const imagePreview = preview && IMAGE_KINDS.has(preview.kind);

  return (
    <div className="flex flex-wrap items-center gap-2">
      {items.map((item, i) =>
        IMAGE_KINDS.has(item.kind) ? (
          <button
            key={`${item.storage_path ?? i}-${item.name}`}
            type="button"
            onClick={() => setPreview(item)}
            className="cursor-zoom-in"
          >
            <MediaView agentId={agentId} item={item} />
          </button>
        ) : (
          <MediaView key={`${item.storage_path ?? i}-${item.name}`} agentId={agentId} item={item} />
        ),
      )}
      <Modal
        isOpen={preview !== null && imagePreview}
        onClose={() => setPreview(null)}
        title={preview?.name ?? ''}
        size="lg"
      >
        {imagePreview && <LightboxImage agentId={agentId} item={preview!} />}
      </Modal>
    </div>
  );
}

function LightboxImage({ agentId, item }: { agentId: string; item: MediaItem }) {
  const url = useMediaUrl(agentId, item.storage_path);
  if (!url) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt={item.name} className="max-h-[70vh] w-auto mx-auto" />
  );
}
```

(Кнопкой-превью обёрнуты только фото/стикеры — клик открывает лайтбокс; аудио,
видео и файлы рендерятся напрямую. `cn` при этом больше не нужен в импортах —
уберите его. Сверстайте по Taste: превью не должно растягивать блок.)

- [ ] **Step 2: Verify + commit**

Run: `bun run typecheck && bun run lint`
Expected: PASS

```bash
git add frontend/src/components/activity/MediaContent.tsx
git commit -m "feat(front): media previews for activity feed"
```

---

### Task 13: TurnCard — порядок внутри блока, медиа, chatOnly

**Files:**
- Modify: `frontend/src/components/activity/TurnCard.tsx`

- [ ] **Step 1: Rework collapsed body (newest-first)**

Проп `chatOnly` добавляется к сигнатуре:

```tsx
export function TurnCard({
  item,
  defaultOpen = false,
  chatOnly = false,
}: {
  item: ActivityItem;
  defaultOpen?: boolean;
  chatOnly?: boolean;
}) {
```

Порядок внутри `<button>`: (1) ответ агента, (2) тулзы (`[...item.actions].reverse()` —
новые сверху), (3) входящее/триггер — внизу блока. Медиа — под входящим сообщением:

```tsx
        {item.response && (
          <p className="text-xs text-neon-300/90 leading-relaxed line-clamp-2">
            {sanitizeText(item.response.content)}
          </p>
        )}

        {!chatOnly && item.actions.length > 0 && (
          <div className="mt-1.5 space-y-0.5">
            {[...item.actions].reverse().map((action) => (
              <ActionRow key={action.id} action={action} />
            ))}
          </div>
        )}

        {item.incoming && (
          <p className="mt-1.5 text-xs text-void-100 leading-relaxed line-clamp-2">
            <CornerDownRight className="h-3 w-3 inline mr-1.5 text-plasma-500 -mt-0.5" />
            {sanitizeText(incomingBody(item.incoming.content))}
          </p>
        )}
        {item.incoming?.media?.length ? (
          <MediaContent agentId={item.agentId ?? ''} items={item.incoming.media} />
        ) : null}
```

В раскрытой секции порядок: Ответ → Действия (секции действий тоже под `!chatOnly`)
→ Входящее (единое направление), медиа в секции «Входящее».

`ActivityItem.agentId` обязателен для MediaContent: в normalize это уже поле.

- [ ] **Step 2: Verify + commit**

Run: `bun test src/__tests__/activity.test.ts && bun run typecheck`
Expected: PASS

```bash
git add frontend/src/components/activity/TurnCard.tsx
git commit -m "feat(front): newest-first turn body with media previews"
```

---

### Task 14: TabActivity — единый контейнер

**Files:**
- Create: `frontend/src/components/activity/TabActivity.tsx`
- Delete: `frontend/src/components/agent/TabLogs.tsx`, `frontend/src/components/chat/TabLogsChat.tsx`, `frontend/src/components/chat/ConversationThread.tsx`, `frontend/src/components/chat/ChatBubble.tsx`, `frontend/src/hooks/useConversation.ts`

- [ ] **Step 1: Implement container**

```tsx
'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Wifi, WifiOff } from 'lucide-react';
import { useActivityFeed } from '@/hooks/useActivityFeed';
import { useRealtimeFeed } from '@/hooks/useRealtimeFeed';
import { useMessageThreads } from '@/hooks/useTelegramSession';
import { Card, Spinner } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { TurnCard } from './TurnCard';
import { buildActivityFeed, turnToActivityItem, type ActivityItem } from '@/lib/activity/normalize';
import { cn } from '@/lib/utils';

type FeedFilter = 'full' | 'chat';

const FILTER_LABELS: Record<FeedFilter, string> = { full: 'Полный', chat: 'Только чат' };

function isDialog(item: ActivityItem): boolean {
  return Boolean(item.incoming || item.trigger || item.response);
}

export function TabActivity({ agentId }: { agentId: string }) {
  const { data, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } = useActivityFeed(agentId);
  const { items: realtimeItems, isConnected } = useRealtimeFeed(agentId);
  const { data: threads } = useMessageThreads(agentId);

  const [filter, setFilter] = useState<FeedFilter>('full');
  const [search, setSearch] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const topRef = useRef<HTMLDivElement>(null);
  const loadMoreRef = useRef<HTMLDivElement>(null);

  const peerNames = useMemo(
    () => new Map((threads ?? []).filter((t) => t.title).map((t) => [t.telegram_peer_id, t.title as string])),
    [threads],
  );

  const items = useMemo(() => {
    const historical = (data?.pages ?? []).flatMap((page) =>
      page.turns.map((turn) => {
        const item = turnToActivityItem(turn);
        item.peerTitle = item.peerTitle ?? peerNames.get(item.peer) ?? null;
        return item;
      }),
    );
    const seen = new Set(historical.map((i) => i.id));
    const realtime = realtimeItems.filter((i) => !seen.has(i.id));
    const merged = [...realtime, ...historical];
    merged.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
    return merged;
  }, [data?.pages, realtimeItems, peerNames]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter((item) => {
      if (filter === 'chat' && !isDialog(item)) return false;
      if (q && !matchesSearch(item, q)) return false;
      return true;
    });
  }, [items, filter, search]);

  const handleLoadMore = () => {
    if (!hasNextPage || isFetchingNextPage) return;
    fetchNextPage();
  };

  useEffect(() => {
    if (autoScroll) topRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [items.length, autoScroll]);

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row gap-3">
        <Input placeholder="Поиск по содержимому..." value={search}
          onChange={(e) => setSearch(e.target.value)} className="sm:max-w-xs" />
        <div className="flex items-center gap-1">
          {(Object.keys(FILTER_LABELS) as FeedFilter[]).map((f) => (
            <button key={f} data-testid={`log-filter-${f}`} onClick={() => setFilter(f)}
              className={cn('px-3 py-1.5 rounded-sm font-mono text-xs border transition-colors',
                filter === f ? 'bg-plasma-950 border-plasma-800 text-plasma-400'
                  : 'border-void-700 text-void-500 hover:text-void-300 hover:border-void-600')}>
              {FILTER_LABELS[f]}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 ml-auto">
          <button onClick={() => setAutoScroll((v) => !v)}
            className={cn('font-mono text-xs px-3 py-1.5 rounded-sm border transition-colors',
              autoScroll ? 'border-neon-800 text-neon-500' : 'border-void-700 text-void-600')}>
            {autoScroll ? '⬇ Авто-скролл' : '— Авто-скролл'}
          </button>
          <div className="flex items-center gap-1.5">
            {isConnected ? <Wifi className="h-3.5 w-3.5 text-neon-400" /> : <WifiOff className="h-3.5 w-3.5 text-void-600" />}
            <span className={cn('font-mono text-[10px]', isConnected ? 'text-neon-500' : 'text-void-600')}>
              {isConnected ? 'LIVE' : 'OFFLINE'}
            </span>
          </div>
        </div>
      </div>

      <Card variant="glass" padding="none">
        <div className="h-[640px] overflow-y-auto" data-testid="activity-feed">
          <div ref={topRef} />
          {isLoading ? (
            <div className="flex items-center justify-center h-full"><Spinner /></div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-void-600 gap-2">
              <Activity className="h-8 w-8 opacity-30" />
              <p>Нет записей</p>
            </div>
          ) : (
            <>
              {filtered.map((item) => (
                <TurnCard key={item.id} item={item} chatOnly={filter === 'chat'} />
              ))}
              <div ref={loadMoreRef} className="py-3 text-center">
                {isFetchingNextPage ? (
                  <Spinner className="inline-block" />
                ) : hasNextPage ? (
                  <button onClick={handleLoadMore}
                    className="font-mono text-xs text-void-500 hover:text-void-300 transition-colors">
                    Загрузить ещё
                  </button>
                ) : null}
              </div>
            </>
          )}
        </div>
      </Card>

      <p className="font-mono text-xs text-void-600 text-right">{filtered.length} записей</p>
    </div>
  );
}
```

Фильтр «Только чат»: скрывает тулзы внутри блоков и блоки без сообщений —
реализуется в TurnCard пропом:

```tsx
// TurnCard props: { item, chatOnly?: boolean }
// Свёрнутый вид:  {!chatOnly && item.actions.length > 0 && (... ActionRow ...)}
// Раскрытый вид:  {!chatOnly && <section>Действия ...</section>}
```

Т.е. `TabActivity` передаёт `chatOnly={filter === 'chat'}` в `TurnCard`;
тулза-only блоки отсеиваются `isDialog` (они не пройдут фильтр «Только чат»).

`matchesSearch` (по аналогии с прежним `TabLogs.tsx:32-40`):

```ts
function matchesSearch(item: ActivityItem, q: string): boolean {
  if (item.peerTitle?.toLowerCase().includes(q)) return true;
  if (item.incoming?.content.toLowerCase().includes(q)) return true;
  if (item.response?.content.toLowerCase().includes(q)) return true;
  if (item.trigger?.content.toLowerCase().includes(q)) return true;
  return item.actions.some(
    (a) => a.label.toLowerCase().includes(q) || a.hint?.toLowerCase().includes(q),
  );
}
```

- [ ] **Step 2: Verify + commit**

Run: `bun test src/__tests__/activity.test.ts && bun run typecheck`
Expected: PASS

```bash
git rm frontend/src/components/agent/TabLogs.tsx frontend/src/components/chat/TabLogsChat.tsx frontend/src/components/chat/ConversationThread.tsx frontend/src/components/chat/ChatBubble.tsx frontend/src/hooks/useConversation.ts
git add frontend/src/components/activity/TabActivity.tsx
git commit -m "feat(front): unified activity feed container"
```

---

### Task 15: Страница агента, дашборд, e2e

**Files:**
- Modify: `frontend/src/app/(dashboard)/agent/[id]/page.tsx:43-50,77,136-158`
- Modify: `frontend/src/app/(dashboard)/dashboard/page.tsx:88`
- Modify: `frontend/e2e/agent.spec.ts:43-45,57-85,121-127`

- [ ] **Step 1: page.tsx**

В `TABS`: `{ id: 'logs', label: 'Активность', icon: Activity }` (импорт `Activity` из
lucide-react вместо `ScrollText` для этой вкладки). Удалить `logsView` state и
под-вкладки; рендер:

```tsx
        {activeTab === 'logs'      && <TabActivity  agentId={agentId} />}
```

Импорт: `import { TabActivity } from '@/components/activity/TabActivity';`.
Удалить импорты `TabLogsChat` и `TabLogs`.

- [ ] **Step 2: dashboard link**

`dashboard/page.tsx:88`: `?tab=logs&filter=errors` → `?tab=logs`.

- [ ] **Step 3: e2e**

`agent.spec.ts`:
- «switches tabs» — `log-filter-all` заменяется на `log-filter-full`.
- «log filters narrow the feed» — фильтры: `log-filter-chat` скрывает тулзу-only блок
  (`tool.get_dialogs` failed → блок тулзы; он пропадает), `log-filter-full` возвращает.
  Тестовый сценарий: seed те же; `filter=errors` убрать; проверки:

```ts
    await page.goto(`/agent/${agentId}?tab=logs`);
    await expect(page.getByText('Здравствуйте!')).toBeVisible();

    await page.getByTestId('log-filter-chat').click();
    await expect(page.getByText('Здравствуйте!')).toBeVisible();
    await expect(page.getByText('Получил список диалогов')).toHaveCount(0);

    await page.getByTestId('log-filter-full').click();
    await expect(page.getByText('Здравствуйте!')).toBeVisible();
```

(Лейбл тулзы возьмите из `toolCatalog` для `get_dialogs` — сверьте фактическую
строку в каталоге; `data-testid` рендерится самим контейнером как
`log-filter-${f}`.)
- «logs tab shows the empty state» — текст «Нет записей» остаётся.

- [ ] **Step 4: toolCatalog покрытие**

Прогнать все `StructuredTool` имена (91 тулза) через каталог: `rg -o 'name="[a-z_]+"' src/mimic42/integrations/telegram_tools.py`, сравнить с ключами `TOOL_META` в `frontend/src/lib/activity/toolCatalog.ts`; добавить недостающие записи (label `ru`, hint-форматер). Сырые имена `<tool.*>` в UI не выводятся.

- [ ] **Step 5: Verify + commit**

Run: `bun run lint && bun run typecheck && bun test && uv run pytest -q`
Expected: PASS. Playwright e2e: `bun run test:e2e` — требует окружения e2e (`.env.test`, мок-телега); запуск по availability, см. README.

```bash
git add -A frontend
git commit -m "feat(front): rename logs tab to unified activity, fix filters"
```

---

### Task 16: Финальная проверка и PR

- [ ] **Step 1: Полный свип**

```bash
uv run ruff check src tests
uv run ty check
uv run pytest -q
cd frontend && bun run lint && bun run typecheck && bun test
```
Expected: всё зелёное. `bun run build` для финальной сборки Next.

- [ ] **Step 2: Пуш и PR**

```bash
git push -u origin feat/unified-activity-feed
gh pr create --repo 42-Z/Mimic42 --base main --title "Активность: единая лента вместо вкладок Логов (#59)" --body "Closes #59"
```

Пункты PR-описания: объединение вкладок, курсорная пагинация, финальные ответы,
медиа в Storage + просмотр из ленты, фильтры Полный/Только чат, миграция бакета.
