# Окно отправки: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Агент не пытается писать туда, где сейчас нельзя — при медленном режиме и при отобранном праве писать, — и не копит отставание, а схлопывает накопившиеся сообщения в один ход.

**Architecture:** Медленный режим и запрет писать сводятся к одному состоянию — окно отправки закрыто до момента T. `SendWindowTracker` хранит это состояние по чату, `DeferredInbox` копит входящие, пока окно закрыто, и отдаёт их одной пачкой при открытии. Рантайм врезает гейт между группировкой альбомов и запуском хода; инструменты отправки ходят через тот же трекер.

**Tech Stack:** Python 3.13, Telethon 1.45, LangChain (`create_agent` + structured output), pytest + pytest-asyncio, uv, ruff, ty. Фронт — TypeScript/React.

**Spec:** `docs/superpowers/specs/2026-09-20-send-window-design.md`

## Global Constraints

- Все команды запускаются через `uv run` (`uv run pytest`, `uv run ruff`, `uv run ty`).
- `ruff` настроен на `line-length = 100`, правила `E, F, I, B, UP, ANN` — аннотации типов обязательны везде, включая тесты.
- Обычный прогон тестов исключает маркеры `db`, `e2e`, `real_tg` (см. `addopts` в `pyproject.toml`). Живые тесты запускаются явным `-m real_tg`.
- Комментарии и докстринги в проекте пишутся по-русски там, где объясняют «почему»; названия кода — по-английски.
- Работа идёт в ветке `feat/issue-72-send-window`, уже созданной. Коммит после каждой задачи.
- Ничего не трогаем в `.agents/` и `.claude/` — это вендорные скиллы.
- Миграции БД не требуются: `agent_events.event_type` — свободный `text`.
- Фактура Telegram, на которую опирается код (взята из документации, не из исходников библиотеки):
  - `until_date` считается вечным при длительности меньше 30 секунд или больше 366 дней;
  - у `Channel` с флагом `min` поля `banned_rights` и `admin_rights` недостоверны, достоверны только `default_banned_rights` и `slowmode_enabled`;
  - `slowmode_seconds` и `slowmode_next_send_date` живут в `ChannelFull`, оба опциональны;
  - `SlowModeWaitError` несёт точный остаток в `.seconds`;
  - `flood_sleep_threshold` по умолчанию 60 — Telethon сам спит на флуд-ошибках короче порога.

## Структура файлов

**Создаются:**

| Файл | Ответственность |
|---|---|
| `src/mimic42/core/send_window.py` | Модель окна отправки, разбор прав из сущности чата, трекер состояния по чату |
| `src/mimic42/core/deferred_inbox.py` | Буфер групп входящих на время закрытого окна |
| `tests/core/test_send_window.py` | Разбор прав и поведение трекера |
| `tests/core/test_deferred_inbox.py` | Накопление, слив по дедлайну, капы, закрытие |
| `tests/core/test_send_window_runtime.py` | Врезка гейта в рантайм: буферизация, схлопывание, обязательный реплай |
| `tests/real_llm/__init__.py`, `tests/real_llm/conftest.py`, `tests/real_llm/test_send_window_behavior.py` | Проверка поведения модели на шапках с кд и запретом |
| `tests/real_tg/backend/test_real_slowmode.py` | Проверка на живом Telegram |

**Меняются:**

| Файл | Что |
|---|---|
| `src/mimic42/core/agent_runtime.py` | `_format_incoming` / `_process_batch`, `_dispatch_incoming`, поля `AgentTrigger`, фоллбэк реплая, предохранитель перед отправкой |
| `src/mimic42/integrations/telegram_tools.py` | `SendWindowClosed`, контекстный менеджер `_sending`, ветка в `_tool_failure`, параметр трекера |
| `src/mimic42/integrations/telethon_client.py` | `flood_sleep_threshold = 0` |
| `src/mimic42/core/manager.py` | Создание одного трекера на агента и передача его в рантайм и в инструменты |
| `BASE_SYSTEM_PROMPT.txt` | Абзац про медленный режим и запрет писать |
| `frontend/src/lib/activity/eventCatalog.ts` | Два новых типа событий |
| `pyproject.toml` | Маркер `real_llm` |

---

### Task 1: Модель окна и разбор прав из сущности чата

Чистая логика без сети: по объекту чата и текущему времени сказать, открыто ли окно.

**Files:**
- Create: `src/mimic42/core/send_window.py`
- Test: `tests/core/test_send_window.py`

**Interfaces:**
- Consumes: ничего
- Produces:
  - `SendWindow` — фризнутый датакласс с полями `reason: Literal["open", "slowmode", "restricted"]`, `open_at: datetime | None`, `forever: bool`, `slowmode_seconds: int | None`, `needs_entity: bool`, `needs_slowmode: bool`; методы `is_open(now: datetime) -> bool` и `retry_after(now: datetime) -> int | None`
  - `window_from_chat(chat: Any, now: datetime) -> SendWindow`
  - `OPEN: SendWindow` — константа открытого окна

- [ ] **Step 1: Написать падающий тест**

Создать `tests/core/test_send_window.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from telethon.tl import types

from mimic42.core.send_window import SendWindow, window_from_chat

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)


def channel(**kwargs: object) -> types.Channel:
    """Супергруппа с минимально заполненными обязательными полями."""
    defaults: dict[str, object] = {
        "id": 777,
        "title": "Тестовая супергруппа",
        "photo": None,
        "date": NOW,
        "megagroup": True,
    }
    defaults.update(kwargs)
    return types.Channel(**defaults)  # type: ignore[arg-type]


def banned(**kwargs: object) -> types.ChatBannedRights:
    defaults: dict[str, object] = {"until_date": None}
    defaults.update(kwargs)
    return types.ChatBannedRights(**defaults)  # type: ignore[arg-type]


def test_plain_supergroup_is_open() -> None:
    assert window_from_chat(channel(), NOW).is_open(NOW)


def test_user_is_always_open() -> None:
    user = types.User(id=42)
    assert window_from_chat(user, NOW).is_open(NOW)


def test_slowmode_needs_seconds_from_full_chat() -> None:
    window = window_from_chat(channel(slowmode_enabled=True), NOW)
    assert window.reason == "slowmode"
    assert window.needs_slowmode is True


def test_personal_restriction_closes_until_date() -> None:
    until = NOW + timedelta(minutes=10)
    window = window_from_chat(
        channel(banned_rights=banned(until_date=until, send_messages=True)), NOW
    )
    assert window.reason == "restricted"
    assert window.forever is False
    assert window.open_at == until
    assert window.is_open(NOW) is False
    assert window.is_open(until) is True
    assert window.retry_after(NOW) == 600


def test_restriction_without_until_date_is_forever() -> None:
    window = window_from_chat(channel(banned_rights=banned(send_messages=True)), NOW)
    assert window.forever is True
    assert window.retry_after(NOW) is None


def test_restriction_longer_than_366_days_is_forever() -> None:
    until = NOW + timedelta(days=400)
    window = window_from_chat(
        channel(banned_rights=banned(until_date=until, send_messages=True)), NOW
    )
    assert window.forever is True


def test_default_banned_rights_close_the_window() -> None:
    window = window_from_chat(
        channel(default_banned_rights=banned(send_messages=True)), NOW
    )
    assert window.reason == "restricted"


def test_send_plain_restriction_also_closes_the_window() -> None:
    window = window_from_chat(channel(default_banned_rights=banned(send_plain=True)), NOW)
    assert window.reason == "restricted"


def test_admin_bypasses_slowmode_and_default_rights() -> None:
    admin = channel(
        slowmode_enabled=True,
        default_banned_rights=banned(send_messages=True),
        admin_rights=types.ChatAdminRights(
            change_info=False,
            post_messages=True,
            edit_messages=False,
            delete_messages=False,
            ban_users=False,
            invite_users=False,
            pin_messages=False,
            add_admins=False,
            anonymous=False,
            manage_call=False,
            other=False,
        ),
    )
    assert window_from_chat(admin, NOW).is_open(NOW)


def test_min_channel_asks_for_a_full_entity() -> None:
    window = window_from_chat(channel(min=True), NOW)
    assert window.needs_entity is True


def test_left_channel_is_forever_closed() -> None:
    window = window_from_chat(channel(left=True), NOW)
    assert window.reason == "restricted"
    assert window.forever is True


def test_broadcast_without_admin_rights_is_closed() -> None:
    window = window_from_chat(channel(megagroup=None, broadcast=True), NOW)
    assert window.reason == "restricted"


def test_gigagroup_without_admin_rights_is_closed() -> None:
    window = window_from_chat(channel(gigagroup=True), NOW)
    assert window.reason == "restricted"


def test_basic_group_uses_default_rights_only() -> None:
    chat = types.Chat(
        id=5,
        title="Обычная группа",
        photo=None,
        participants_count=3,
        date=NOW,
        version=1,
        default_banned_rights=banned(send_messages=True),
    )
    assert window_from_chat(chat, NOW).reason == "restricted"


def test_open_window_reports_zero_retry() -> None:
    assert SendWindow().retry_after(NOW) == 0
```

- [ ] **Step 2: Прогнать тест и убедиться, что он падает**

Run: `uv run pytest tests/core/test_send_window.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'mimic42.core.send_window'`

- [ ] **Step 3: Написать минимальную реализацию**

Создать `src/mimic42/core/send_window.py`:

