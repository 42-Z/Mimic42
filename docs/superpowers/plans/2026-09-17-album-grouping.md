# Album Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Альбом из нескольких картинок обрабатывается агентом как одно сообщение (один ход, один ответ), а в ленте «Активность» несколько картинок показываются в ряд горизонтально уменьшенными превью.

**Architecture:** Telegram-альбом — это N отдельных сообщений с одинаковым `grouped_id`. В `MimicAgentRuntime` добавляется буфер (`AlbumGrouper`): элементы альбома копятся по ключу `(chat_id, grouped_id)`, через «тихое окно» (продлевается на каждый новый элемент, жёсткий кап от первого) flush-задача отдаёт их в общий обработчик одним списком. Тело `_handle_incoming_message` переезжает в `_process_incoming(events)`: метаданные от первого события, тексты/медиа всех элементов конкатенируются. На фронте `MediaContent` рендерит галерею: >1 картинок — компактные превью в горизонтальном ряду с прокруткой, лайтбокс по клику сохраняется.

**Tech Stack:** Python (asyncio, telethon 1.43.2, pytest), Next.js 14 + React 18 + Tailwind (bun test + @testing-library/react + happy-dom).

**Ветка:** `feat/unified-activity-feed` (остаёмся в ней; НЕ пушить — ревьюит пользователь; e2e Playwright не запускать).