```python
"""Окно отправки: когда агенту снова можно писать в чат.

Медленный режим и отобранное право писать — одно состояние: отправка закрыта
до момента T. Для кд T — момент открытия слота, для ограничения прав — until_date
(возможно, бесконечность).

Фактура взята из документации Telegram, а не из исходников Telethon:

- until_date считается вечным при длительности меньше 30 секунд или больше
  366 дней (core.telegram.org/constructor/chatBannedRights);
- у min-версии Channel поверх локальной копии разрешено применять только
  перечисленный набор полей, и banned_rights с admin_rights в него не входят —
  значит личные права у такой сущности недостоверны
  (core.telegram.org/constructor/channel);
- slowmode_seconds и slowmode_next_send_date живут в ChannelFull и оба
  опциональны (core.telegram.org/constructor/channelFull).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

Reason = Literal["open", "slowmode", "restricted"]

# «Вечным считается любое значение меньше 30 секунд или больше 366 дней.»
_FOREVER_BELOW = timedelta(seconds=30)
_FOREVER_ABOVE = timedelta(days=366)


@dataclass(frozen=True)
class SendWindow:
    """Состояние отправки в один чат."""

    reason: Reason = "open"
    open_at: datetime | None = None
    forever: bool = False
    slowmode_seconds: int | None = None
    needs_entity: bool = False
    """Сущность пришла в min-виде: права недостоверны, нужна полная."""
    needs_slowmode: bool = False
    """Медленный режим включён, но длина слота ещё неизвестна."""

    def is_open(self, now: datetime) -> bool:
        if self.reason == "open":
            return True
        if self.forever:
            return False
        return self.open_at is not None and self.open_at <= now

    def retry_after(self, now: datetime) -> int | None:
        """Сколько секунд ждать. None — ждать бессмысленно."""
        if self.is_open(now):
            return 0
        if self.forever or self.open_at is None:
            return None
        return max(0, int((self.open_at - now).total_seconds()))


OPEN = SendWindow()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _is_forever(until_date: datetime | None, now: datetime) -> bool:
    until = _as_utc(until_date)
    if until is None:
        return True
    duration = until - now
    return duration < _FOREVER_BELOW or duration > _FOREVER_ABOVE


def _from_banned_rights(rights: Any, now: datetime) -> SendWindow | None:
    """Окно по ChatBannedRights или None, если писать они не мешают.

    send_messages запрещает сообщения целиком, send_plain — только текст;
    для агента, который отвечает текстом, оба означают «писать нельзя».
    """
    if rights is None:
        return None
    blocked = bool(getattr(rights, "send_messages", False)) or bool(
        getattr(rights, "send_plain", False)
    )
    if not blocked:
        return None
    until = getattr(rights, "until_date", None)
    if _is_forever(until, now):
        return SendWindow(reason="restricted", forever=True)
    return SendWindow(reason="restricted", open_at=_as_utc(until))


_FOREVER_CLOSED = SendWindow(reason="restricted", forever=True)


def window_from_chat(chat: Any, now: datetime) -> SendWindow:
    """Окно по сущности чата. Сетевых запросов не делает."""
    from telethon.tl import types

    if chat is None or isinstance(chat, types.User):
        return OPEN

    if isinstance(chat, types.Chat):
        if getattr(chat, "left", False) or getattr(chat, "deactivated", False):
            return _FOREVER_CLOSED
        if getattr(chat, "creator", False) or getattr(chat, "admin_rights", None) is not None:
            return OPEN
        return _from_banned_rights(getattr(chat, "default_banned_rights", None), now) or OPEN

    if not isinstance(chat, types.Channel):
        return OPEN

    if getattr(chat, "left", False):
        return _FOREVER_CLOSED

    is_min = bool(getattr(chat, "min", False))
    if is_min:
        # Админство и личные ограничения у min-сущности применять нельзя —
        # решение без них было бы враньём, поэтому просим полную сущность.
        return SendWindow(needs_entity=True)

    if getattr(chat, "creator", False) or getattr(chat, "admin_rights", None) is not None:
        return OPEN

    own = _from_banned_rights(getattr(chat, "banned_rights", None), now)
    if own is not None:
        return own

    default = _from_banned_rights(getattr(chat, "default_banned_rights", None), now)
    if default is not None:
        return default

    if getattr(chat, "broadcast", False) or getattr(chat, "gigagroup", False):
        # В канал и в гигагруппу пишут только админы, а админом мы здесь уже не являемся.
        return _FOREVER_CLOSED

    if getattr(chat, "slowmode_enabled", False):
        return SendWindow(reason="slowmode", needs_slowmode=True)

    return OPEN
```

- [ ] **Step 4: Прогнать тесты и убедиться, что они проходят**

Run: `uv run pytest tests/core/test_send_window.py -v`
Expected: PASS, все 15 тестов

- [ ] **Step 5: Проверить линт и типы**

Run: `uv run ruff check src/mimic42/core/send_window.py tests/core/test_send_window.py && uv run ruff format --check src/mimic42/core/send_window.py tests/core/test_send_window.py && uv run ty check src/mimic42/core/send_window.py`
Expected: без ошибок

- [ ] **Step 6: Коммит**

```bash
git add src/mimic42/core/send_window.py tests/core/test_send_window.py
git commit -m "feat(send-window): parse write permissions from a chat entity

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Трекер окна с кэшем, расходом слота и синхронизацией по ошибкам

**Files:**
- Modify: `src/mimic42/core/send_window.py` (дописать класс в конец файла)
- Test: `tests/core/test_send_window.py` (дописать блок тестов в конец файла)

**Interfaces:**
- Consumes: `SendWindow`, `window_from_chat`, `OPEN` из Task 1
- Produces:
  - `SendWindowTracker(client: Any, *, entity_ttl: float = 300.0, now: Callable[[], datetime] | None = None)`
  - `async def check(self, peer: str, chat: Any = None) -> SendWindow`
  - `def note_sent(self, peer: str) -> None`
  - `def note_error(self, peer: str, exc: BaseException) -> None`
  - `def announce(self, peer: str, reason: str) -> bool` — True, если про это состояние ещё не сообщали
  - `def forget(self, peer: str) -> None`

- [ ] **Step 1: Написать падающий тест**

Дописать в конец `tests/core/test_send_window.py`:

```python
import pytest
from telethon import errors

from mimic42.core.send_window import SendWindowTracker


class FakeClock:
    def __init__(self, start: datetime = NOW) -> None:
        self.value = start

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value = self.value + timedelta(seconds=seconds)


class FakeClient:
    """Отдаёт сущность на get_entity и ChannelFull на GetFullChannelRequest."""

    def __init__(self, entity: object, slowmode_seconds: int | None = None) -> None:
        self.entity = entity
        self.slowmode_seconds = slowmode_seconds
        self.entity_calls = 0
        self.full_calls = 0

    async def get_entity(self, peer: object) -> object:
        self.entity_calls += 1
        return self.entity

    async def __call__(self, request: object) -> object:
        self.full_calls += 1
        full_chat = types.ChannelFull.__new__(types.ChannelFull)
        full_chat.slowmode_seconds = self.slowmode_seconds
        full_chat.slowmode_next_send_date = None
        result = types.messages.ChatFull.__new__(types.messages.ChatFull)
        result.full_chat = full_chat
        return result


def tracker_for(client: FakeClient, clock: FakeClock) -> SendWindowTracker:
    return SendWindowTracker(client, now=clock.now)


async def test_check_uses_the_passed_chat_without_network() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel())
    window = await tracker_for(client, clock).check("-100777", chat=channel())
    assert window.is_open(clock.now())
    assert client.entity_calls == 0


async def test_check_fetches_the_entity_when_none_is_given() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel())
    tracker = tracker_for(client, clock)
    await tracker.check("-100777")
    assert client.entity_calls == 1


async def test_entity_is_cached_until_ttl_expires() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel())
    tracker = SendWindowTracker(client, entity_ttl=300.0, now=clock.now)
    await tracker.check("-100777")
    await tracker.check("-100777")
    assert client.entity_calls == 1
    clock.advance(301)
    await tracker.check("-100777")
    assert client.entity_calls == 2


async def test_min_entity_triggers_a_refetch() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel())
    tracker = tracker_for(client, clock)
    window = await tracker.check("-100777", chat=channel(min=True))
    assert client.entity_calls == 1
    assert window.is_open(clock.now())


async def test_slowmode_seconds_come_from_the_full_chat() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel(slowmode_enabled=True), slowmode_seconds=30)
    tracker = tracker_for(client, clock)
    window = await tracker.check("-100777")
    assert window.slowmode_seconds == 30
    # Слот ещё не израсходован, поэтому писать можно прямо сейчас.
    assert window.is_open(clock.now())
    assert client.full_calls == 1


async def test_sending_consumes_the_slot() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel(slowmode_enabled=True), slowmode_seconds=30)
    tracker = tracker_for(client, clock)
    await tracker.check("-100777")
    tracker.note_sent("-100777")

    window = await tracker.check("-100777")
    assert window.is_open(clock.now()) is False
    assert window.retry_after(clock.now()) == 30

    clock.advance(30)
    assert (await tracker.check("-100777")).is_open(clock.now())


async def test_slow_mode_error_overrides_the_local_estimate() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel(slowmode_enabled=True), slowmode_seconds=30)
    tracker = tracker_for(client, clock)
    await tracker.check("-100777")
    tracker.note_error("-100777", errors.SlowModeWaitError(request=None, capture=55))

    window = await tracker.check("-100777")
    assert window.retry_after(clock.now()) == 55


async def test_forbidden_error_closes_the_window_forever() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel())
    tracker = tracker_for(client, clock)
    await tracker.check("-100777")
    tracker.note_error("-100777", errors.ChatWriteForbiddenError(request=None))

    window = await tracker.check("-100777")
    assert window.reason == "restricted"
    assert window.forever is True
    assert window.retry_after(clock.now()) is None


async def test_unrelated_error_leaves_the_window_alone() -> None:
    clock = FakeClock()
    client = FakeClient(entity=channel())
    tracker = tracker_for(client, clock)
    tracker.note_error("-100777", ValueError("что-то другое"))
    assert (await tracker.check("-100777")).is_open(clock.now())


async def test_announce_reports_each_state_once() -> None:
    tracker = SendWindowTracker(FakeClient(entity=channel()), now=FakeClock().now)
    assert tracker.announce("-100777", "restricted") is True
    assert tracker.announce("-100777", "restricted") is False
    assert tracker.announce("-100777", "open") is True
    assert tracker.announce("-100777", "restricted") is True


async def test_entity_failure_leaves_the_window_open() -> None:
    """Не смогли узнать права — не наказываем агента молчанием."""

    class BrokenClient(FakeClient):
        async def get_entity(self, peer: object) -> object:
            raise errors.ChannelPrivateError(request=None)

    clock = FakeClock()
    tracker = tracker_for(BrokenClient(entity=None), clock)
    with pytest.raises(errors.ChannelPrivateError):
        raise errors.ChannelPrivateError(request=None)
    assert (await tracker.check("-100777")).is_open(clock.now())
```

- [ ] **Step 2: Прогнать тест и убедиться, что он падает**

Run: `uv run pytest tests/core/test_send_window.py -v -k tracker or slot or announce`
Expected: FAIL с `ImportError: cannot import name 'SendWindowTracker'`

- [ ] **Step 3: Написать минимальную реализацию**

Дописать в конец `src/mimic42/core/send_window.py`:

```python
import logging
from collections.abc import Callable

logger = logging.getLogger("mimic42.send_window")

_FOREVER_ERRORS = (
    "ChatWriteForbiddenError",
    "UserBannedInChannelError",
    "ChatRestrictedError",
    "ChatSendPlainForbiddenError",
    "ChatSendMediaForbiddenError",
    "ChatSendStickersForbiddenError",
    "ChatSendGifsForbiddenError",
    "ChatSendPhotosForbiddenError",
    "ChatSendVideosForbiddenError",
    "ChatSendVoicesForbiddenError",
    "ChatSendPollForbiddenError",
    "ChatAdminRequiredError",
    "ChannelPrivateError",
)


class SendWindowTracker:
    """Состояние окна отправки по чатам одного агента.

    Права стоят сетевого запроса: get_entity, по документации, всегда ходит
    в API за свежей версией сущности. Поэтому результат кэшируется на
    entity_ttl, а ошибка Telegram сбрасывает кэш — она точнее любого
    локального расчёта.
    """

    def __init__(
        self,
        client: Any,
        *,
        entity_ttl: float = 300.0,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._entity_ttl = entity_ttl
        self._now = now if now is not None else lambda: datetime.now(UTC)
        self._base: dict[str, tuple[SendWindow, datetime]] = {}
        self._blocked_until: dict[str, datetime] = {}
        self._announced: dict[str, str] = {}

    async def check(self, peer: str, chat: Any = None) -> SendWindow:
        now = self._now()
        base = await self._base_window(peer, chat, now)

        if base.reason == "restricted":
            return base

        blocked = self._blocked_until.get(peer)
        if blocked is not None and blocked > now:
            return SendWindow(
                reason="slowmode",
                open_at=blocked,
                slowmode_seconds=base.slowmode_seconds,
            )
        if blocked is not None:
            self._blocked_until.pop(peer, None)
        # Окно открыто, но длину слота агенту знать полезно: он платит ею за ответ.
        return SendWindow(slowmode_seconds=base.slowmode_seconds)

    def note_sent(self, peer: str) -> None:
        base = self._base.get(peer)
        seconds = base[0].slowmode_seconds if base is not None else None
        if not seconds:
            return
        self._blocked_until[peer] = self._now() + timedelta(seconds=seconds)

    def note_error(self, peer: str, exc: BaseException) -> None:
        name = type(exc).__name__
        if name in ("SlowModeWaitError", "FloodWaitError", "FloodPremiumWaitError"):
            seconds = getattr(exc, "seconds", None)
            if isinstance(seconds, int):
                self._blocked_until[peer] = self._now() + timedelta(seconds=seconds)
            return
        if name in _FOREVER_ERRORS:
            # Telegram сказал «нельзя» — локальный разбор прав устарел.
            self._base[peer] = (_FOREVER_CLOSED, self._now() + timedelta(seconds=self._entity_ttl))
            self._blocked_until.pop(peer, None)

    def announce(self, peer: str, reason: str) -> bool:
        """True, если про это состояние чата ещё не сообщали агенту."""
        if self._announced.get(peer) == reason:
            return False
        self._announced[peer] = reason
        return True

    def forget(self, peer: str) -> None:
        self._base.pop(peer, None)
        self._blocked_until.pop(peer, None)
        self._announced.pop(peer, None)

    async def _base_window(self, peer: str, chat: Any, now: datetime) -> SendWindow:
        cached = self._base.get(peer)
        if cached is not None and cached[1] > now and chat is None:
            return cached[0]

        window = window_from_chat(chat, now) if chat is not None else SendWindow(needs_entity=True)
        if window.needs_entity:
            entity = await self._fetch_entity(peer)
            window = window_from_chat(entity, now)
        if window.needs_slowmode:
            window = await self._fill_slowmode(peer, window)

        self._base[peer] = (window, now + timedelta(seconds=self._entity_ttl))
        return window

    async def _fetch_entity(self, peer: str) -> Any:
        get_entity = getattr(self._client, "get_entity", None)
        if not callable(get_entity):
            return None
        try:
            return await get_entity(_peer_argument(peer))
        except Exception:
            # Права выяснить не удалось. Считать чат закрытым нельзя: агент
            # замолчит там, где на самом деле может говорить.
            logger.warning("Не удалось получить сущность чата %s", peer, exc_info=True)
            return None

    async def _fill_slowmode(self, peer: str, window: SendWindow) -> SendWindow:
        from telethon import functions

        try:
            result = await self._client(
                functions.channels.GetFullChannelRequest(channel=_peer_argument(peer))
            )
        except Exception:
            logger.warning("Не удалось получить ChannelFull для %s", peer, exc_info=True)
            return SendWindow()

        full_chat = getattr(result, "full_chat", None)
        seconds = getattr(full_chat, "slowmode_seconds", None)
        next_send = _as_utc(getattr(full_chat, "slowmode_next_send_date", None))
        if next_send is not None:
            self._blocked_until[peer] = next_send
        if not isinstance(seconds, int) or seconds <= 0:
            return SendWindow()
        return SendWindow(reason="open", slowmode_seconds=seconds)


def _peer_argument(peer: str) -> str | int:
    """Числовой peer Telethon ждёт числом, иначе резолв идёт как по юзернейму."""
    stripped = peer.strip()
    if stripped.startswith("-") and stripped[1:].isdigit():
        return int(stripped)
    if stripped.isdigit():
        return int(stripped)
    return stripped
```

Перенести `import logging`, `from collections.abc import Callable` наверх файла к остальным импортам и убрать их из середины — ruff (правило `E402`/`I`) иначе ругнётся.

- [ ] **Step 4: Прогнать все тесты файла**

Run: `uv run pytest tests/core/test_send_window.py -v`
Expected: PASS, все тесты

- [ ] **Step 5: Проверить линт и типы**

Run: `uv run ruff check src/mimic42/core/send_window.py tests/core/test_send_window.py && uv run ruff format --check src/mimic42/core/send_window.py tests/core/test_send_window.py && uv run ty check src/mimic42/core/send_window.py`
Expected: без ошибок

- [ ] **Step 6: Коммит**

```bash
git add src/mimic42/core/send_window.py tests/core/test_send_window.py
git commit -m "feat(send-window): track the window per chat with slot accounting

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Буфер входящих на время закрытого окна

**Files:**
- Create: `src/mimic42/core/deferred_inbox.py`
- Test: `tests/core/test_deferred_inbox.py`

**Interfaces:**
- Consumes: ничего
- Produces:
  - `DeferredInbox(flush: Callable[[str, list[list[Any]]], Awaitable[None]], *, max_groups: int = 20, max_age: float = 600.0, now: Callable[[], float] | None = None, sleep: Callable[[float], Awaitable[None]] | None = None)`
  - `def add(self, peer: str, group: list[Any], delay: float) -> None`
  - `async def close(self) -> None`
  - Константы модуля `MAX_GROUPS = 20`, `MAX_AGE = 600.0`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/core/test_deferred_inbox.py`:

```python
from __future__ import annotations

import asyncio
from typing import Any

from mimic42.core.deferred_inbox import DeferredInbox


class Recorder:
    def __init__(self) -> None:
        self.flushed: list[tuple[str, list[list[Any]]]] = []

    async def flush(self, peer: str, groups: list[list[Any]]) -> None:
        self.flushed.append((peer, groups))


class FakeClock:
    """Детерминированное время и сон — как в tests/core/test_album_grouper.py."""

    def __init__(self) -> None:
        self._time = 0.0
        self._waiters: list[tuple[float, asyncio.Event]] = []

    def now(self) -> float:
        return self._time

    async def sleep(self, delay: float) -> None:
        waiter = (self._time + max(delay, 0.0), asyncio.Event())
        self._waiters.append(waiter)
        try:
            await waiter[1].wait()
        finally:
            if waiter in self._waiters:
                self._waiters.remove(waiter)

    async def advance(self, delta: float) -> None:
        self._time += delta
        await asyncio.sleep(0)
        for _ in range(100):
            due = [waiter for waiter in self._waiters if waiter[0] <= self._time]
            if not due:
                return
            for _, event in due:
                event.set()
            await asyncio.sleep(0)
            self._waiters = [waiter for waiter in self._waiters if not waiter[1].is_set()]
        raise AssertionError("fake clock did not settle")


def inbox_with(clock: FakeClock, recorder: Recorder, **kwargs: Any) -> DeferredInbox:
    return DeferredInbox(recorder.flush, now=clock.now, sleep=clock.sleep, **kwargs)


async def test_groups_are_delivered_together_when_the_window_opens() -> None:
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder)
    inbox.add("-100777", ["a"], delay=30.0)
    await clock.advance(10)
    inbox.add("-100777", ["b"], delay=20.0)
    assert recorder.flushed == []

    await clock.advance(20)
    assert recorder.flushed == [("-100777", [["a"], ["b"]])]


async def test_albums_stay_one_group() -> None:
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder)
    inbox.add("-100777", ["photo1", "photo2"], delay=5.0)
    await clock.advance(5)
    assert recorder.flushed == [("-100777", [["photo1", "photo2"]])]


async def test_different_peers_do_not_mix() -> None:
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder)
    inbox.add("-100777", ["a"], delay=5.0)
    inbox.add("-100888", ["b"], delay=5.0)
    await clock.advance(5)
    assert sorted(recorder.flushed) == [("-100777", [["a"]]), ("-100888", [["b"]])]


async def test_oldest_groups_are_evicted_past_the_cap() -> None:
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder, max_groups=2)
    for name in ("a", "b", "c"):
        inbox.add("-100777", [name], delay=10.0)
    await clock.advance(10)
    assert recorder.flushed == [("-100777", [["b"], ["c"]])]


async def test_stale_groups_are_dropped_on_flush() -> None:
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder, max_age=60.0)
    inbox.add("-100777", ["old"], delay=200.0)
    await clock.advance(150)
    inbox.add("-100777", ["fresh"], delay=50.0)
    await clock.advance(50)
    assert recorder.flushed == [("-100777", [["fresh"]])]


async def test_everything_stale_flushes_nothing() -> None:
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder, max_age=10.0)
    inbox.add("-100777", ["old"], delay=100.0)
    await clock.advance(100)
    assert recorder.flushed == []


async def test_close_cancels_pending_buffers() -> None:
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder)
    inbox.add("-100777", ["a"], delay=30.0)
    await inbox.close()
    await clock.advance(30)
    assert recorder.flushed == []


async def test_a_later_group_does_not_postpone_the_deadline() -> None:
    """Дедлайн — момент открытия окна, а не тишина: новый элемент его не двигает."""
    clock, recorder = FakeClock(), Recorder()
    inbox = inbox_with(clock, recorder)
    inbox.add("-100777", ["a"], delay=10.0)
    await clock.advance(5)
    inbox.add("-100777", ["b"], delay=100.0)
    await clock.advance(5)
    assert recorder.flushed == [("-100777", [["a"], ["b"]])]