**Документация, проверенная при проектировании:** docs.telethon.dev/en/stable (Update Events — `events.Album`/`AlbumHack`, Concepts/Updates — sequential updates, Custom package — `Message.grouped_id`, Client Reference/Uploads), tl.telethon.dev (Message, SendMultiMediaRequest, InputSingleMedia), core.telegram.org (constructor/message `grouped_id:flags.17?long`, /api/files#albums-grouped-media — максимум 10 элементов, подписи per-item), гайд миграции Telethon v2 (официальная рекомендация — ручной буфер, а не `events.Album`).

---

### Task 1: AlbumGrouper — буфер альбома с тихим окном

**Files:**
- Create: `src/mimic42/core/album_grouper.py`
- Test: `tests/core/test_album_grouper.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_album_grouper.py`:

```python
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mimic42.core.album_grouper import AlbumGrouper


class Recorder:
    def __init__(self) -> None:
        self.flushed: list[list[Any]] = []

    async def flush(self, events: list[Any]) -> None:
        self.flushed.append(events)


@pytest.mark.asyncio
async def test_album_items_flush_together_after_quiet_window() -> None:
    recorder = Recorder()
    grouper = AlbumGrouper(recorder.flush, quiet_window=0.05, max_window=0.5)

    for i in range(3):
        grouper.add(("chat", "1"), f"event-{i}")
        await asyncio.sleep(0.02)

    await asyncio.sleep(0.4)

    assert recorder.flushed == [["event-0", "event-1", "event-2"]]


@pytest.mark.asyncio
async def test_interleaved_albums_flush_separately() -> None:
    recorder = Recorder()
    grouper = AlbumGrouper(recorder.flush, quiet_window=0.05, max_window=0.5)

    grouper.add(("chat", "1"), "a-1")
    grouper.add(("chat", "2"), "b-1")
    grouper.add(("chat", "1"), "a-2")
    grouper.add(("other", "2"), "c-1")

    await asyncio.sleep(0.4)

    batches = {tuple(sorted(batch)) for batch in recorder.flushed}
    assert batches == {("a-1", "a-2"), ("b-1",), ("c-1",)}


@pytest.mark.asyncio
async def test_item_after_flush_starts_a_new_buffer() -> None:
    recorder = Recorder()
    grouper = AlbumGrouper(recorder.flush, quiet_window=0.05, max_window=0.5)

    grouper.add(("chat", "1"), "first")
    await asyncio.sleep(0.4)
    assert recorder.flushed == [["first"]]

    # Опоздавший элемент после доставки не теряется — начинает новый буфер.
    grouper.add(("chat", "1"), "late")
    await asyncio.sleep(0.4)
    assert recorder.flushed == [["first"], ["late"]]


@pytest.mark.asyncio
async def test_close_cancels_pending_buffers_without_flushing() -> None:
    recorder = Recorder()
    grouper = AlbumGrouper(recorder.flush, quiet_window=0.05, max_window=30.0)

    grouper.add(("chat", "1"), "pending")
    await grouper.close()
    await asyncio.sleep(0.1)

    assert recorder.flushed == []


@pytest.mark.asyncio
async def test_max_window_caps_extensions() -> None:
    recorder = Recorder()
    grouper = AlbumGrouper(recorder.flush, quiet_window=0.15, max_window=0.3)

    grouper.add(("chat", "1"), "first")
    # Элементы приходят дольше капа: flush обязан случиться не позже капа.
    for i in range(6):
        await asyncio.sleep(0.1)
        grouper.add(("chat", "1"), f"late-{i}")

    await asyncio.sleep(0.5)

    assert recorder.flushed, "flush должен был случиться"
    first = recorder.flushed[0]
    assert first[0] == "first"
    # До капа успели доехать не все: часть осталась на отдельный буфер/потеряна
    # в этой доставке, но flush случился и не завис навсегда.
    assert len(first) < 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_album_grouper.py -q`
Expected: FAIL с `ModuleNotFoundError: No module named 'mimic42.core.album_grouper'`

- [ ] **Step 3: Write the implementation**

Create `src/mimic42/core/album_grouper.py`:

```python
"""Группировка элементов Telegram-альбома в одно событие.

Альбом на уровне API — это несколько отдельных сообщений с одинаковым
``grouped_id`` (core.telegram.org/api/files#albums-grouped-media). Официальная
рекомендация Telethon (гайд миграции на v2) — буферизовать их самостоятельно:
«тихое окно», продлеваемое каждым новым элементом, плюс жёсткий предел на весь
буфер от момента прибытия первого элемента. Опоздавший после доставки элемент
начинает новый буфер и обрабатывается отдельным ходом — ничего не теряется.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

logger = logging.getLogger("mimic42.album_grouper")

# Сколько ждём тишины после последнего элемента и сколько всего ждём от первого.
# Встроенный events.Album в Telethon ждёт 0.5 c и опоздавших теряет; документация
# отмечает, что задержки между элементами могут превышать секунду.
QUIET_WINDOW = 1.0
MAX_WINDOW = 4.0

AlbumKey = tuple[str, str]


class AlbumGrouper:
    """Буферизует элементы альбома по (chat_id, grouped_id) и отдаёт их разом."""

    def __init__(
        self,
        flush: Callable[[list[Any]], Awaitable[None]],
        *,
        quiet_window: float | None = None,
        max_window: float | None = None,
        now: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        # Значения по умолчанию читаются в момент вызова (sentinel None), чтобы
        # тесты могли monkeypatch-нуть константы модуля до создания рантайма.
        self._flush = flush
        self._quiet = QUIET_WINDOW if quiet_window is None else quiet_window
        self._cap = MAX_WINDOW if max_window is None else max_window
        self._now = now if now is not None else self._loop_time
        self._sleep = sleep if sleep is not None else asyncio.sleep
        self._events: dict[AlbumKey, list[Any]] = {}
        self._deadlines: dict[AlbumKey, float] = {}
        self._tasks: dict[AlbumKey, asyncio.Task[None]] = {}

    @staticmethod
    def _loop_time() -> float:
        return asyncio.get_running_loop().time()

    def add(self, key: AlbumKey, event: Any) -> None:
        """Положить элемент альбома в буфер; первый элемент планирует flush."""
        now = self._now()
        if key in self._events:
            self._events[key].append(event)
            # Окно отсчитывается от последнего элемента, но не дальше капа,
            # зафиксированного на момент прибытия первого.
            self._deadlines[key] = min(self._deadlines[key], now + self._quiet)
            return
        self._events[key] = [event]
        self._deadlines[key] = now + self._cap
        self._tasks[key] = asyncio.create_task(self._flush_after(key))

    async def close(self) -> None:
        """Отменить незавершённые буферы (при остановке агента)."""
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        dropped = sum(len(events) for events in self._events.values())
        self._events.clear()
        self._deadlines.clear()
        if dropped:
            logger.warning("Dropped %d buffered album item(s) on close", dropped)

    async def _flush_after(self, key: AlbumKey) -> None:
        try:
            while True:
                delay = self._deadlines.get(key, 0.0) - self._now()
                if delay <= 0:
                    break
                await self._sleep(delay)
        except asyncio.CancelledError:
            raise
        except KeyError:  # буфер уже забран/закрыт
            return
        events = self._events.pop(key, [])
        self._deadlines.pop(key, None)
        self._tasks.pop(key, None)
        if not events:
            return
        try:
            await self._flush(events)
        except Exception:
            logger.exception("Album flush failed for key %s", key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_album_grouper.py -q`
Expected: 5 passed

- [ ] **Step 5: Lint**

Run: `uv run ruff check src tests && uv run ty check`
Expected: All checks passed!

- [ ] **Step 6: Commit**

```bash
git add src/mimic42/core/album_grouper.py tests/core/test_album_grouper.py
git commit -m "feat: album grouper buffers Telegram media groups by grouped_id"
```

---

### Task 2: Рантайм — альбом идёт одним ходом

**Files:**
- Modify: `src/mimic42/core/agent_runtime.py` (`__init__` ~строка 168, `stop()` ~255-287, `_handle_incoming_message` ~643-980)
- Modify: `src/mimic42/testing/telegram/account.py` (`IncomingMessage`, `FakeIncomingEvent`)
- Test: `tests/core/test_agent_runtime.py` (новые тесты в конце файла)

- [ ] **Step 1: Добавить grouped_id в фейковые события**

В `src/mimic42/testing/telegram/account.py`:

```python
@dataclass
class IncomingMessage:
    chat_id: int
    message_id: int
    text: str
    sender_id: int
    reply_to_msg_id: int | None = None
    grouped_id: int | None = None
    order: int = 0
```

В `FakeIncomingEvent.__init__` после `self.client = client` добавить:

```python
        self.grouped_id = message.grouped_id
```

- [ ] **Step 2: Write the failing tests**

В конец `tests/core/test_agent_runtime.py` добавить импорт asyncio к существующим (вверху файла `import asyncio` — проверить, что он есть; если нет — добавить) и два теста:

```python
@pytest.mark.asyncio
async def test_incoming_album_becomes_single_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Альбом из трёх сообщений = один ход и один ответ агента."""
    monkeypatch.setattr("mimic42.core.album_grouper.QUIET_WINDOW", 0.05)
    monkeypatch.setattr("mimic42.core.album_grouper.MAX_WINDOW", 0.5)

    telegram = FakeTelegramClient()
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(response="один ответ"),
    )
    await runtime.start()

    async def mock_peer(ev: Any) -> str:
        return "12345"

    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_peer", mock_peer)
    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_message_id", lambda ev: ev.id)

    for i in range(3):
        message = IncomingMessage(
            chat_id=12345,
            message_id=700 + i,
            text=f"caption {i}" if i == 0 else "",
            sender_id=999,
            grouped_id=555,
        )
        await telegram.emit_message(FakeIncomingEvent(message, client=telegram))

    await asyncio.sleep(0.3)
    await runtime.stop()

    assert len(runtime._langchain_agent.inputs) == 1  # type: ignore
    prompt_text = runtime._langchain_agent.inputs[0]["messages"][-1]["content"]  # type: ignore
    assert "Альбом из 3 файлов" in prompt_text
    assert "Содержимое: caption 0" in prompt_text


@pytest.mark.asyncio
async def test_incoming_single_message_is_not_buffered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обычное сообщение (без grouped_id) обрабатывается сразу, как раньше."""
    telegram = FakeTelegramClient()
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(response="ok"),
    )
    await runtime.start()

    async def mock_peer(ev: Any) -> str:
        return "12345"

    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_peer", mock_peer)
    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_message_id", lambda ev: ev.id)

    message = IncomingMessage(chat_id=12345, message_id=800, text="просто текст", sender_id=999)
    await telegram.emit_message(FakeIncomingEvent(message, client=telegram))

    assert len(runtime._langchain_agent.inputs) == 1  # type: ignore
    await runtime.stop()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/core/test_agent_runtime.py::test_incoming_album_becomes_single_turn tests/core/test_agent_runtime.py::test_incoming_single_message_is_not_buffered -q`
Expected: album-тест FAIL (`Альбом из 3 файлов` не найден; `inputs == 3` — три отдельных хода). single-тест PASS (регрессия уже зелёная).

- [ ] **Step 4: Импорт и состояние в `MimicAgentRuntime`**

В `src/mimic42/core/agent_runtime.py` добавить импорт рядом с остальными локальными:

```python
from mimic42.core.album_grouper import AlbumGrouper
```

В `__init__` после строки `self._http_client: Any | None = None` добавить:

```python
        self._album_grouper = AlbumGrouper(self._flush_album)
```

- [ ] **Step 5: Остановка — отмена буферов**

В `stop()` после блока отмены `self._scheduler_task` и ДО закрытия `self._http_client` добавить:

```python
                await self._album_grouper.close()
```

- [ ] **Step 6: Разделение хендлера на маршрут и обработку**

Переименовать тело `_handle_incoming_message` в новый метод `_process_incoming(self, events: list[TelegramEventLike])` и сделать `_handle_incoming_message` маршрутизатором:

```python
    async def _handle_incoming_message(self, event: TelegramEventLike) -> None:
        """Альбомы буферизуются, одиночные сообщения обрабатываются сразу."""
        grouped_id = getattr(event, "grouped_id", None)
        if grouped_id is None:
            await self._process_incoming([event])
            return
        chat_id = getattr(event, "chat_id", None)
        self._album_grouper.add((str(chat_id), str(grouped_id)), event)

    async def _flush_album(self, events: list[TelegramEventLike]) -> None:
        """Буфер альбома доставлен — обработать элементы одним ходом."""
        logger.info(
            "Grouped album with %d item(s) from chat %s",
            len(events),
            getattr(events[0], "chat_id", None),
        )
        try:
            await self._process_incoming(events)
        except Exception:
            logger.exception("Failed to process grouped album")

    async def _process_incoming(self, events: list[TelegramEventLike]) -> None:
        event = events[0]
        ... # дальше — прежнее тело _handle_incoming_message с правками ниже
```

Правки внутри `_process_incoming`:

1. Блок обработки медиа (сейчас единственный вызов `_process_media_and_text`) заменить на конкатенацию по всем элементам:

```python
            merged_content: list[str] = []
            merged_raw: list[str] = []
            media_files: list[MediaFile] = []
            for item in events:
                item_raw = getattr(item, "raw_text", None) or getattr(item, "text", None)
                if not isinstance(item_raw, str):
                    item_raw = ""
                if item_raw:
                    merged_raw.append(item_raw)
                item_text, item_media = await _process_media_and_text(
                    item,
                    item_raw,
                    http_client=self._http_client,
                    media_uploader=self._media_uploader,
                    agent_id=self.config.agent_id,
                )
                if item_text:
                    merged_content.append(item_text)
                media_files.extend(item_media)

            raw_text = "\n".join(merged_raw)
            text = "\n".join(merged_content)
```

(Дальше существующая проверка `if not text: ... return` остаётся как была.)

2. Перед формированием текста (рядом с `incoming_msg_id = _extract_incoming_message_id(event)`) добавить заметку альбома:

```python
            album_note = ""
            if len(events) > 1:
                item_ids = [
                    str(item_id)
                    for item in events
                    if (item_id := _extract_incoming_message_id(item)) is not None
                ]
                album_note = f"Альбом из {len(events)} файлов (ID: {', '.join(item_ids)})\n"
```

3. В шапку сообщения вставить `album_note` после строки `ID сообщения:`:

```python
            incoming_msg_id = _extract_incoming_message_id(event)
            text = (
                f"[Входящее сообщение]\n"
                f"Время: {time_str}\n"
                f"Чат: {chat_type_str}\n"
                f"Отправитель: {sender_str}\n"
                f"ID сообщения: {incoming_msg_id}\n"
                f"{album_note}"
                f"{reply_str}"
                f"Содержимое: {text}"
            )
```

4. Всё остальное (mute-чек, sender/chat/thread, reply-аннотация, `trigger_message`, catch-all с `turn.failed`) остаётся без изменений — `event` везде означает `events[0]`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_agent_runtime.py -q`
Expected: все тесты файла PASS, включая оба новых (одиночные сообщения — регрессия зелёная).

- [ ] **Step 8: Lint и типы**

Run: `uv run ruff check src tests && uv run ty check`
Expected: All checks passed!

- [ ] **Step 9: Commit**

```bash
git add src/mimic42/core/agent_runtime.py src/mimic42/testing/telegram/account.py tests/core/test_agent_runtime.py
git commit -m "feat: process incoming Telegram albums as a single agent turn"
```

---

### Task 3: Фронт — несколько картинок в ряд, компактные

**Files:**
- Modify: `frontend/src/components/activity/MediaContent.tsx`
- Test: `frontend/src/__tests__/media-content.test.tsx` (новый файл)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/media-content.test.tsx`:

```tsx
import { describe, expect, test } from 'bun:test';
import { render, screen, within } from '@testing-library/react';
import { MediaContent } from '@/components/activity/MediaContent';
import type { MediaItem } from '@/types';

function item(kind: MediaItem['kind'], name: string): MediaItem {
  return {
    kind,
    name,
    mime_type: 'image/jpeg',
    size: 1024,
    storage_path: null,
  };
}

describe('MediaContent', () => {
  test('несколько картинок идут в ряд в отдельной галерее', () => {
    render(
      <MediaContent
        agentId="a1"
        items={[item('photo', '1.jpeg'), item('photo', '2.jpeg'), item('photo', '3.jpeg')]}
      />,
    );
    const gallery = screen.getByTestId('media-gallery');
    expect(within(gallery).getAllByRole('button')).toHaveLength(3);
  });

  test('одна картинка рендерится как раньше, без галереи', () => {
    render(<MediaContent agentId="a1" items={[item('photo', 'solo.jpeg')]} />);
    expect(screen.queryByTestId('media-gallery')).toBeNull();
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  test('не-картинки не попадают в галерею', () => {
    render(
      <MediaContent agentId="a1" items={[item('photo', '1.jpeg'), item('doc', 'report.pdf')]} />,
    );
    const gallery = screen.getByTestId('media-gallery');
    expect(within(gallery).getAllByRole('button')).toHaveLength(1);
    expect(screen.getByText(/report\.pdf/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (из `frontend/`): `bun test src/__tests__/media-content.test.tsx`
Expected: FAIL — `data-testid="media-gallery"` не найден (сейчас картинки идут общим flex-wrap без выделенной галереи).

- [ ] **Step 3: Implement**

В `frontend/src/components/activity/MediaContent.tsx`:

1. `MediaView` принимает флаг компактного размера:

```tsx
function MediaView({
  agentId,
  item,
  compact = false,
}: {
  agentId: string;
  item: MediaItem;
  compact?: boolean;
}) {
```

Ветка изображения меняет класс:

```tsx
  if (IMAGE_KINDS.has(item.kind)) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt={item.name}
        className={
          compact
            ? 'h-16 w-16 flex-none rounded-sm border border-void-800 object-cover'
            : 'max-h-40 max-w-56 rounded-sm border border-void-800 object-cover'
        }
      />
    );
  }