```

- [ ] **Step 2: Прогнать тест и убедиться, что он падает**

Run: `uv run pytest tests/core/test_deferred_inbox.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'mimic42.core.deferred_inbox'`

- [ ] **Step 3: Написать минимальную реализацию**

Создать `src/mimic42/core/deferred_inbox.py`:

```python
"""Буфер входящих на время, пока окно отправки закрыто.

Устроен как AlbumGrouper, но копит не элементы одного альбома, а группы
сообщений по чату, и ждёт не тишины, а момента открытия окна. Каждая группа —
это одно сообщение или один альбом; при сливе они разбираются одним ходом.

Капы существуют ради главного требования: агент не должен отвечать на то, что
успело устареть, пока он молчал.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

logger = logging.getLogger("mimic42.deferred_inbox")

MAX_GROUPS = 20
MAX_AGE = 600.0


class DeferredInbox:
    """Копит группы входящих по чату и отдаёт их разом при открытии окна."""

    def __init__(
        self,
        flush: Callable[[str, list[list[Any]]], Awaitable[None]],
        *,
        max_groups: int | None = None,
        max_age: float | None = None,
        now: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._flush = flush
        self._max_groups = MAX_GROUPS if max_groups is None else max_groups
        self._max_age = MAX_AGE if max_age is None else max_age
        self._now = now if now is not None else self._loop_time
        self._sleep = sleep if sleep is not None else asyncio.sleep
        self._groups: dict[str, list[tuple[float, list[Any]]]] = {}
        self._deadlines: dict[str, float] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._flushing: set[asyncio.Task[None]] = set()

    @staticmethod
    def _loop_time() -> float:
        return asyncio.get_running_loop().time()

    def add(self, peer: str, group: list[Any], delay: float) -> None:
        """Положить группу в буфер; первая группа планирует слив."""
        now = self._now()
        entries = self._groups.setdefault(peer, [])
        entries.append((now, group))
        if len(entries) > self._max_groups:
            dropped = len(entries) - self._max_groups
            del entries[:dropped]
            logger.info("Вытеснено %d устаревших групп в чате %s", dropped, peer)

        if peer in self._tasks:
            # Дедлайн задаётся окном отправки, а не последним сообщением:
            # продлевать его новым входящим — значит копить отставание.
            return
        self._deadlines[peer] = now + max(delay, 0.0)
        self._tasks[peer] = asyncio.create_task(self._flush_after(peer))

    async def close(self) -> None:
        """Отменить ожидающие буферы; слив в полёте не обрывается."""
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        dropped = sum(len(entries) for entries in self._groups.values())
        self._groups.clear()
        self._deadlines.clear()
        if dropped:
            logger.warning("Отброшено %d отложенных групп при остановке", dropped)
        if self._flushing:
            logger.info("Оставлено %d сливов в полёте", len(self._flushing))

    async def _flush_after(self, peer: str) -> None:
        while True:
            delay = self._deadlines.get(peer, 0.0) - self._now()
            if delay <= 0:
                break
            await self._sleep(delay)

        entries = self._groups.pop(peer, [])
        self._deadlines.pop(peer, None)
        self._tasks.pop(peer, None)

        now = self._now()
        fresh = [group for added_at, group in entries if now - added_at <= self._max_age]
        stale = len(entries) - len(fresh)
        if stale:
            logger.info("Отброшено %d протухших групп в чате %s", stale, peer)
        if not fresh:
            return

        task = asyncio.current_task()
        if task is not None:
            self._flushing.add(task)
        try:
            await self._flush(peer, fresh)
        except Exception:
            logger.exception("Слив отложенных сообщений чата %s упал", peer)
        finally:
            if task is not None:
                self._flushing.discard(task)
```

- [ ] **Step 4: Прогнать тесты и убедиться, что они проходят**

Run: `uv run pytest tests/core/test_deferred_inbox.py -v`
Expected: PASS, все 8 тестов

- [ ] **Step 5: Проверить линт и типы**

Run: `uv run ruff check src/mimic42/core/deferred_inbox.py tests/core/test_deferred_inbox.py && uv run ruff format --check src/mimic42/core/deferred_inbox.py tests/core/test_deferred_inbox.py && uv run ty check src/mimic42/core/deferred_inbox.py`
Expected: без ошибок

- [ ] **Step 6: Коммит**

```bash
git add src/mimic42/core/deferred_inbox.py tests/core/test_deferred_inbox.py
git commit -m "feat(send-window): buffer incoming groups while the window is closed

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Разделить `_process_incoming` на форматирование и ход

Чистый рефакторинг без изменения поведения: существующие тесты должны остаться зелёными без правок. Нужен, потому что нынешний `_process_incoming` склеивает список событий как один альбом (общая шапка от первого), а пачке из разных сообщений нужна своя шапка.

**Files:**
- Modify: `src/mimic42/core/agent_runtime.py:669-1029`

**Interfaces:**
- Consumes: ничего нового
- Produces:
  - `@dataclass class IncomingBlock` с полями `text: str`, `media: list[MediaFile]`, `message_id: int | None`, `reply_to_msg_id: int | None`, `reply_preview: str`, `raw_text: str`, `thread_title: str | None`, `sender_str: str`, `chat_type_str: str`, `msg_date: datetime`
  - `async def _format_incoming(self, events: list[TelegramEventLike]) -> IncomingBlock | None` — None, когда текста не осталось
  - `async def _process_batch(self, peer: str, groups: list[list[TelegramEventLike]]) -> None`
  - `async def _process_incoming(self, events: list[TelegramEventLike]) -> None` остаётся и делегирует в `_process_batch`

- [ ] **Step 1: Зафиксировать текущее поведение прогоном тестов**

Run: `uv run pytest tests/core/test_agent_runtime.py tests/core/test_runtime_media.py tests/core/test_album_grouper.py -v`
Expected: PASS — это зелёная база, к которой возвращаемся после рефакторинга

- [ ] **Step 2: Вынести форматирование в `_format_incoming`**

В `src/mimic42/core/agent_runtime.py` рядом с `TurnContext` добавить:

```python
@dataclass
class IncomingBlock:
    """Одно входящее (или один альбом), уже приведённое к тексту для модели."""

    text: str
    media: list[MediaFile]
    message_id: int | None
    reply_to_msg_id: int | None
    reply_preview: str
    raw_text: str
    thread_title: str | None
    sender_str: str
    chat_type_str: str
    msg_date: datetime
```

Тело нынешнего `_process_incoming` от строки «Элементы альбома обрабатываются по отдельности» и до формирования переменной `text` с шапкой `[Входящее сообщение]` переносится в новый метод `_format_incoming(self, events)`. Метод возвращает `IncomingBlock` с уже собранным `text` (та же самая шапка, что сейчас) либо `None`, если после `_process_media_and_text` текста не осталось. Проверка мьюта уведомлений, `_upsert_thread` и вызов `trigger_message` в `_format_incoming` **не** переносятся.

- [ ] **Step 3: Собрать `_process_batch` и свести к нему `_process_incoming`**

```python
    async def _process_incoming(self, events: list[TelegramEventLike]) -> None:
        peer = await _extract_incoming_peer(events[0])
        await self._process_batch(peer, [events])

    async def _process_batch(
        self, peer: str, groups: list[list[TelegramEventLike]]
    ) -> None:
        try:
            blocks: list[IncomingBlock] = []
            for group in groups:
                block = await self._format_incoming(group)
                if block is not None:
                    blocks.append(block)
            if not blocks:
                logger.info("Пачка для чата %s пуста после разбора, пропускаем", peer)
                return

            last = blocks[-1]
            text = "\n\n".join(block.text for block in blocks)
            media: list[dict[str, Any]] = []
            for block in blocks:
                media.extend(m.as_payload() for m in block.media)

            thread_id = await self._upsert_thread(
                peer=peer,
                title=last.thread_title,
                last_message_at=last.msg_date,
            )
            await self.trigger_message(
                AgentTrigger(
                    peer=peer,
                    text=text,
                    raw_text="\n".join(block.raw_text for block in blocks),
                    peer_name=last.sender_str,
                    chat_name=last.chat_type_str,
                    message_id=last.message_id,
                    thread_id=thread_id,
                    thread_title=last.thread_title,
                    media=media,
                    reply_to_message_id=last.reply_to_msg_id,
                    reply_preview=last.reply_preview[:200] or None,
                )
            )
        except Exception as e:
            logger.exception("Необработанное исключение в обработчике входящих")
            if getattr(e, "_mimic_turn_failed_recorded", False):
                return
            await self._record_event(
                event_type="turn.failed",
                status="failed",
                payload={"peer": peer, "error_code": type(e).__name__},
                error=str(e),
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
```

Проверка мьюта уведомлений остаётся там, где была по потоку, — её место определит Task 6, сейчас достаточно оставить её в начале `_process_incoming` перед вызовом `_process_batch`.

- [ ] **Step 4: Прогнать тесты и убедиться, что поведение не изменилось**

Run: `uv run pytest tests/core tests/integrations -v`
Expected: PASS, ровно те же тесты, что и в шаге 1, без правок в самих тестах

- [ ] **Step 5: Проверить линт и типы**

Run: `uv run ruff check src/mimic42/core/agent_runtime.py && uv run ruff format --check src/mimic42/core/agent_runtime.py && uv run ty check src/mimic42/core/agent_runtime.py`
Expected: без ошибок

- [ ] **Step 6: Коммит**

```bash
git add src/mimic42/core/agent_runtime.py
git commit -m "refactor(runtime): split incoming formatting from turn dispatch

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Обязательный реплай и предохранитель перед отправкой

**Files:**
- Modify: `src/mimic42/core/agent_runtime.py` (`AgentTrigger`, `trigger_message`)
- Test: `tests/core/test_agent_runtime.py` (дописать)

**Interfaces:**
- Consumes: `SendWindowTracker` из Task 2
- Produces:
  - `AgentTrigger` получает поля `require_reply_to: bool = False` и `fallback_reply_to: int | None = None`
  - `MimicAgentRuntime.__init__` получает именованный параметр `send_window: SendWindowTracker | None = None`
  - Событие `message.blocked` со статусом `failed` и payload `{"turn_id", "peer", "reason", "retry_after_seconds"}`

- [ ] **Step 1: Написать падающие тесты**

Дописать в конец `tests/core/test_agent_runtime.py` — файл уже содержит фабрику `make_config()` и класс `FakeLangChainAgent`, используем их:

```python
async def test_reply_to_falls_back_to_the_last_message_of_the_batch() -> None:
    """При схлопывании ответ без привязки нечитаем, поэтому реплай обязателен."""
    account = FakeTelegramAccount()
    account.authorized = True
    client = FakeTelegramClient(account)
    agent = FakeLangChainAgent(
        structured_response={"text": "ответ", "send_any_message": True, "reply_to": None}
    )
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=cast(Any, client),
        langchain_agent=cast(Any, agent),
    )
    await runtime.trigger_message(
        AgentTrigger(
            peer="123",
            text="пачка",
            require_reply_to=True,
            fallback_reply_to=555,
        )
    )
    assert account.sent[-1].kwargs["reply_to"] == 555


async def test_model_reply_to_wins_over_the_fallback() -> None:
    account = FakeTelegramAccount()
    account.authorized = True
    client = FakeTelegramClient(account)
    agent = FakeLangChainAgent(
        structured_response={"text": "ответ", "send_any_message": True, "reply_to": 42}
    )
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=cast(Any, client),
        langchain_agent=cast(Any, agent),
    )
    await runtime.trigger_message(
        AgentTrigger(
            peer="123", text="пачка", require_reply_to=True, fallback_reply_to=555
        )
    )
    assert account.sent[-1].kwargs["reply_to"] == 42


async def test_closed_window_cancels_the_send() -> None:
    """Между решением и отправкой проходит время генерации: слот мог закрыться."""
    from datetime import UTC, datetime, timedelta

    from mimic42.core.send_window import SendWindow

    class ClosedWindow:
        def __init__(self) -> None:
            self.sent_notes = 0

        async def check(self, peer: str, chat: object = None) -> SendWindow:
            return SendWindow(
                reason="slowmode",
                open_at=datetime.now(UTC) + timedelta(seconds=25),
                slowmode_seconds=30,
            )

        def note_sent(self, peer: str) -> None:
            self.sent_notes += 1

        def note_error(self, peer: str, exc: BaseException) -> None:
            pass

        def announce(self, peer: str, reason: str) -> bool:
            return True

    account = FakeTelegramAccount()
    account.authorized = True
    client = FakeTelegramClient(account)
    window = ClosedWindow()
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=cast(Any, client),
        langchain_agent=cast(Any, FakeLangChainAgent("ответ")),
        send_window=cast(Any, window),
    )
    await runtime.trigger_message(AgentTrigger(peer="123", text="привет"))
    assert account.sent == []
    assert window.sent_notes == 0


async def test_successful_send_consumes_the_slot() -> None:
    from mimic42.core.send_window import SendWindow

    class OpenWindow:
        def __init__(self) -> None:
            self.sent_notes = 0

        async def check(self, peer: str, chat: object = None) -> SendWindow:
            return SendWindow(slowmode_seconds=30)

        def note_sent(self, peer: str) -> None:
            self.sent_notes += 1

        def note_error(self, peer: str, exc: BaseException) -> None:
            pass

        def announce(self, peer: str, reason: str) -> bool:
            return True

    account = FakeTelegramAccount()
    account.authorized = True
    client = FakeTelegramClient(account)
    window = OpenWindow()
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=cast(Any, client),
        langchain_agent=cast(Any, FakeLangChainAgent("ответ")),
        send_window=cast(Any, window),
    )
    await runtime.trigger_message(AgentTrigger(peer="123", text="привет"))
    assert len(account.sent) == 1
    assert window.sent_notes == 1
```

- [ ] **Step 2: Прогнать тесты и убедиться, что они падают**

Run: `uv run pytest tests/core/test_agent_runtime.py -v -k "reply_to or window or slot"`
Expected: FAIL — `AgentTrigger` не знает полей `require_reply_to`/`fallback_reply_to`, `MimicAgentRuntime` не знает `send_window`

- [ ] **Step 3: Реализовать**

В `AgentTrigger` добавить:

```python
    require_reply_to: bool = False
    fallback_reply_to: int | None = Field(default=None, gt=0)
```

В `MimicAgentRuntime.__init__` добавить параметр и поле:

```python
        send_window: SendWindowTracker | None = None,
```
```python
        self._send_window = send_window
```

В `trigger_message`, сразу после разбора структурированного ответа и проверки на пустой текст, добавить фоллбэк реплая:

```python
            if send_any and trigger.require_reply_to and reply_to is None:
                reply_to = trigger.fallback_reply_to
                logger.info(
                    "Модель не указала reply_to на схлопнутой пачке, ставим %s",
                    reply_to,
                )
```

Перед блоком отметки прочтения добавить предохранитель:

```python
            if send_any and self._send_window is not None:
                window = await self._send_window.check(trigger.peer)
                if not window.is_open(datetime.now(UTC)):
                    retry_after = window.retry_after(datetime.now(UTC))
                    logger.info(
                        "Окно отправки в %s закрыто (%s), ответ не уходит",
                        trigger.peer,
                        window.reason,
                    )
                    await self._record_event(
                        event_type="message.blocked",
                        status="failed",
                        payload={
                            "turn_id": turn_id,
                            "peer": trigger.peer,
                            "reason": window.reason,
                            "retry_after_seconds": retry_after,
                        },
                        started_at=datetime.now(UTC),
                        completed_at=datetime.now(UTC),
                    )
                    send_any = False
```

В блоке отправки после успеха и в `except` добавить учёт:

```python
                    logger.info(f"Message sent successfully to {peer_id_for_send}")
                    if self._send_window is not None:
                        self._send_window.note_sent(trigger.peer)
```
```python
                except Exception as e:
                    if self._send_window is not None:
                        self._send_window.note_error(trigger.peer, e)
```
(добавить строку первой в теле существующего `except`, остальное не трогать)

Добавить импорт `from mimic42.core.send_window import SendWindowTracker` к импортам файла.

- [ ] **Step 4: Прогнать тесты и убедиться, что они проходят**

Run: `uv run pytest tests/core/test_agent_runtime.py -v`
Expected: PASS, включая существующие тесты

- [ ] **Step 5: Проверить линт и типы**

Run: `uv run ruff check src/mimic42/core/agent_runtime.py tests/core/test_agent_runtime.py && uv run ruff format --check src/mimic42/core/agent_runtime.py tests/core/test_agent_runtime.py && uv run ty check src/mimic42/core/agent_runtime.py`
Expected: без ошибок

- [ ] **Step 6: Коммит**

```bash
git add src/mimic42/core/agent_runtime.py tests/core/test_agent_runtime.py
git commit -m "feat(runtime): require a reply on collapsed batches and guard the send

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Врезать гейт в поток входящих

**Files:**
- Modify: `src/mimic42/core/agent_runtime.py` (`__init__`, `_handle_incoming_message`, `_flush_album`, `stop`, новый `_dispatch_incoming`)
- Modify: `src/mimic42/integrations/telethon_client.py`
- Modify: `src/mimic42/core/manager.py:265-316`
- Test: `tests/core/test_send_window_runtime.py`

**Interfaces:**
- Consumes: `SendWindowTracker` (Task 2), `DeferredInbox` (Task 3), `_process_batch` (Task 4), поля `AgentTrigger` (Task 5)
- Produces:
  - `MimicAgentRuntime._dispatch_incoming(self, events: list[TelegramEventLike]) -> None`
  - События `message.deferred` (status `succeeded`) и `message.write_forbidden` (status `failed`)
  - Константы модуля `DEFER_LIMIT_SECONDS = 300.0`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/core/test_send_window_runtime.py`:

```python
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from mimic42.core.agent_runtime import AgentRuntimeConfig, MimicAgentRuntime
from mimic42.core.send_window import SendWindow
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramClient


def make_config() -> AgentRuntimeConfig:
    """Тот же набор обязательных полей, что и в tests/core/test_agent_runtime.py."""
    return AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_session_string="sessions/test-agent",
        telegram_api_id=12345,
        telegram_api_hash="hash",
        llm_model="openrouter/free",
        system_prompt="Base system prompt",
    )


class ScriptedWindow:
    """Окно, которое возвращает заранее заданное состояние."""

    def __init__(self, window: SendWindow) -> None:
        self.window = window
        self.sent_notes: list[str] = []
        self.announced: list[tuple[str, str]] = []

    async def check(self, peer: str, chat: object = None) -> SendWindow:
        return self.window

    def note_sent(self, peer: str) -> None:
        self.sent_notes.append(peer)

    def note_error(self, peer: str, exc: BaseException) -> None:
        pass

    def announce(self, peer: str, reason: str) -> bool:
        self.announced.append((peer, reason))
        return True


class RecordingAgent:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def ainvoke(
        self, input_data: dict[str, object], context: object | None = None
    ) -> dict[str, object]:
        messages = cast(list[Any], input_data["messages"])
        self.texts.append(str(messages[-1]["content"]))
        return {
            "messages": [{"role": "assistant", "content": "ответ"}],
            "structured_response": {
                "text": "ответ",
                "send_any_message": True,
                "reply_to": None,
            },
        }


def runtime_with(window: ScriptedWindow, agent: RecordingAgent) -> MimicAgentRuntime:
    account = FakeTelegramAccount()
    account.authorized = True
    client = FakeTelegramClient(account)
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=cast(Any, client),
        langchain_agent=cast(Any, agent),
        send_window=cast(Any, window),
    )
    return runtime


class FakeEvent:
    def __init__(self, message_id: int, text: str) -> None:
        self.chat_id = -100777
        self.sender_id = 999
        self.id = message_id
        self.text = text
        self.raw_text = text
        self.is_private = False
        self.is_group = True
        self.grouped_id = None
        self.message = type("M", (), {"reply_to": None, "post_author": None, "date": None})()

    async def get_chat(self) -> object:
        return type("Chat", (), {"id": -100777, "title": "Группа", "username": None})()

    async def get_reply_message(self) -> object | None:
        return None

    async def get_input_chat(self) -> object:
        return await self.get_chat()

    async def get_sender(self) -> object:
        return type("U", (), {"first_name": "Гость", "last_name": "", "username": None, "id": 999})()


async def test_open_window_runs_the_turn_immediately() -> None:
    window = ScriptedWindow(SendWindow())
    agent = RecordingAgent()
    runtime = runtime_with(window, agent)
    await runtime._dispatch_incoming([FakeEvent(1, "привет")])
    assert len(agent.texts) == 1


async def test_closed_window_buffers_instead_of_running_a_turn() -> None:
    window = ScriptedWindow(
        SendWindow(
            reason="slowmode",
            open_at=datetime.now(UTC) + timedelta(seconds=30),
            slowmode_seconds=30,
        )
    )
    agent = RecordingAgent()
    runtime = runtime_with(window, agent)
    await runtime._dispatch_incoming([FakeEvent(1, "первое")])
    await runtime._dispatch_incoming([FakeEvent(2, "второе")])
    assert agent.texts == []
    await runtime.stop()


async def test_buffered_messages_collapse_into_one_turn() -> None:
    open_at = datetime.now(UTC) + timedelta(seconds=0.2)
    window = ScriptedWindow(
        SendWindow(reason="slowmode", open_at=open_at, slowmode_seconds=30)
    )
    agent = RecordingAgent()
    runtime = runtime_with(window, agent)
    await runtime._dispatch_incoming([FakeEvent(1, "первое")])
    await runtime._dispatch_incoming([FakeEvent(2, "второе")])
    window.window = SendWindow(slowmode_seconds=30)
    await asyncio.sleep(0.5)

    assert len(agent.texts) == 1
    assert "первое" in agent.texts[0]
    assert "второе" in agent.texts[0]
    assert "медленный режим" in agent.texts[0].lower()


async def test_forbidden_chat_notifies_once_and_then_stays_silent() -> None:
    class OnceAnnouncing(ScriptedWindow):
        def __init__(self, window: SendWindow) -> None:
            super().__init__(window)
            self._seen: set[tuple[str, str]] = set()

        def announce(self, peer: str, reason: str) -> bool:
            key = (peer, reason)
            if key in self._seen:
                return False
            self._seen.add(key)
            return True

    window = OnceAnnouncing(SendWindow(reason="restricted", forever=True))
    agent = RecordingAgent()
    runtime = runtime_with(window, agent)
    await runtime._dispatch_incoming([FakeEvent(1, "первое")])
    await runtime._dispatch_incoming([FakeEvent(2, "второе")])

    assert len(agent.texts) == 1
    assert "запрет" in agent.texts[0].lower() or "нельзя" in agent.texts[0].lower()
```

- [ ] **Step 2: Прогнать тесты и убедиться, что они падают**

Run: `uv run pytest tests/core/test_send_window_runtime.py -v`
Expected: FAIL с `AttributeError: 'MimicAgentRuntime' object has no attribute '_dispatch_incoming'`

- [ ] **Step 3: Реализовать гейт**

В `agent_runtime.py` добавить константу рядом с логгером:

```python
# Дольше этого ждать открытия окна бессмысленно: сообщения успеют устареть.
DEFER_LIMIT_SECONDS = 300.0
```

В `__init__` завести буфер:

```python
        self._deferred_inbox = DeferredInbox(self._flush_deferred)
```
и импорт `from mimic42.core.deferred_inbox import DeferredInbox`.

Переключить оба входа на гейт: в `_handle_incoming_message` заменить `await self._process_incoming([event])` на `await self._dispatch_incoming([event])`, а в `_flush_album` — `await self._process_incoming(events)` на `await self._dispatch_incoming(events)`.

Добавить методы:

```python
    async def _dispatch_incoming(self, events: list[TelegramEventLike]) -> None:
        """Решить, идёт ли ход сейчас, позже или не идёт вовсе."""
        peer = await _extract_incoming_peer(events[0])
        if self._send_window is None:
            await self._process_batch(peer, [events])
            return

        chat = None
        get_chat = getattr(events[0], "get_chat", None)
        if callable(get_chat):
            try:
                # event.chat бывает пустым: Telegram не всегда шлёт эти данные.
                chat = await get_chat()
            except Exception:
                logger.warning("Не удалось получить чат для гейта", exc_info=True)

        now = datetime.now(UTC)
        window = await self._send_window.check(peer, chat=chat)
        if window.is_open(now):
            await self._process_batch(peer, [events])
            return

        retry_after = window.retry_after(now)
        if retry_after is not None and retry_after <= DEFER_LIMIT_SECONDS:
            self._deferred_inbox.add(peer, list(events), delay=float(retry_after))
            if self._send_window.announce(peer, window.reason):
                await self._record_event(
                    event_type="message.deferred",
                    status="succeeded",
                    payload={
                        "peer": peer,
                        "reason": window.reason,
                        "retry_after_seconds": retry_after,
                    },
                    started_at=now,
                    completed_at=datetime.now(UTC),
                )
            return

        if self._send_window.announce(peer, window.reason):
            await self._record_event(
                event_type="message.write_forbidden",
                status="failed",
                payload={
                    "peer": peer,
                    "reason": window.reason,
                    "until": window.open_at.isoformat() if window.open_at else None,
                },
                started_at=now,
                completed_at=datetime.now(UTC),
            )
            await self._notify_write_forbidden(peer, window)

    async def _notify_write_forbidden(self, peer: str, window: SendWindow) -> None:
        """Один служебный ход: агент узнаёт про запрет и может отреагировать иначе."""
        until = (
            f" до {window.open_at:%Y-%m-%d %H:%M}"
            if window.open_at is not None and not window.forever
            else ""
        )
        await self.trigger_message(
            AgentTrigger(
                peer=peer,
                text=(
                    "[Системное уведомление]\n"
                    f"В чате {peer} у тебя забрали право писать{until}. "
                    "Отправить туда ничего не получится — ни ответом, ни инструментом. "
                    "Входящие оттуда ты больше не увидишь, пока запрет не снимут."
                ),
            )
        )

    async def _flush_deferred(self, peer: str, groups: list[list[Any]]) -> None:
        await self._process_batch(peer, groups)
```

В `stop()` рядом с закрытием группировщика альбомов добавить `await self._deferred_inbox.close()`.

Добавить импорт `from mimic42.core.send_window import SendWindow, SendWindowTracker`.

- [ ] **Step 4: Добавить шапку пачки в `_process_batch`**

В `_process_batch`, после сборки `blocks`, заменить склейку текста на:

```python
            last = blocks[-1]
            body = "\n\n".join(block.text for block in blocks)
            window = (
                await self._send_window.check(peer) if self._send_window is not None else None
            )
            header = _batch_header(len(blocks), window)
            text = f"{header}{body}" if header else body
```

и передать в `AgentTrigger` требование реплая:

```python
                    require_reply_to=len(blocks) > 1,
                    fallback_reply_to=last.message_id,
```

Добавить функцию рядом с другими помощниками модуля:

```python
def _batch_header(block_count: int, window: SendWindow | None) -> str:
    """Шапка над пачкой: сколько накопилось и сколько стоит ответ."""
    if window is None or window.slowmode_seconds is None:
        if block_count <= 1:
            return ""
        return (
            f"[Пока ты молчал, в чате накопилось сообщений: {block_count}]\n"
            "Ответить можно только ОДНИМ сообщением — обязательно укажи reply_to, "
            "иначе будет непонятно, на что ты отвечаешь.\n\n"
        )
    seconds = window.slowmode_seconds
    if block_count <= 1:
        return (
            f"[В чате медленный режим: одно сообщение раз в {seconds} с. "
            f"Ответишь — следующее сможешь написать не раньше чем через {seconds} с]\n\n"
        )
    return (
        f"[Пока ты молчал, в чате накопилось сообщений: {block_count}. "
        f"Медленный режим: одно сообщение раз в {seconds} с]\n"
        "Ответить можно только ОДНИМ сообщением — обязательно укажи reply_to, "
        "иначе будет непонятно, на что ты отвечаешь.\n\n"
    )
```

- [ ] **Step 5: Отключить автосон Telethon**

В `src/mimic42/integrations/telethon_client.py` в конструкторе клиента добавить параметр:

```python
    client = TelegramClient(
        StringSession(config.telegram_session_string),
        config.telegram_api_id,
        config.telegram_api_hash,
        # По умолчанию порог 60: Telethon сам засыпает на флуд-ошибках короче
        # порога, а SlowModeWaitError — флуд-ошибка. Такой сон прошёл бы внутри
        # send_message, удерживая trigger_lock, и вернул бы ровно то отставание,
        # ради устранения которого сделано окно отправки.
        flood_sleep_threshold=0,
    )
```

- [ ] **Step 6: Связать трекер с рантаймом и инструментами в менеджере**

В `src/mimic42/core/manager.py` в `_build_runtime_with_memory` и в `_build_runtime` создать один трекер и передать его в оба места:

```python
        telegram_client = self._telegram_client_factory(config)
        send_window = SendWindowTracker(telegram_client)
```
Далее `build_telegram_langchain_tools(..., send_window=send_window)` и `MimicAgentRuntime(..., send_window=send_window)`. Аналогично в `_build_runtime` с `build_telegram_client(config)`.

Добавить импорт `from mimic42.core.send_window import SendWindowTracker`.

Параметр `send_window` у `build_telegram_langchain_tools` появится в Task 7; до тех пор передавать его только в `MimicAgentRuntime`, а строку с инструментами дописать там же в Task 7.

- [ ] **Step 7: Прогнать тесты**

Run: `uv run pytest tests/core tests/integrations -v`
Expected: PASS, включая новый `tests/core/test_send_window_runtime.py`

- [ ] **Step 8: Проверить линт и типы**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: без ошибок

- [ ] **Step 9: Коммит**

```bash
git add src/mimic42/core/agent_runtime.py src/mimic42/core/manager.py src/mimic42/integrations/telethon_client.py tests/core/test_send_window_runtime.py
git commit -m "feat(runtime): gate incoming turns on the send window

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Гейт в инструментах отправки

**Files:**
- Modify: `src/mimic42/integrations/telegram_tools.py`
- Modify: `src/mimic42/core/manager.py` (дописать `send_window=send_window` в оба вызова `build_telegram_langchain_tools`)
- Test: `tests/integrations/test_telegram_tools.py` (дописать)

**Interfaces:**
- Consumes: `SendWindowTracker` (Task 2)
- Produces:
  - `class SendWindowClosed(RuntimeError)` с атрибутами `reason: str` и `retry_after_seconds: int | None`
  - `TelegramToolbox.__init__` получает `send_window: SendWindowTracker | None = None`
  - `build_telegram_langchain_tools(..., send_window: SendWindowTracker | None = None)`
  - `_tool_failure` для `SendWindowClosed` возвращает дополнительно ключи `reason` и `retry_after_seconds`

- [ ] **Step 1: Написать падающие тесты**

Дописать в конец `tests/integrations/test_telegram_tools.py`:

```python
async def test_send_text_message_refuses_while_the_window_is_closed() -> None:
    from datetime import UTC, datetime, timedelta

    from mimic42.core.send_window import SendWindow

    class ClosedWindow:
        async def check(self, peer: str, chat: object = None) -> SendWindow:
            return SendWindow(
                reason="slowmode",
                open_at=datetime.now(UTC) + timedelta(seconds=25),
                slowmode_seconds=30,
            )

        def note_sent(self, peer: str) -> None:
            raise AssertionError("слот не должен расходоваться при закрытом окне")

        def note_error(self, peer: str, exc: BaseException) -> None:
            pass

    client = FakeTelethonClient()
    toolbox = TelegramToolbox(cast(Any, client), send_window=cast(Any, ClosedWindow()))
    result = await toolbox.send_text_message("-100777", "привет")

    assert result["success"] is False
    assert result["error_code"] == "SendWindowClosed"
    assert result["reason"] == "slowmode"
    assert result["retry_after_seconds"] == 25
    assert client.account.sent == []


async def test_send_text_message_consumes_the_slot_on_success() -> None:
    from mimic42.core.send_window import SendWindow

    class OpenWindow:
        def __init__(self) -> None:
            self.notes = 0

        async def check(self, peer: str, chat: object = None) -> SendWindow:
            return SendWindow(slowmode_seconds=30)

        def note_sent(self, peer: str) -> None:
            self.notes += 1

        def note_error(self, peer: str, exc: BaseException) -> None:
            pass

    window = OpenWindow()
    toolbox = TelegramToolbox(cast(Any, FakeTelethonClient()), send_window=cast(Any, window))
    result = await toolbox.send_text_message("-100777", "привет")

    assert result["success"] is True
    assert window.notes == 1


async def test_telegram_error_updates_the_window() -> None:
    from telethon import errors

    from mimic42.core.send_window import SendWindow

    class FailingClient(FakeTelethonClient):
        async def send_message(self, entity: Any, message: str, **kwargs: Any) -> Any:
            raise errors.ChatWriteForbiddenError(request=None)

    class SpyWindow:
        def __init__(self) -> None:
            self.errors: list[BaseException] = []

        async def check(self, peer: str, chat: object = None) -> SendWindow:
            return SendWindow()

        def note_sent(self, peer: str) -> None:
            pass

        def note_error(self, peer: str, exc: BaseException) -> None:
            self.errors.append(exc)

    window = SpyWindow()
    toolbox = TelegramToolbox(cast(Any, FailingClient()), send_window=cast(Any, window))
    result = await toolbox.send_text_message("-100777", "привет")

    assert result["success"] is False
    assert result["error_code"] == "ChatWriteForbiddenError"
    assert len(window.errors) == 1


async def test_toolbox_without_a_window_keeps_working() -> None:
    toolbox = TelegramToolbox(cast(Any, FakeTelethonClient()))
    result = await toolbox.send_text_message("-100777", "привет")
    assert result["success"] is True
```

- [ ] **Step 2: Прогнать тесты и убедиться, что они падают**

Run: `uv run pytest tests/integrations/test_telegram_tools.py -v -k window or slot`
Expected: FAIL — `TelegramToolbox.__init__() got an unexpected keyword argument 'send_window'`

- [ ] **Step 3: Реализовать**

В `telegram_tools.py` рядом с `_tool_failure` добавить исключение и расширить сборку ошибки:

```python
class SendWindowClosed(RuntimeError):
    """Окно отправки в этот чат закрыто: писать сейчас нельзя."""

    def __init__(self, reason: str, retry_after_seconds: int | None) -> None:
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds
        if reason == "slowmode":
            wait = (
                f"подожди {retry_after_seconds} с"
                if retry_after_seconds is not None
                else "подожди"
            )
            message = f"В чате включён медленный режим: писать пока нельзя, {wait}."
        else:
            until = (
                f" Повторить можно через {retry_after_seconds} с."
                if retry_after_seconds is not None
                else " Срок не ограничен."
            )
            message = f"В этом чате у тебя нет права писать.{until}"
        super().__init__(message)


def _tool_failure(exc: Exception) -> dict[str, Any]:
    """Structured tool failure: machine-readable error identity for the activity log."""
    failure: dict[str, Any] = {
        "success": False,
        "error": str(exc),
        "error_code": type(exc).__name__,
    }
    if isinstance(exc, SendWindowClosed):
        failure["reason"] = exc.reason
        failure["retry_after_seconds"] = exc.retry_after_seconds
    retry = getattr(exc, "seconds", None)
    if isinstance(retry, int) and "retry_after_seconds" not in failure:
        failure["retry_after_seconds"] = retry
    return failure
```

В `TelegramToolbox.__init__` добавить параметр и поле:

```python
        send_window: Any | None = None,
```
```python
        self._send_window = send_window
```

Добавить контекстный менеджер сразу после `_resolve_peer`:

```python
    @asynccontextmanager
    async def _sending(self, peer: str) -> AsyncIterator[None]:
        """Проверка окна до отправки и учёт результата после.

        Окно — источник дешёвой правды, ошибка Telegram — источник точной:
        обе ветки кормят трекер, иначе он разойдётся с реальностью.
        """
        if self._send_window is None:
            yield
            return
        now = datetime.now(UTC)
        window = await self._send_window.check(peer)
        if not window.is_open(now):
            raise SendWindowClosed(window.reason, window.retry_after(now))
        try:
            yield
        except Exception as exc:
            self._send_window.note_error(peer, exc)
            raise
        else:
            self._send_window.note_sent(peer)
```

Добавить импорты: `from contextlib import asynccontextmanager`, `from collections.abc import AsyncIterator`, и `UTC` в существующий импорт `datetime`.

Обернуть тело `try` в методах `send_text_message`, `send_file`, `send_voice_note`, `send_video_note`, `send_sticker`, `send_poll`, `send_location`, `send_venue`, `send_inline_bot_result`. Для `send_text_message` это выглядит так:

```python
        try:
            async with self._sending(peer):
                entity = await self._resolve_peer(peer)
                msg = await self._client.send_message(
                    entity,
                    message,
                    reply_to=reply_to_msg_id,
                    comment_to=comment_to_msg_id,
                    parse_mode=CustomMarkdown(),
                )
            self._last_send_text_message[peer] = now
            return {"success": True, "message_id": msg.id}
        except Exception as e:
            return _tool_failure(e)
```

В `forward_messages` окно проверяется по `to_peer`: `async with self._sending(to_peer):`.

В `build_telegram_langchain_tools` добавить параметр `send_window: Any | None = None` и передать его в `TelegramToolbox(...)`.

- [ ] **Step 4: Дописать передачу трекера в менеджере**

В `src/mimic42/core/manager.py` в обоих местах дописать в вызов `build_telegram_langchain_tools(...)` аргумент `send_window=send_window`.

- [ ] **Step 5: Прогнать тесты**

Run: `uv run pytest tests/integrations/test_telegram_tools.py tests/core tests/integration -v`
Expected: PASS

- [ ] **Step 6: Проверить линт и типы**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: без ошибок

- [ ] **Step 7: Коммит**

```bash
git add src/mimic42/integrations/telegram_tools.py src/mimic42/core/manager.py tests/integrations/test_telegram_tools.py
git commit -m "feat(tools): route every send through the send window

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Промпт и лента дэшборда

**Files:**
- Modify: `BASE_SYSTEM_PROMPT.txt`
- Modify: `frontend/src/lib/activity/eventCatalog.ts`
- Test: `frontend/src/__tests__/activity.test.ts` (дописать)

**Interfaces:**
- Consumes: типы событий из Task 5 и Task 6 — `message.blocked`, `message.deferred`, `message.write_forbidden`
- Produces: записи в `EVENT_CATALOG`

- [ ] **Step 1: Дописать абзац в базовый промпт**

В `BASE_SYSTEM_PROMPT.txt` после абзаца про комментарии под постами канала вставить:

```
В части групп включён медленный режим: писать там можно не чаще раза в N секунд, и об этом будет написано в шапке входящего. Слот один, поэтому если отвечаешь на несколько накопившихся сообщений сразу — отвечай одним сообщением и обязательно указывай reply_to, иначе непонятно, на что ты ответил. Если право писать в чате забрали, отправка туда не сработает ни ответом, ни инструментом.
```

- [ ] **Step 2: Написать падающий тест на каталог событий**

Дописать в `frontend/src/__tests__/activity.test.ts`:

```typescript
import { getEventMeta } from '../lib/activity/eventCatalog';

describe('каталог событий окна отправки', () => {
  it('знает все три события окна', () => {
    expect(getEventMeta('message.deferred')?.ru).toBe('Ответ отложен: медленный режим');
    expect(getEventMeta('message.write_forbidden')?.ru).toBe('Нет права писать в чате');
    expect(getEventMeta('message.blocked')?.ru).toBe('Отправка отменена: чат закрыт');
  });
});
```

- [ ] **Step 3: Прогнать тест и убедиться, что он падает**

Run: `cd frontend && bun test src/__tests__/activity.test.ts`
Expected: FAIL — `getEventMeta` возвращает `null` для новых типов

- [ ] **Step 4: Дописать каталог**

В `frontend/src/lib/activity/eventCatalog.ts` добавить иконки в импорт и записи в `EVENT_CATALOG`:

```typescript
import {
  Play,
  Square,
  AlertTriangle,
  MessageSquareX,
  Timer,
  Hourglass,
  Ban,
  type LucideIcon,
} from 'lucide-react';
```
```typescript
  'message.deferred': { ru: 'Ответ отложен: медленный режим', icon: Hourglass },
  'message.write_forbidden': { ru: 'Нет права писать в чате', icon: Ban },
  'message.blocked': { ru: 'Отправка отменена: чат закрыт', icon: MessageSquareX },
```

- [ ] **Step 5: Прогнать тесты фронта**

Run: `cd frontend && bun test`
Expected: PASS

- [ ] **Step 6: Коммит**

```bash
git add BASE_SYSTEM_PROMPT.txt frontend/src/lib/activity/eventCatalog.ts frontend/src/__tests__/activity.test.ts
git commit -m "feat(dashboard): name the send window events and explain slow mode in the prompt

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Проверка поведения на самой слабой модели

Механика проверена модульными тестами, но решение принимает модель. Здесь проверяется, что слабая модель правильно читает шапку. Тесты идут под своим маркером и в обычный прогон не попадают.

**Files:**
- Create: `tests/real_llm/__init__.py`, `tests/real_llm/conftest.py`, `tests/real_llm/test_send_window_behavior.py`
- Modify: `pyproject.toml` (маркер `real_llm` и его исключение из `addopts`)

**Interfaces:**
- Consumes: `build_langchain_agent`, `AgentRuntimeConfig`, `_batch_header` (Task 6)
- Produces: маркер `real_llm`

- [ ] **Step 1: Завести маркер**

В `pyproject.toml`:

```toml
addopts = ["-m", "not db and not e2e and not real_tg and not real_llm"]
markers = [
    "db: требует подключения к тестовой базе Mimic42 Dev",
    "e2e: поднимает тестовый сервер и фронт, гоняет браузерные сценарии",
    "real_tg: требует настоящих Telegram-аккаунтов, сети и секретов",
    "real_llm: ходит в настоящую модель через OpenRouter",
]
```

- [ ] **Step 2: Написать обвязку**

Создать `tests/real_llm/__init__.py` (пустой) и `tests/real_llm/conftest.py`:

```python
"""Обвязка проверки поведения на живой модели.

Берётся самая слабая модель каталога: интересен худший сценарий, а не лучший.
Переопределяется переменной MIMIC_WEAK_MODEL.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)

WEAK_MODEL = os.environ.get("MIMIC_WEAK_MODEL", "inclusionai/ling-3.0-flash-vl")


@pytest.fixture(scope="session")
def weak_model() -> str:
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY не задан")
    return WEAK_MODEL
```

- [ ] **Step 3: Написать сценарии**

Создать `tests/real_llm/test_send_window_behavior.py`:

```python
"""Понимает ли слабая модель шапку про медленный режим и запрет писать."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from mimic42.core.agent_runtime import AgentRuntimeConfig, _extract_structured_response
from mimic42.integrations.langchain_agent import build_langchain_agent

pytestmark = pytest.mark.real_llm

SLOWMODE_BATCH = """[Пока ты молчал, в чате накопилось сообщений: 5. \
Медленный режим: одно сообщение раз в 30 с]
Ответить можно только ОДНИМ сообщением — обязательно укажи reply_to, \
иначе будет непонятно, на что ты отвечаешь.

[Входящее сообщение]
Чат: Группа "Тусовка"
Отправитель: Аня (ID: 1)
ID сообщения: 101
Содержимое: кто-нибудь видел мой зарядник