```

2. `MediaContent` делит элементы на картинки и остальные; >1 картинок — галерея:

```tsx
export function MediaContent({ agentId, items }: { agentId: string; items: MediaItem[] }) {
  const [preview, setPreview] = useState<MediaItem | null>(null);

  if (!items?.length) return null;

  const images = items.filter((item) => IMAGE_KINDS.has(item.kind));
  const others = items.filter((item) => !IMAGE_KINDS.has(item.kind));
  const gallery = images.length > 1;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {gallery ? (
        <div
          data-testid="media-gallery"
          className="flex flex-row items-center gap-1.5 overflow-x-auto"
        >
          {images.map((item, i) => (
            <button
              key={`${item.storage_path ?? i}-${item.name}`}
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                setPreview(item);
              }}
              className="cursor-zoom-in"
            >
              <MediaView agentId={agentId} item={item} compact />
            </button>
          ))}
        </div>
      ) : (
        images.map((item, i) => (
          <button
            key={`${item.storage_path ?? i}-${item.name}`}
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              setPreview(item);
            }}
            className="cursor-zoom-in"
          >
            <MediaView agentId={agentId} item={item} />
          </button>
        ))
      )}
      {others.map((item, i) => (
        <MediaView key={`${item.storage_path ?? i}-${item.name}`} agentId={agentId} item={item} />
      ))}
      <Modal
        isOpen={preview !== null}
        onClose={() => setPreview(null)}
        title={preview?.name ?? ''}
        size="lg"
      >
        {preview && <LightboxImage agentId={agentId} item={preview} />}
      </Modal>
    </div>
  );
}
```

(Остальные ветки `MediaView` — голосовые, видео, бейджи ошибок — не меняются.)

- [ ] **Step 4: Run tests to verify they pass**

Run (из `frontend/`): `bun test src/__tests__/media-content.test.tsx`
Expected: 3 passed

- [ ] **Step 5: Проверки фронта**

Run (из `frontend/`):
```bash
bun run typecheck
bun run lint
bun test
```
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/activity/MediaContent.tsx frontend/src/__tests__/media-content.test.tsx
git commit -m "feat(ui): render multiple activity images as a compact horizontal gallery"
```

---

### Task 4: Полная верификация

- [ ] **Step 1: Бэкенд**

```bash
uv run ruff check src tests
uv run ty check
uv run pytest -q
```
Expected: All checks passed!; все тесты зелёные (was 161, станет +8 новых).

- [ ] **Step 2: Фронт**

```bash
cd frontend && bun test && bun run typecheck && bun run lint && bun run build
```
Expected: всё зелёное.

- [ ] **Step 3: Ручная визуальная проверка (по запросу пользователя)**

Отправить «Сергее» в Telegram альбом из 2–3 картинок с подписью. Ожидаемо:
- в Telegram агент отвечает **один раз**;
- в ленте «Активность» один ход с одной строкой «Альбом: N файлов» и N компактными картинками в горизонтальном ряду;
- клик по картинке открывает лайтбокс.

e2e Playwright НЕ запускать (решение пользователя); пуш не делать — сначала ревью пользователя.