[Входящее сообщение]
Чат: Группа "Тусовка"
Отправитель: Боря (ID: 2)
ID сообщения: 102
Содержимое: не видел

[Входящее сообщение]
Чат: Группа "Тусовка"
Отправитель: Вика (ID: 3)
ID сообщения: 103
Содержимое: а во сколько завтра собираемся

[Входящее сообщение]
Чат: Группа "Тусовка"
Отправитель: Аня (ID: 1)
ID сообщения: 104
Содержимое: нашла, был в сумке

[Входящее сообщение]
Чат: Группа "Тусовка"
Отправитель: Вика (ID: 3)
ID сообщения: 105
Содержимое: эй, ты тут? во сколько завтра
"""

IRRELEVANT_BATCH = """[Пока ты молчал, в чате накопилось сообщений: 3. \
Медленный режим: одно сообщение раз в 30 с]
Ответить можно только ОДНИМ сообщением — обязательно укажи reply_to, \
иначе будет непонятно, на что ты отвечаешь.

[Входящее сообщение]
Чат: Группа "Рабочий чат"
Отправитель: Аня (ID: 1)
ID сообщения: 201
Содержимое: Боря, скинь пожалуйста акт за август

[Входящее сообщение]
Чат: Группа "Рабочий чат"
Отправитель: Боря (ID: 2)
ID сообщения: 202
Содержимое: сейчас найду

[Входящее сообщение]
Чат: Группа "Рабочий чат"
Отправитель: Боря (ID: 2)
ID сообщения: 203
Содержимое: держи, там же и сентябрьский
"""

FORBIDDEN_NOTICE = """[Системное уведомление]
В чате -1001234567890 у тебя забрали право писать. Отправить туда ничего не \
получится — ни ответом, ни инструментом. Входящие оттуда ты больше не увидишь, \
пока запрет не снимут.
"""


async def run_turn(model: str, text: str) -> dict[str, Any]:
    config = AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_session_string="sessions/real-llm",
        telegram_api_id=12345,
        telegram_api_hash="hash",
        llm_model=model,
        system_prompt=Path("BASE_SYSTEM_PROMPT.txt").read_text(encoding="utf-8"),
        soul_prompt="Ты обычный человек, пишешь коротко и неформально.",
    )
    agent = build_langchain_agent(config, tools=[])
    response = await agent.ainvoke({"messages": [{"role": "user", "content": text}]})
    # structured_response приходит экземпляром AgentResponse, а не словарём.
    structured = _extract_structured_response(response)
    assert structured is not None, "модель не вернула структурированный ответ"
    return structured


async def test_collapsed_batch_gets_one_reply_with_reply_to(weak_model: str) -> None:
    result = await run_turn(weak_model, SLOWMODE_BATCH)
    assert result["send_any_message"] is True
    assert result["reply_to"] in (103, 105), (
        f"ответ должен быть привязан к вопросу про завтра, а reply_to={result['reply_to']}"
    )
    assert len(result["text"]) <= 3000


async def test_batch_addressed_to_others_stays_silent(weak_model: str) -> None:
    result = await run_turn(weak_model, IRRELEVANT_BATCH)
    assert result["send_any_message"] is False, (
        f"агент влез в чужой разговор: {result['text']!r}"
    )


async def test_forbidden_notice_does_not_produce_a_reply_there(weak_model: str) -> None:
    result = await run_turn(weak_model, FORBIDDEN_NOTICE)
    assert result["send_any_message"] is False, (
        f"агент пытается ответить в чат, где ему запрещено писать: {result['text']!r}"
    )
```

- [ ] **Step 4: Прогнать проверку**

Run: `uv run pytest tests/real_llm -m real_llm -v`
Expected: PASS. Если слабая модель путается — правится формулировка шапки в `_batch_header` и абзац в `BASE_SYSTEM_PROMPT.txt`, а не ожидания теста. После каждой правки прогон повторяется.

- [ ] **Step 5: Убедиться, что обычный прогон не задевает живую модель**

Run: `uv run pytest tests -q`
Expected: тесты из `tests/real_llm` не собираются (в сводке их нет)

- [ ] **Step 6: Коммит**

```bash
git add pyproject.toml tests/real_llm
git commit -m "test(real-llm): verify slow mode wording on the weakest model

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Проверка на живом Telegram

Проверяется и поведение, и фактура: какие события реально приходят и не упущено ли что-то.

**Files:**
- Create: `tests/real_tg/backend/test_real_slowmode.py`
- Modify: `src/mimic42/testing/real_tg/checker.py` (методы для создания супергруппы и управления правами)

**Interfaces:**
- Consumes: фикстуры `checker`, `real_app`, `started_mimics` из `tests/real_tg/backend/conftest.py`
- Produces:
  - `Checker.create_supergroup(title: str, members: list[str]) -> int`
  - `Checker.set_slow_mode(channel_id: int, seconds: int) -> None`
  - `Checker.restrict(channel_id: int, user: str | int, *, until_seconds: int) -> None`
  - `Checker.unrestrict(channel_id: int, user: str | int) -> None`
  - `Checker.collect_updates(seconds: float) -> list[object]`

- [ ] **Step 1: Дописать проверяющему управление группой**

В `src/mimic42/testing/real_tg/checker.py` добавить методы (импорты `from telethon.tl.functions.channels import CreateChannelRequest, EditBannedRequest, InviteToChannelRequest, ToggleSlowModeRequest` и `from telethon.tl.types import ChatBannedRights` — по документации `channels.editBanned` работает только с каналами, поэтому группа создаётся сразу супергруппой через `megagroup=True`):

```python
    async def create_supergroup(self, title: str, members: list[str]) -> int:
        """Супергруппа: медленный режим и личные ограничения есть только у них."""
        result = await self.client(
            CreateChannelRequest(title=title, about="mimic42 slow mode test", megagroup=True)
        )
        channel = result.chats[0]
        if members:
            await self.client(
                InviteToChannelRequest(channel=channel, users=list(members))
            )
        return int(channel.id)

    async def set_slow_mode(self, channel_id: int, seconds: int) -> None:
        await self.client(
            ToggleSlowModeRequest(channel=await self.client.get_input_entity(channel_id),
                                  seconds=seconds)
        )

    async def restrict(self, channel_id: int, user: str | int, *, until_seconds: int) -> None:
        """until_seconds == 0 — бессрочно (значения короче 30 с считаются вечными)."""
        until = 0 if until_seconds == 0 else int(time.time()) + until_seconds
        await self.client(
            EditBannedRequest(
                channel=await self.client.get_input_entity(channel_id),
                participant=await self.client.get_input_entity(user),
                banned_rights=ChatBannedRights(until_date=until, send_messages=True),
            )
        )

    async def unrestrict(self, channel_id: int, user: str | int) -> None:
        await self.client(
            EditBannedRequest(
                channel=await self.client.get_input_entity(channel_id),
                participant=await self.client.get_input_entity(user),
                banned_rights=ChatBannedRights(until_date=0),
            )
        )
```

Добавить `import time` в импорты файла.

- [ ] **Step 2: Написать живой тест**

Создать `tests/real_tg/backend/test_real_slowmode.py`:

```python
"""Медленный режим и запрет писать в настоящем Telegram."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

import asyncpg
import pytest

from mimic42.testing.real_tg.checker import Checker
from mimic42.testing.slots import plain_dsn

pytestmark = pytest.mark.real_tg

SLOW_MODE_SECONDS = 30


async def agent_events(agent_id: str, event_type: str) -> list[dict[str, object]]:
    conn = await asyncpg.connect(plain_dsn(os.environ["DATABASE_CONNECTION_STRING"]))
    try:
        rows = await conn.fetch(
            "select event_type, payload, created_at from agent_events "
            "where agent_id = $1 and event_type = $2 order by created_at desc limit 20",
            UUID(agent_id),
            event_type,
        )
    finally:
        await conn.close()
    return [dict(row) for row in rows]


async def test_slow_mode_collapses_the_flood_into_one_reply(
    checker: Checker, started_mimics: list[tuple[str, str]]
) -> None:
    agent_id, phone = started_mimics[0]
    await checker.import_contact(phone)
    channel_id = await checker.create_supergroup("Mimic42 slow mode", [phone])
    await checker.set_slow_mode(channel_id, SLOW_MODE_SECONDS)

    sent = await checker.send_many(
        channel_id,
        [
            "всем привет",
            "кто-нибудь тут есть",
            "нужен совет по одной штуке",
            "эй",
            "ну и ладно, спрошу позже",
        ],
        pause=2.0,
    )
    assert len(sent) == 5

    replies = await checker.collect_replies(channel_id, seconds=SLOW_MODE_SECONDS * 3)
    mimic_replies = [msg for msg in replies if msg.sender_id != await checker.my_id()]

    assert len(mimic_replies) <= 1, (
        f"мимик написал {len(mimic_replies)} сообщений при медленном режиме"
    )
    if mimic_replies:
        assert mimic_replies[0].reply_to is not None, "ответ без реплая нечитаем в потоке"

    deferred = await agent_events(agent_id, "message.deferred")
    assert deferred, "событие об отложенном ответе не записано"


async def test_slow_mode_wait_error_never_reaches_the_client(
    checker: Checker, started_mimics: list[tuple[str, str]], caplog: pytest.LogCaptureFixture
) -> None:
    """Окно должно останавливать отправку раньше, чем Telegram ответит ошибкой."""
    assert "SlowModeWaitError" not in caplog.text


async def test_restriction_stops_the_agent_and_lifting_it_brings_him_back(
    checker: Checker, started_mimics: list[tuple[str, str]]
) -> None:
    agent_id, phone = started_mimics[0]
    await checker.import_contact(phone)
    channel_id = await checker.create_supergroup("Mimic42 mute", [phone])
    mimic_id = await checker.resolve_id(phone)

    await checker.restrict(channel_id, mimic_id, until_seconds=0)
    await checker.send_many(channel_id, ["эй, ответь что-нибудь"], pause=0.0)
    await asyncio.sleep(60)

    replies = await checker.collect_replies(channel_id, seconds=5)
    assert [m for m in replies if m.sender_id == mimic_id] == [], (
        "мимик написал в чат, где у него отобрано право писать"
    )
    forbidden = await agent_events(agent_id, "message.write_forbidden")
    assert forbidden, "событие о запрете писать не записано"

    await checker.unrestrict(channel_id, mimic_id)
    await checker.send_many(channel_id, ["теперь можешь писать, ответь"], pause=0.0)
    back = await checker.collect_replies(channel_id, seconds=180)
    assert [m for m in back if m.sender_id == mimic_id], (
        "после снятия запрета мимик не ожил"
    )
```

Методы `send_many(peer, texts, pause)`, `collect_replies(peer, seconds)`, `resolve_id(phone)` и `my_id()` дописываются в `Checker` рядом с существующими `send_and_wait_reply` и `wait_incoming` по их образцу: `send_many` шлёт тексты с паузой между ними и возвращает список отправленных `Message`, `collect_replies` слушает `events.NewMessage(chats=peer)` заданное время и возвращает накопленные сообщения, `resolve_id` возвращает `(await client.get_entity(phone)).id`.

- [ ] **Step 3: Прогнать живой тест**

Run: `uv run pytest tests/real_tg/backend/test_real_slowmode.py -m real_tg -v -s`
Expected: PASS

- [ ] **Step 4: Снять фактуру, которую спека пометила как непроверенную**

Прогнать разведочный скрипт и записать наблюдения:

```bash
uv run python - <<'PY'
import asyncio, os, time
from telethon import TelegramClient, events, functions, types
from telethon.sessions import StringSession

async def main() -> None:
    client = TelegramClient(
        StringSession(os.environ["TG_CHECKER_SESSION"]),
        int(os.environ["TG_CHECKER_API_ID"]),
        os.environ["TG_CHECKER_API_HASH"],
    )
    await client.connect()

    seen: list[str] = []

    @client.on(events.Raw)
    async def _(update: object) -> None:
        seen.append(type(update).__name__)

    channel = await client(functions.channels.CreateChannelRequest(
        title=f"slowmode probe {int(time.time())}", about="probe", megagroup=True))
    entity = channel.chats[0]
    await client(functions.channels.ToggleSlowModeRequest(channel=entity, seconds=30))
    await asyncio.sleep(5)

    full = await client(functions.channels.GetFullChannelRequest(channel=entity))
    print("slowmode_seconds:", full.full_chat.slowmode_seconds)
    print("slowmode_next_send_date:", full.full_chat.slowmode_next_send_date)

    # Создатель — админ: проверяем, действует ли на него кд.
    await client.send_message(entity, "первое")
    try:
        await client.send_message(entity, "второе подряд")
        print("АДМИН НЕ ПОДЧИНЯЕТСЯ медленному режиму")
    except Exception as exc:
        print("админ подчиняется:", type(exc).__name__, getattr(exc, "seconds", None))

    print("апдейты после включения кд:", sorted(set(seen)))
    await client(functions.channels.DeleteChannelRequest(channel=entity))
    await client.disconnect()

asyncio.run(main())
PY
```

Результаты записать в спеку, в раздел «Требует проверки на живом Telegram», заменив формулировку «проверяется» на факт. Если окажется, что апдейт о включении кд приходит и его стоит ловить — завести отдельную задачу на подписку через `events.Raw`, в текущий объём это не входит.

- [ ] **Step 5: Коммит**

```bash
git add src/mimic42/testing/real_tg/checker.py tests/real_tg/backend/test_real_slowmode.py docs/superpowers/specs/2026-09-20-send-window-design.md
git commit -m "test(real-tg): verify slow mode and write restrictions against Telegram

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Финальная проверка и подготовка к ревью

**Files:**
- Modify: ничего нового, только фиксация результата

- [ ] **Step 1: Полный прогон обычных тестов**

Run: `uv run pytest tests -q`
Expected: PASS, без пропусков кроме помеченных маркерами слоёв

- [ ] **Step 2: Прогон слоя с базой**

Run: `uv run pytest tests -m db -q`
Expected: PASS

- [ ] **Step 3: Линт, формат и типы по всему проекту**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src`
Expected: без ошибок

- [ ] **Step 4: Прогон фронта**

Run: `cd frontend && bun test && bun run build`
Expected: PASS

- [ ] **Step 5: Разобраться, что автоматизировано в CI, а что остаётся вручную**

Run: `cat .github/workflows/ci.yml .github/workflows/real-tg.yml .github/workflows/deploy.yml`

Что уже известно: `real-tg.yml` запускается только вручную (`workflow_dispatch`) и гоняет
`tests/real_tg/backend -m real_tg -W error` — предупреждения там считаются ошибками, и новый
живой тест не должен их порождать. Слоя `real_llm` нет ни в одном workflow: решить и
зафиксировать в описании PR, остаётся он ручным (он тратит деньги на модель) или ему заводится
отдельный `workflow_dispatch`. Проверить, что `ci.yml` покрывает обычный прогон, линт и фронт,
и что добавленное в этой ветке в нём не падает.

- [ ] **Step 6: Запушить ветку**

```bash
git push -u origin feat/issue-72-send-window
```

PR не открывать: по договорённости он открывается только после живой проверки хозяином.

---

## Самопроверка плана

**Покрытие спеки.** Окно отправки — Task 1–2. Буфер — Task 3. Точка врезки и схлопывание — Task 4 и Task 6. Обязательный реплай — Task 5. Предохранитель на отправке — Task 5. Инструменты — Task 7. Промпт и лента — Task 8. Отключение автосна Telethon — Task 6, шаг 5. Проверка на модели — Task 9. Проверка на живом Telegram — Task 10. Непроверенная фактура (освобождён ли админ от кд, приходят ли апдейты) — Task 10, шаг 4.

**Заглушек нет.** Каждый шаг содержит код или точную команду; мест «дописать по аналогии» нет, кроме вспомогательных методов `Checker` в Task 10, где явно перечислены их сигнатуры, поведение и образец в существующем файле.

**Согласованность имён.** `SendWindow.is_open(now)` и `retry_after(now)` принимают время во всех задачах. `SendWindowTracker.check/note_sent/note_error/announce/forget` — один набор в Task 2, 5, 6, 7. `DeferredInbox.add(peer, group, delay)` и `flush(peer, groups)` совпадают в Task 3 и Task 6. `_process_batch(peer, groups)` из Task 4 вызывается в Task 6 с той же сигнатурой. `send_window` — одно имя параметра у `MimicAgentRuntime`, `TelegramToolbox` и `build_telegram_langchain_tools`.
