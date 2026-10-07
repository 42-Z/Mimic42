# Target Chats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать пользователю включать и выключать чаты и каналы, доступные Мимику (`agents.settings.disabled_chats`): отключённый чат не запускает ходы, не доступен инструментам и не получает первого комментария; группа комментариев включённого канала доступна вместе с ним.

**Architecture:** Хранение — список ID отключённых чатов в `agents.settings` (миграции БД нет). Бэкенд разбирает его в `AgentRuntimeConfig`, строит политику `ChatAccess` (чистое правило по ID плюс поиск «канал — группа обсуждения» через Telethon) и применяет её в трёх точках: входящие события рантайма, разрешение чата в `TelegramToolbox`, таймеры. Живой список диалогов отдаёт новый `GET /api/v1/agents/{id}/chats` через клиент запущенного рантайма. Фронтенд — секция «Чаты и каналы» в форме «Настройки» по образцу «Инструментов».

**Tech Stack:** Python 3.13 (`uv`, Ruff, ty, pytest), Telethon 1.43.2, FastAPI, SQLAlchemy 2.0 async, Next.js 14 + React 18 + TanStack Query + TypeScript + Tailwind, `bun test` + Testing Library, Playwright через pytest.

**Spec:** `docs/superpowers/specs/2026-10-07-target-chats-design.md`

## Global Constraints

- Формат настройки один: `agents.settings.disabled_chats: number[]` — ID в формате Telethon (marked: `-100…` у каналов и супергрупп, `-…` у обычных групп, положительные у людей и ботов). Ключа нет или список пуст — ограничений нет. Никакого второго формата и никакого режима «новые чаты выключены».
- Чат доступен, пока его ID нет в `disabled_chats`; новые чаты доступны автоматически. Группа обсуждения доступна, если включён её канал (даже когда сама она отключена).
- Разбор настройки терпимый: мусор не роняет агента и не отключает чаты случайно. Не удалось узнать связь «канал — группа» — закрыто по умолчанию (чат недоступен).
- Прогрев не подчиняется настройке: личные сообщения от другого мимика проходят, зачины не проверяются.
- Миграций БД нет. Новых Python-зависимостей нет. `BASE_SYSTEM_PROMPT.txt`, память, `POST /agents/{id}/reload`, пресеты и онбординг не меняются.
- Люди (`user`, `users`, `bot_username`, `get_profile`, контакты, приватность) не проверяются: настройка управляет чатами.
- Все пользовательские строки — на русском. Комментарии в коде — doc-комментарии на русском, без «заголовочных»; по стилю соседнего кода.
- Python-команды — через `uv run`; фронтенд — `bun run --cwd=frontend <скрипт>` (без `cd`). Не склеивать команды через `&&`.
- Тесты не способ отладки: пишутся вместе с кодом, прогон — один раз в Task 11 (после ревью диффа). Вывод линтеров и тестов не обрезать.
- Коммиты: Conventional Commits, тема одна строка по-русски, в конце трейлеры `Co-Authored-By` и `Claude-Session` из контекста сессии. Файлы добавлять по путям (`git add <пути>`), перед коммитом `git diff --cached --stat`. Никакого `git add -A`.
- Ветка `feat/target-chats`. Push можно, **PR — только после того, как пользователь сам проверил приложение локально**.

**Отличия от спеки:**
- Кеш связи «группа → канал» (TTL 1 час) живёт в `TelethonChatDirectory.discussion_of`, а не в `ChatAccess`: тот же кеш обслуживает и список чатов для API. `ChatAccess` получает готовую функцию поиска.
- Типы `ChatItem`/`ChatDirectory` вынесены в `core/chat_directory.py`, чтобы рантайм и API не зависели от `integrations`.
- В `ChatAccess.allows` есть подсказка `has_link` (признак `Channel.has_link`): `False` снимает лишний запрос, когда сущность уже под рукой.
- Помимо переключателей в секцию добавлена кнопка «Обновить список» (иконка), потому что список кешируется на минуту.

## Review Focus

Входные данные и условия, которые спека подразумевает, но которых нет в основных сценариях; тест на каждую строку живёт в задаче-владельце.

1. **`peer="me"` / «Избранное»** с отключённым собственным ID: `InputPeerSelf` не приводится `utils.get_peer_id`, нужен `client.get_peer_id` → Task 4.
2. **Числовая строка вместо @username** (`"-1000000000002"`): `_resolve_peer` превращает её в `int`, проверка обязана сработать и на ней → Task 4.
3. **Мусор в `disabled_chats`** (строки, `true`, дробные, не список): агент поднимается, чаты не отключаются → Task 1 (бэкенд) и Task 7 (фронтенд).
4. **Сбой запроса `GetFullChannel`** при проверке группы обсуждения: чат недоступен, исключение не вылетает наружу, неудача не кешируется → Task 1 и Task 2.
5. **Отключённые ID, которых нет в живом списке** (вышел из чата, агент остановлен): интерфейс их показывает, и при переключении другого чата они не теряются → Task 7 и Task 8.

---

### Task 1: Политика доступа и типы каталога

**Files:**
- Create: `src/mimic42/core/chat_access.py`
- Create: `src/mimic42/core/chat_directory.py`
- Test: `tests/core/test_chat_access.py`

**Interfaces:**
- Consumes: ничего.
- Produces:
  - `ChatDisabledError(chat_id: int | None = None)` (`.chat_id`; текст «Чат недоступен: он отключён в настройках агента.»).
  - `parse_disabled_chats(raw: Any) -> frozenset[int]`.
  - `link_hint(entity: Any) -> bool | None` — значение `has_link` сущности, если это настоящий `bool`, иначе `None`.
  - `DiscussionLookup = Callable[[int], Awaitable[int | None]]`.
  - `ChatAccess(disabled: frozenset[int], discussion_of: DiscussionLookup)`; `.disabled: frozenset[int]`; `async allows(chat_id: int, *, has_link: bool | None = None) -> bool`.
  - `ChatKind = Literal["channel", "group", "private"]`; `ChatItem` (pydantic, frozen: `id: int`, `title: str`, `username: str | None`, `kind: ChatKind`, `discussion_of: int | None`); `ChatDirectory` Protocol (`async list_chats() -> list[ChatItem]`, `async discussion_of(chat_id: int) -> int | None`).

- [ ] **Step 1: Создать `src/mimic42/core/chat_directory.py`**

```python
"""Диалоги аккаунта для настройки доступных агенту чатов."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

ChatKind = Literal["channel", "group", "private"]


class ChatItem(BaseModel):
    """Диалог аккаунта: то, что пользователь включает и выключает в настройках."""

    model_config = ConfigDict(frozen=True)

    id: int
    title: str
    username: str | None = None
    kind: ChatKind
    # Marked ID канала, если это группа обсуждения (комментарии) его постов.
    discussion_of: int | None = None


class ChatDirectory(Protocol):
    async def list_chats(self) -> list[ChatItem]: ...

    async def discussion_of(self, chat_id: int) -> int | None:
        """Marked ID канала, чья группа обсуждения — ``chat_id``; ``None`` — не она."""
        ...
```

- [ ] **Step 2: Создать `src/mimic42/core/chat_access.py`**

```python
"""Какие чаты доступны агенту (settings.disabled_chats).

Чат доступен, пока его ID нет в списке отключённых: новые чаты и каналы
включаются сами. Исключение — комментарии: группа обсуждения доступна, если
включён её канал. Нечитаемое значение не должно ни ронять агента, ни отключать
чаты случайно, поэтому разбор терпимый.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("mimic42.chat_access")

# Marked ID каналов и супергрупп — «-100» и ID канала: всё левее порога — Channel.
# Группой обсуждения может быть только супергруппа, остальным поиск связи не нужен.
_MIN_PLAIN_CHAT_ID = -1_000_000_000_000

DiscussionLookup = Callable[[int], Awaitable[int | None]]


class ChatDisabledError(Exception):
    """Инструмент или таймер обратились к чату, отключённому в настройках агента."""

    def __init__(self, chat_id: int | None = None) -> None:
        super().__init__("Чат недоступен: он отключён в настройках агента.")
        self.chat_id = chat_id


def parse_disabled_chats(raw: Any) -> frozenset[int]:
    """Разобрать ``settings.disabled_chats``: только целые, остальное отбрасывается."""
    if raw is None:
        return frozenset()
    if not isinstance(raw, (list, tuple)):
        logger.warning(
            "disabled_chats has unexpected type %s; no chats disabled", type(raw).__name__
        )
        return frozenset()
    return frozenset(item for item in raw if isinstance(item, int) and not isinstance(item, bool))


def link_hint(entity: Any) -> bool | None:
    """Признак ``Channel.has_link`` у сущности: связана ли она с обсуждением или каналом.

    Настоящий ``bool`` приходит у разобранных сущностей Telegram; у остальных
    (InputPeer, заглушки) признак неизвестен, и вызывающему придётся спросить.
    """
    value = getattr(entity, "has_link", None)
    return value if isinstance(value, bool) else None


class ChatAccess:
    """Правило доступа по ID чата. Создаётся только при непустом списке отключённых."""

    def __init__(self, disabled: frozenset[int], discussion_of: DiscussionLookup) -> None:
        self._disabled = disabled
        self._discussion_of = discussion_of

    @property
    def disabled(self) -> frozenset[int]:
        return self._disabled

    async def allows(self, chat_id: int, *, has_link: bool | None = None) -> bool:
        """Доступен ли чат агенту.

        ``has_link=False`` — сущность уже в руках и связи с каналом у неё нет:
        запрос не нужен. Сбой поиска считается «не связана».
        """
        if chat_id not in self._disabled:
            return True
        if chat_id > _MIN_PLAIN_CHAT_ID or has_link is False:
            return False
        try:
            channel_id = await self._discussion_of(chat_id)
        except Exception:
            logger.warning(
                "Failed to find the channel of discussion group %s", chat_id, exc_info=True
            )
            return False
        return channel_id is not None and channel_id not in self._disabled
```

- [ ] **Step 3: Написать `tests/core/test_chat_access.py`**

```python
"""Правило доступа к чатам: отключённые, комментарии, терпимый разбор."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mimic42.core.chat_access import (
    ChatAccess,
    ChatDisabledError,
    link_hint,
    parse_disabled_chats,
)

CHANNEL = -1001111111111
GROUP = -1002222222222
OTHER_GROUP = -1003333333333


def _access(
    disabled: set[int], links: dict[int, int | None] | None = None
) -> tuple[ChatAccess, list[int]]:
    calls: list[int] = []

    async def discussion_of(chat_id: int) -> int | None:
        calls.append(chat_id)
        return (links or {}).get(chat_id)

    return ChatAccess(frozenset(disabled), discussion_of), calls


def test_missing_key_disables_nothing() -> None:
    assert parse_disabled_chats(None) == frozenset()


def test_list_of_ids_becomes_the_disabled_set() -> None:
    assert parse_disabled_chats([CHANNEL, 42, -7]) == frozenset({CHANNEL, 42, -7})


def test_garbage_items_are_dropped() -> None:
    # bool — подкласс int: «true» из ручной правки JSON не должен стать ID 1.
    assert parse_disabled_chats([CHANNEL, True, "42", 1.5, None]) == frozenset({CHANNEL})


def test_unexpected_type_disables_nothing() -> None:
    assert parse_disabled_chats({"id": CHANNEL}) == frozenset()
    assert parse_disabled_chats("42") == frozenset()


def test_link_hint_trusts_only_real_booleans() -> None:
    assert link_hint(SimpleNamespace(has_link=True)) is True
    assert link_hint(SimpleNamespace(has_link=False)) is False
    assert link_hint(SimpleNamespace(has_link=None)) is None
    assert link_hint(SimpleNamespace()) is None
    assert link_hint(SimpleNamespace(has_link=object())) is None


def test_disabled_error_tells_the_model_why() -> None:
    error = ChatDisabledError(42)
    assert error.chat_id == 42
    assert "отключён в настройках агента" in str(error)
    assert ChatDisabledError().chat_id is None


@pytest.mark.asyncio
async def test_chats_are_available_by_default() -> None:
    access, calls = _access({42})
    assert await access.allows(7) is True
    assert await access.allows(CHANNEL) is True
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_id", [42, -777, CHANNEL])
async def test_disabled_private_basic_and_channel_chats_are_refused(chat_id: int) -> None:
    access, _ = _access({chat_id})
    assert await access.allows(chat_id) is False


@pytest.mark.asyncio
async def test_no_lookup_for_chats_that_cannot_be_discussion_groups() -> None:
    access, calls = _access({42, -777})
    await access.allows(42)
    await access.allows(-777)
    assert calls == []


@pytest.mark.asyncio
async def test_discussion_group_of_an_enabled_channel_is_available() -> None:
    access, calls = _access({GROUP}, {GROUP: CHANNEL})
    assert await access.allows(GROUP) is True
    assert calls == [GROUP]


@pytest.mark.asyncio
async def test_discussion_group_of_a_disabled_channel_is_refused() -> None:
    access, _ = _access({GROUP, CHANNEL}, {GROUP: CHANNEL})
    assert await access.allows(GROUP) is False


@pytest.mark.asyncio
async def test_disabled_supergroup_without_a_channel_is_refused() -> None:
    access, _ = _access({OTHER_GROUP}, {OTHER_GROUP: None})
    assert await access.allows(OTHER_GROUP) is False


@pytest.mark.asyncio
async def test_entity_without_a_link_skips_the_lookup() -> None:
    access, calls = _access({GROUP}, {GROUP: CHANNEL})
    assert await access.allows(GROUP, has_link=False) is False
    assert calls == []
    assert await access.allows(GROUP, has_link=True) is True


@pytest.mark.asyncio
async def test_lookup_failure_closes_the_chat() -> None:
    attempts = 0

    async def failing(chat_id: int) -> int | None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("FLOOD_WAIT")

    access = ChatAccess(frozenset({GROUP}), failing)

    assert await access.allows(GROUP) is False
    # Неудача не запоминается: следующая проверка пробует снова.
    assert await access.allows(GROUP) is False
    assert attempts == 2
```

- [ ] **Step 4: Перечитать модуль против спеки**

Сверить с разделом «Политика» спеки: `allows` для не-супергрупп не делает запросов; `has_link=False` снимает запрос; сбой — `False`; `disabled` — публичное свойство (его читает рантайм). Расхождения — исправить в коде.

- [ ] **Step 5: Commit**

```bash
git add src/mimic42/core/chat_access.py src/mimic42/core/chat_directory.py tests/core/test_chat_access.py
git diff --cached --stat
git commit -m "feat(chats): политика доступа к чатам и типы каталога диалогов"
```

---

### Task 2: Каталог диалогов и связь «канал — группа» через Telethon

**Files:**
- Create: `src/mimic42/integrations/chat_directory.py`
- Test: `tests/integrations/test_chat_directory.py`

**Interfaces:**
- Consumes: `ChatItem`, `ChatKind` из Task 1.
- Produces:
  - `DirectoryClient` Protocol (`iter_dialogs`, `get_input_entity`, `__call__`).
  - `chat_kind(entity: Any) -> ChatKind`.
  - `TelethonChatDirectory(client: DirectoryClient, *, clock: Callable[[], float] = time.monotonic)` — реализует `ChatDirectory`: `async list_chats() -> list[ChatItem]` (кеш 60 с), `async discussion_of(chat_id: int) -> int | None` (кеш 1 час, только успехи).
  - Константы `LINK_CACHE_TTL_SECONDS = 3600.0`, `LIST_CACHE_TTL_SECONDS = 60.0`, `SAVED_MESSAGES_TITLE = "Избранное"`.

Документация к прочтению перед кодом: Telethon `iter_dialogs` (`folder`: 0 — основной список, 1 — архив), `client.get_input_entity`, `GetFullChannelRequest` → `full_chat.linked_chat_id` (симметрично: у супергруппы это канал), `utils.get_peer_id`/`utils.resolve_id` (https://docs.telethon.dev/en/stable/concepts/chats-vs-channels.html).

- [ ] **Step 1: Создать `src/mimic42/integrations/chat_directory.py`**

```python
"""Диалоги аккаунта и связь «канал — группа обсуждения» через Telethon."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

from telethon import functions, types, utils

from mimic42.core.chat_directory import ChatItem, ChatKind

logger = logging.getLogger("mimic42.chat_directory")

LINK_CACHE_TTL_SECONDS = 3600.0
LIST_CACHE_TTL_SECONDS = 60.0
SAVED_MESSAGES_TITLE = "Избранное"
# Основной список и архив: Telegram отдаёт архив папкой 1.
_DIALOG_FOLDERS = (0, 1)
# Запросов GetFullChannel одновременно: у аккаунта с сотнями групп обсуждения
# первая загрузка списка иначе упирается во флуд-лимит.
_LOOKUP_CONCURRENCY = 5


class DirectoryClient(Protocol):
    def iter_dialogs(self, limit: int | None = None, **kwargs: Any) -> Any: ...
    async def get_input_entity(self, entity: Any) -> Any: ...
    async def __call__(self, request: object) -> Any: ...


def chat_kind(entity: Any) -> ChatKind:
    """Вещательный канал, группа (в т. ч. супергруппа) или личный диалог."""
    if isinstance(entity, types.User):
        return "private"
    if isinstance(entity, types.Channel):
        return "group" if entity.megagroup else "channel"
    return "group"


class TelethonChatDirectory:
    """Список диалогов для настроек и поиск канала по его группе обсуждения."""

    def __init__(
        self, client: DirectoryClient, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._client = client
        self._clock = clock
        self._links: dict[int, tuple[int | None, float]] = {}
        self._listing: tuple[list[ChatItem], float] | None = None
        self._lookup_slots = asyncio.Semaphore(_LOOKUP_CONCURRENCY)

    async def discussion_of(self, chat_id: int) -> int | None:
        """Marked ID канала, чья группа обсуждения — ``chat_id``; ``None`` — не она.

        Успех кешируется на час; сбой поднимается вызывающему и не запоминается.
        """
        cached = self._links.get(chat_id)
        if cached is not None and cached[1] > self._clock():
            return cached[0]
        channel_id = await self._fetch_discussion_of(chat_id)
        self._links[chat_id] = (channel_id, self._clock() + LINK_CACHE_TTL_SECONDS)
        return channel_id

    async def _fetch_discussion_of(self, chat_id: int) -> int | None:
        real_id, _ = utils.resolve_id(chat_id)
        input_chat = await self._client.get_input_entity(chat_id)
        full = await self._client(functions.channels.GetFullChannelRequest(channel=input_chat))
        group = next((chat for chat in full.chats if getattr(chat, "id", None) == real_id), None)
        # Связь у вещательного канала указывает на его обсуждение, а не наоборот:
        # «канала, чьей группой он был бы» у него нет.
        if not (isinstance(group, types.Channel) and group.megagroup):
            return None
        linked = getattr(full.full_chat, "linked_chat_id", None)
        if not isinstance(linked, int):
            return None
        return utils.get_peer_id(types.PeerChannel(linked))

    async def list_chats(self) -> list[ChatItem]:
        if self._listing is not None and self._listing[1] > self._clock():
            return self._listing[0]
        dialogs = await self._read_dialogs()
        items = list(await asyncio.gather(*(self._to_item(dialog) for dialog in dialogs)))
        self._listing = (items, self._clock() + LIST_CACHE_TTL_SECONDS)
        return items

    async def _read_dialogs(self) -> list[Any]:
        seen: set[int] = set()
        dialogs: list[Any] = []
        for folder in _DIALOG_FOLDERS:
            async for dialog in self._client.iter_dialogs(folder=folder):
                if dialog.id in seen:
                    continue
                seen.add(dialog.id)
                dialogs.append(dialog)
        return dialogs

    async def _to_item(self, dialog: Any) -> ChatItem:
        entity = dialog.entity
        is_self = bool(getattr(entity, "is_self", False))
        discussion_of: int | None = None
        # Признак has_link есть у самой сущности: запрос нужен только супергруппам,
        # которые чьи-то обсуждения.
        if (
            isinstance(entity, types.Channel)
            and entity.megagroup
            and bool(getattr(entity, "has_link", False))
        ):
            discussion_of = await self._safe_discussion_of(dialog.id)
        return ChatItem(
            id=dialog.id,
            title=SAVED_MESSAGES_TITLE if is_self else (dialog.title or str(dialog.id)),
            username=getattr(entity, "username", None),
            kind=chat_kind(entity),
            discussion_of=discussion_of,
        )

    async def _safe_discussion_of(self, chat_id: int) -> int | None:
        async with self._lookup_slots:
            try:
                return await self.discussion_of(chat_id)
            except Exception:
                logger.warning(
                    "Failed to find the channel of discussion group %s", chat_id, exc_info=True
                )
                return None
```

- [ ] **Step 2: Написать `tests/integrations/test_chat_directory.py`**

```python
"""Каталог диалогов: виды чатов, архив, группы обсуждения, кеши."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from telethon import functions, types

from mimic42.core.chat_directory import ChatItem
from mimic42.integrations.chat_directory import (
    LINK_CACHE_TTL_SECONDS,
    LIST_CACHE_TTL_SECONDS,
    TelethonChatDirectory,
    chat_kind,
)

DATE = datetime(2026, 1, 1, tzinfo=UTC)
CHANNEL_ID = -1001000000001
GROUP_ID = -1001000000002


def _channel(real_id: int, title: str, *, megagroup: bool, has_link: bool = False) -> Any:
    return types.Channel(
        id=real_id,
        title=title,
        photo=types.ChatPhotoEmpty(),
        date=DATE,
        access_hash=1,
        broadcast=not megagroup or None,
        megagroup=megagroup or None,
        has_link=has_link or None,
        username=f"u{real_id}",
    )


def _user(real_id: int, name: str, *, is_self: bool = False) -> Any:
    return types.User(id=real_id, first_name=name, access_hash=1, is_self=is_self or None)


def _dialog(marked_id: int, title: str, entity: Any) -> Any:
    return SimpleNamespace(id=marked_id, title=title, entity=entity)


class FakeDirectoryClient:
    def __init__(
        self,
        main: list[Any] | None = None,
        archive: list[Any] | None = None,
        links: dict[int, int | None] | None = None,
    ) -> None:
        self.folders = {0: main or [], 1: archive or []}
        # реальный ID группы → реальный ID канала (или None)
        self.links = links or {}
        self.requests: list[Any] = []
        self.fail_lookups = False

    def iter_dialogs(self, limit: int | None = None, **kwargs: Any) -> Any:
        dialogs = self.folders[kwargs["folder"]]

        async def gen() -> Any:
            for dialog in dialogs:
                yield dialog

        return gen()

    async def get_input_entity(self, entity: Any) -> Any:
        return types.InputPeerChannel(channel_id=abs(entity) - 1_000_000_000_000, access_hash=1)

    async def __call__(self, request: object) -> Any:
        assert isinstance(request, functions.channels.GetFullChannelRequest)
        self.requests.append(request)
        if self.fail_lookups:
            raise RuntimeError("FLOOD_WAIT")
        real_id = request.channel.channel_id  # type: ignore[union-attr]
        if real_id in self.links:
            group = _channel(real_id, "g", megagroup=True, has_link=True)
        else:
            group = _channel(real_id, "c", megagroup=False, has_link=True)
        linked = self.links.get(real_id)
        return SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=linked), chats=[group])


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_chat_kinds() -> None:
    assert chat_kind(_user(7, "Анна")) == "private"
    assert chat_kind(_channel(1, "Новости", megagroup=False)) == "channel"
    assert chat_kind(_channel(2, "Чат", megagroup=True)) == "group"
    chat = types.Chat(
        id=3, title="Старая группа", photo=types.ChatPhotoEmpty(), participants_count=2,
        date=DATE, version=1,
    )  # fmt: skip
    assert chat_kind(chat) == "group"


@pytest.mark.asyncio
async def test_list_merges_main_list_and_archive_without_duplicates() -> None:
    news = _dialog(CHANNEL_ID, "Новости", _channel(1000000001, "Новости", megagroup=False))
    anna = _dialog(7, "Анна", _user(7, "Анна"))
    client = FakeDirectoryClient(main=[news, anna], archive=[anna])
    directory = TelethonChatDirectory(client)

    items = await directory.list_chats()

    assert [(item.id, item.kind, item.title) for item in items] == [
        (CHANNEL_ID, "channel", "Новости"),
        (7, "private", "Анна"),
    ]
    assert all(isinstance(item, ChatItem) for item in items)
    assert items[0].username == "u1000000001"


@pytest.mark.asyncio
async def test_own_chat_is_titled_saved_messages() -> None:
    me = _dialog(777, "Janna", _user(777, "Janna", is_self=True))
    directory = TelethonChatDirectory(FakeDirectoryClient(main=[me]))

    assert (await directory.list_chats())[0].title == "Избранное"


@pytest.mark.asyncio
async def test_discussion_group_points_to_its_channel() -> None:
    group = _dialog(
        GROUP_ID, "Комментарии", _channel(1000000002, "Комментарии", megagroup=True, has_link=True)
    )
    client = FakeDirectoryClient(main=[group], links={1000000002: 1000000001})
    directory = TelethonChatDirectory(client)

    (item,) = await directory.list_chats()

    assert item.kind == "group"
    assert item.discussion_of == CHANNEL_ID


@pytest.mark.asyncio
async def test_plain_supergroup_triggers_no_lookup() -> None:
    group = _dialog(GROUP_ID, "Чат", _channel(1000000002, "Чат", megagroup=True))
    client = FakeDirectoryClient(main=[group])

    (item,) = await TelethonChatDirectory(client).list_chats()

    assert item.discussion_of is None
    assert client.requests == []


@pytest.mark.asyncio
async def test_failed_lookup_leaves_the_link_empty_without_breaking_the_list() -> None:
    group = _dialog(
        GROUP_ID, "Комментарии", _channel(1000000002, "Комментарии", megagroup=True, has_link=True)
    )
    client = FakeDirectoryClient(main=[group], links={1000000002: 1000000001})
    client.fail_lookups = True

    (item,) = await TelethonChatDirectory(client).list_chats()

    assert item.title == "Комментарии"
    assert item.discussion_of is None


@pytest.mark.asyncio
async def test_discussion_of_resolves_the_marked_id_of_the_channel() -> None:
    client = FakeDirectoryClient(links={1000000002: 1000000001})
    directory = TelethonChatDirectory(client)

    assert await directory.discussion_of(GROUP_ID) == CHANNEL_ID


@pytest.mark.asyncio
async def test_broadcast_channel_is_not_a_discussion_group() -> None:
    # У вещательного канала linked_chat_id — его обсуждение, а не «его канал».
    client = FakeDirectoryClient(links={})
    directory = TelethonChatDirectory(client)

    assert await directory.discussion_of(CHANNEL_ID) is None


@pytest.mark.asyncio
async def test_link_is_cached_for_an_hour_then_refreshed() -> None:
    clock = Clock()
    client = FakeDirectoryClient(links={1000000002: 1000000001})
    directory = TelethonChatDirectory(client, clock=clock)

    await directory.discussion_of(GROUP_ID)
    await directory.discussion_of(GROUP_ID)
    assert len(client.requests) == 1

    clock.now += LINK_CACHE_TTL_SECONDS + 1
    await directory.discussion_of(GROUP_ID)
    assert len(client.requests) == 2


@pytest.mark.asyncio
async def test_failed_lookup_is_raised_and_not_cached() -> None:
    client = FakeDirectoryClient(links={1000000002: 1000000001})
    client.fail_lookups = True
    directory = TelethonChatDirectory(client)

    with pytest.raises(RuntimeError):
        await directory.discussion_of(GROUP_ID)

    client.fail_lookups = False
    assert await directory.discussion_of(GROUP_ID) == CHANNEL_ID


@pytest.mark.asyncio
async def test_listing_is_cached_for_a_minute() -> None:
    clock = Clock()
    anna = _dialog(7, "Анна", _user(7, "Анна"))
    client = FakeDirectoryClient(main=[anna])
    directory = TelethonChatDirectory(client, clock=clock)

    first = await directory.list_chats()
    client.folders[0].append(_dialog(8, "Борис", _user(8, "Борис")))
    assert await directory.list_chats() == first

    clock.now += LIST_CACHE_TTL_SECONDS + 1
    assert [item.id for item in await directory.list_chats()] == [7, 8]
```

- [ ] **Step 3: Перечитать код против документации**

Открыть https://docs.telethon.dev/en/stable/concepts/chats-vs-channels.html и `iter_dialogs` в исходниках Telethon: `folder=0/1`, `linked_chat_id` читается из `full.full_chat`, группа ищется в `full.chats` по реальному ID. Убедиться, что `types.Channel` в тестах строится с обязательными `id/title/photo/date`.

- [ ] **Step 4: Commit**

```bash
git add src/mimic42/integrations/chat_directory.py tests/integrations/test_chat_directory.py
git diff --cached --stat
git commit -m "feat(chats): каталог диалогов и связь канала с группой обсуждения"
```

---

### Task 3: Конфиг, хранилище настроек и сборка в менеджере

**Files:**
- Modify: `src/mimic42/core/agent_runtime.py` (`AgentRuntimeConfig`, `MimicAgentRuntime.__init__` — только параметры, логика в Task 5)
- Modify: `src/mimic42/integrations/database_agent_store.py:296-304`
- Modify: `src/mimic42/core/manager.py:327-392`
- Modify: `src/mimic42/integrations/telegram_tools.py` (`build_telegram_langchain_tools`, `TelegramToolbox.__init__` — только параметр; логика в Task 4)
- Test: `tests/core/test_chat_access_wiring.py`, `tests/integration/test_database_agent_store.py` (маркер `db`)

**Interfaces:**
- Consumes: `parse_disabled_chats`, `ChatAccess` (Task 1); `TelethonChatDirectory`, `DirectoryClient` (Task 2).
- Produces:
  - `AgentRuntimeConfig.disabled_chats: frozenset[int]` (по умолчанию пустое).
  - `MimicAgentRuntime.__init__(..., chat_access: ChatAccess | None = None, chat_directory: ChatDirectory | None = None)`.
  - `TelegramToolbox.__init__(..., chat_access: ChatAccess | None = None)`; `build_telegram_langchain_tools(..., chat_access: ChatAccess | None = None)`.
  - `AgentManager` и `_build_runtime` передают `chat_access` (None при пустом списке) в сборщик инструментов и рантайм, а каталог — в рантайм.

- [ ] **Step 1: Поле конфига**

В `src/mimic42/core/agent_runtime.py` импорты (после блока `from mimic42.core.album_grouper import AlbumGrouper`):

```python
from mimic42.core.chat_access import ChatAccess
from mimic42.core.chat_directory import ChatDirectory
```

В `AgentRuntimeConfig` после `enabled_tools`:

```python
    # ID чатов, отключённых в настройках; пусто — доступны все.
    disabled_chats: frozenset[int] = Field(default=frozenset())
```

В `MimicAgentRuntime.__init__` — параметры после `media_refs`:

```python
        media_refs: MediaRefCache | None = None,
        chat_access: ChatAccess | None = None,
        chat_directory: ChatDirectory | None = None,
    ) -> None:
```

и в теле после `self._media_refs = ...`:

```python
        # Правило доступа к чатам общее с инструментами; None — отключённых нет.
        self._chat_access = chat_access
        self._chat_directory = chat_directory
```

- [ ] **Step 2: Разбор в хранилище**

В `src/mimic42/integrations/database_agent_store.py` импорт рядом с `parse_enabled_tools`:

```python
from mimic42.core.chat_access import parse_disabled_chats
```

В `get_runtime_config` после `enabled_tools=...`:

```python
                disabled_chats=parse_disabled_chats(
                    agent.settings.get("disabled_chats") if agent.settings else None
                ),
```

- [ ] **Step 3: Параметр сборщика инструментов (логика — Task 4)**

В `telegram_tools.py`: импорт `from mimic42.core.chat_access import ChatAccess, ChatDisabledError, link_hint` (в Task 3 нужен только `ChatAccess`; остальное — Task 4). В `TelegramToolbox.__init__` добавить параметр `chat_access: ChatAccess | None = None` после `media_refs` и `self._chat_access = chat_access`. В `build_telegram_langchain_tools` добавить параметр `chat_access: ChatAccess | None = None` после `enabled_tools` и передать `chat_access=chat_access` в `TelegramToolbox(...)`.

- [ ] **Step 4: Сборка в менеджере**

В `src/mimic42/core/manager.py` импорты:

```python
from mimic42.core.chat_access import ChatAccess
from mimic42.integrations.chat_directory import DirectoryClient, TelethonChatDirectory
```

Две функции модуля (перед `_build_runtime`):

```python
def _chat_directory_for(telegram_client: TelegramClientLike) -> TelethonChatDirectory:
    return TelethonChatDirectory(cast(DirectoryClient, telegram_client))


def _chat_access_for(
    config: AgentRuntimeConfig, directory: TelethonChatDirectory
) -> ChatAccess | None:
    """Правило доступа есть только у агента с отключёнными чатами."""
    if not config.disabled_chats:
        return None
    return ChatAccess(config.disabled_chats, directory.discussion_of)
```

В `_build_runtime_with_memory` и `_build_runtime` — после создания `telegram_client` добавить:

```python
        directory = _chat_directory_for(telegram_client)
        chat_access = _chat_access_for(config, directory)
```

и передать:
- в `build_telegram_langchain_tools(...)`: `chat_access=chat_access,`
- в `MimicAgentRuntime(...)`: `chat_access=chat_access, chat_directory=directory,`

(в `_build_runtime` отступ на уровень функции, без `self`.)

- [ ] **Step 5: Тесты сборки `tests/core/test_chat_access_wiring.py`**

```python
"""Менеджер строит правило доступа к чатам и передаёт его и инструментам, и рантайму."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from mimic42.core import manager as manager_module
from mimic42.core.agent_runtime import AgentRuntimeConfig
from mimic42.core.chat_access import ChatAccess
from mimic42.core.manager import AgentManager
from mimic42.core.memory import RuntimeMemoryService

from .test_agent_runtime import FakeLangChainAgent, FakeTelegramClient


def _config(disabled: frozenset[int] = frozenset()) -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_api_id=12345,
        telegram_api_hash="hash",
        telegram_session_string="session",
        system_prompt="system",
        soul_prompt="soul",
        llm_model="mistral-small",
        disabled_chats=disabled,
    )


def _memory_manager() -> AgentManager:
    return AgentManager(
        memory_service_factory=lambda config: RuntimeMemoryService(),
        telegram_client_factory=lambda config: FakeTelegramClient(),
        langchain_agent_factory=lambda config, tools, session_factory: FakeLangChainAgent(),
    )


def _capture_tool_builder(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def capturing_builder(client: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(manager_module, "build_telegram_langchain_tools", capturing_builder)
    return captured


def test_memory_runtime_without_disabled_chats_has_no_access_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_tool_builder(monkeypatch)

    runtime = _memory_manager()._build_runtime_with_memory(_config())

    assert captured["chat_access"] is None
    assert runtime._chat_access is None
    assert runtime._chat_directory is not None


def test_memory_runtime_shares_one_access_rule_with_the_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_tool_builder(monkeypatch)

    runtime = _memory_manager()._build_runtime_with_memory(_config(frozenset({-1001, 42})))

    access = captured["chat_access"]
    assert isinstance(access, ChatAccess)
    assert access.disabled == frozenset({-1001, 42})
    assert runtime._chat_access is access


def test_default_runtime_passes_the_access_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_tool_builder(monkeypatch)
    monkeypatch.setattr(
        manager_module, "build_telegram_client", lambda config: FakeTelegramClient()
    )
    monkeypatch.setattr(
        manager_module, "build_langchain_agent", lambda *args, **kwargs: FakeLangChainAgent()
    )

    runtime = manager_module._build_runtime(_config(frozenset({42})))

    assert isinstance(captured["chat_access"], ChatAccess)
    assert runtime._chat_access is captured["chat_access"]
    assert runtime._chat_directory is not None
```

- [ ] **Step 6: DB-тесты разбора в `tests/integration/test_database_agent_store.py`**

Добавить после `test_get_runtime_config_without_enabled_tools_enables_all`:

```python
async def test_get_runtime_config_parses_disabled_chats(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()
    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(_make_session(owner_id, agent_id, "Mimic"))
    async with db_session_factory() as db_session:
        await db_session.execute(
            update(AgentModel)
            .where(AgentModel.id == agent_id)
            .values(settings={"disabled_chats": [-1001234567890, 42, "junk", True]})
        )
        await db_session.commit()

    config = await store.get_runtime_config(agent_id)

    assert config.disabled_chats == frozenset({-1001234567890, 42})


async def test_get_runtime_config_without_disabled_chats_disables_nothing(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("full").user_id
    agent_id = uuid4()
    store = DatabaseAgentStore(db_session_factory)
    await store.create_from_onboarding(_make_session(owner_id, agent_id, "Mimic"))

    config = await store.get_runtime_config(agent_id)

    assert config.disabled_chats == frozenset()
```

- [ ] **Step 7: Commit**

```bash
git add src/mimic42/core/agent_runtime.py src/mimic42/core/manager.py src/mimic42/integrations/database_agent_store.py src/mimic42/integrations/telegram_tools.py tests/core/test_chat_access_wiring.py tests/integration/test_database_agent_store.py
git diff --cached --stat
git commit -m "feat(chats): настройка отключённых чатов в конфиге рантайма и сборке менеджера"
```

---

### Task 4: Проверка доступа в инструментах Telegram

**Files:**
- Modify: `src/mimic42/integrations/telegram_tools.py`
- Test: `tests/integrations/test_telegram_tools_chat_access.py`

**Interfaces:**
- Consumes: `ChatAccess`, `ChatDisabledError`, `link_hint` (Task 1); параметр `chat_access` в `TelegramToolbox` (Task 3).
- Produces (внутри `TelegramToolbox`):
  - `async _resolve_chat(peer: Any, as_input: bool = True) -> Any` — `_resolve_peer` плюс проверка;
  - `async _guard_chat(peer: Any) -> None` — только проверка (для инструментов, передающих Telethon сырой peer);
  - `async _ensure_chat_allowed(entity: Any) -> None`;
  - `async _visible_dialogs(limit: int) -> list[Any]`, `async _visible_peers(peers: Any) -> list[dict[str, Any]]`.
  - Протокол `TelethonRequestClient` получает `get_peer_id` и `iter_dialogs`.
  - Отказ: `{"success": False, "error": "Чат недоступен: …", "error_code": "ChatDisabledError"}` (у инструментов-списков — список из одного такого словаря).

Прочитать перед кодом: Telethon `client.get_peer_id` (приводит и `InputPeerSelf`), `utils.get_peer_id`; в репозитории — `_resolve_peer` (`telegram_tools.py:505`) и `_tool_failure`/`_safe_failure` (`:146-175`).

- [ ] **Step 1: Протокол клиента и импорты**

В `TelethonRequestClient` добавить:

```python
    async def get_peer_id(self, peer: Any, add_mark: bool = True) -> int: ...
    def iter_dialogs(self, limit: int | None = None, **kwargs: Any) -> Any: ...
```

Импорт: `from mimic42.core.chat_access import ChatAccess, ChatDisabledError, link_hint`.

- [ ] **Step 2: `_safe_failure` не подменяет отказ доступа**

Заменить тело `_safe_failure`:

```python
def _safe_failure(exc: Exception, message: str) -> dict[str, Any]:
    """_tool_failure с безопасным текстом: результат целиком попадает в
    ToolMessage.content, который читает модель, — сырые ошибки Telegram
    («caused by GetFileRequest» и т.п.) ей показывать нельзя.

    Отказ доступа — наш собственный текст: подменять его общим «не удалось»
    значит скрыть от модели настоящую причину.
    """
    failure = _tool_failure(exc)
    if not isinstance(exc, ChatDisabledError):
        failure["error"] = message
    return failure
```

- [ ] **Step 3: Методы проверки в `TelegramToolbox`** (после `_resolve_peer`)

```python
    async def _resolve_chat(self, peer: Any, as_input: bool = True) -> Any:
        """Разрешить чат и убедиться, что он не отключён в настройках агента."""
        entity = await self._resolve_peer(peer, as_input=as_input)
        await self._ensure_chat_allowed(entity)
        return entity

    async def _guard_chat(self, peer: Any) -> None:
        """Проверка для инструментов, отдающих Telethon сырой peer без разрешения."""
        if self._chat_access is not None:
            await self._resolve_chat(peer)

    async def _ensure_chat_allowed(self, entity: Any) -> None:
        if self._chat_access is None:
            return
        # client.get_peer_id приводит и InputPeerSelf («me», Избранное).
        chat_id = await self._client.get_peer_id(entity)
        if not await self._chat_access.allows(chat_id, has_link=link_hint(entity)):
            raise ChatDisabledError(chat_id)

    async def _visible_dialogs(self, limit: int) -> list[Any]:
        """Диалоги без отключённых; читаются порциями, пока не наберётся лимит."""
        access = self._chat_access
        if access is None:
            return list(await self._client.get_dialogs(limit=limit))
        visible: list[Any] = []
        async for dialog in self._client.iter_dialogs():
            if await access.allows(dialog.id, has_link=link_hint(dialog.entity)):
                visible.append(dialog)
                if len(visible) >= limit:
                    break
        return visible

    async def _visible_peers(self, peers: Any) -> list[dict[str, Any]]:
        """Сериализованные пиры папки без отключённых чатов."""
        visible: list[dict[str, Any]] = []
        for peer in peers or []:
            if self._chat_access is not None:
                try:
                    chat_id = utils.get_peer_id(peer)
                except TypeError:
                    chat_id = None  # InputPeerSelf: свой чат не отфильтровать по ID
                if chat_id is not None and not await self._chat_access.allows(
                    chat_id, has_link=link_hint(peer)
                ):
                    continue
            visible.append(self._serialize_peer(peer))
        return visible
```

- [ ] **Step 4: Заменить разрешение чатов в инструментах**

Заменить `self._resolve_peer(` на `self._resolve_chat(` (аргумент `as_input=False` сохранить) в этих методах `TelegramToolbox` — это чат-параметры:

`send_text_message`, `edit_text_message`, `delete_messages`, `forward_messages` (оба: `from_peer`, `to_peer`), `pin_message`, `unpin_message`, `unpin_all_messages`, `send_chat_action`, `send_reaction`, `get_message_reactions`, `mark_chat_as_read`, `get_messages`, `search_messages`, `delete_dialog`, `mute_chat`, `unmute_chat`, `send_file`, `send_voice_note`, `send_video_note`, `send_location`, `send_venue`, `send_sticker`, `get_message_buttons`, `click_inline_button`, `click_reply_keyboard_button`, `query_inline_bot` (только `peer`), `send_inline_bot_result`, `start_bot` (`target`), `get_chat_info`, `check_admin_permissions`, `invite_to_channel` (только `channel`), `get_chat_members`, `get_chat_admin_log`, `edit_chat_title`, `edit_chat_about`, `edit_chat_photo`, `update_chat_public_link`, `set_chat_default_banned_rights`, `toggle_chat_signatures`, `delete_channel`, `toggle_join_requests`, `toggle_join_to_send`, `toggle_slow_mode`, `set_discussion_group` (оба), `join_channel_discussion`, `get_discussion_messages`, `toggle_forum`, `toggle_pre_history_hidden`, `toggle_participants_hidden`, `edit_chat_location`, `toggle_anti_spam`, `set_chat_admin_rights` (только `peer`), `set_chat_banned_rights` (только `peer`), `join_channel` (ветка публичного имени), `send_poll`, `create_or_update_chat_folder` (вложенная `resolve_peers`).

**Остаются на `_resolve_peer`** (люди): `get_common_chats`, `get_profile`, `delete_contact`, `query_inline_bot` (`bot_username`), `create_group`, `invite_to_channel` (`users`), `set_chat_admin_rights`/`set_chat_banned_rights` (`user`), `set_privacy_settings` (оба цикла).

Проверка: `grep -n "_resolve_peer(" src/mimic42/integrations/telegram_tools.py` должен показать ровно 11 строк — определение `_resolve_chat` (внутри него) и перечисленные «людские» вызовы.

`archive_dialogs` / `unarchive_dialogs`: сначала разрешить и проверить все пиры, потом менять — иначе часть чатов успеет заархивироваться до отказа. Тело `try` обоих методов:

```python
            entities = [await self._resolve_chat(p) for p in peers]
            for entity in entities:
                await self._client(
                    functions.folders.EditPeerFoldersRequest(
                        folder_peers=[types.InputFolderPeer(peer=entity, folder_id=1)]
                    )
                )
            return {"success": True}
```

(`folder_id=0` в `unarchive_dialogs`.)

Два инструмента с нестандартной обработкой ошибок — отказ доступа не должен ни теряться, ни подменяться:

- `join_channel`: в **внешнем** `try` перед `except Exception as e:` (он возвращает `{"success": False, "error": f"{type(e).__name__}: …"}` без `error_code`) добавить

```python
        except ChatDisabledError as e:
            return _tool_failure(e)
```

- `create_or_update_chat_folder`: вложенная `resolve_peers` глотает любую ошибку (`except Exception: pass`), и папка молча создалась бы без отключённого чата при `success: True`. Заменить блок на

```python
                for p in peer_list:
                    try:
                        entity = await self._resolve_chat(p)
                        resolved.append(entity)
                    except ChatDisabledError:
                        raise
                    except Exception:
                        pass
```

- [ ] **Step 5: Инструменты с сырым peer — `_guard_chat`**

В начале `try` каждого из методов `kick_chat_member`, `ban_chat_member`, `restrict_chat_member`, `promote_chat_member` добавить первой строкой `await self._guard_chat(peer)`. В `set_wakeup_timer` — первой строкой внутри существующего `try` (до работы с БД): `await self._guard_chat(peer)`.

- [ ] **Step 6: Списки без отключённых чатов**

`get_dialogs` — заменить получение диалогов:

```python
            dialogs_list = await self._visible_dialogs(limit)
```

`get_chat_folders` — в трёх ключах словаря папки заменить списки на вызов (метод стал асинхронным по необходимости: собрать значения до литерала словаря):

```python
                    pinned = await self._visible_peers(f.pinned_peers)
                    included = await self._visible_peers(f.include_peers)
                    excluded = await self._visible_peers(f.exclude_peers)
                    folders.append(
                        {
                            ...
                            "pinned_peers": pinned,
                            "include_peers": included,
                            "exclude_peers": excluded,
                            ...
                        }
                    )
```

`get_common_chats` — в цикле по `res.chats` первой строкой:

```python
                if self._chat_access is not None and not await self._chat_access.allows(
                    utils.get_peer_id(chat), has_link=link_hint(chat)
                ):
                    continue
```

- [ ] **Step 7: Тесты `tests/integrations/test_telegram_tools_chat_access.py`**

```python
"""Инструменты Telegram не работают с чатами, отключёнными в настройках агента."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from telethon import functions, types, utils

from mimic42.core.chat_access import ChatAccess
from mimic42.integrations.telegram_tools import TelegramToolbox
from tests.integrations.test_telegram_tools import FakeTelethonClient

ALLOWED = -1000000000001
BLOCKED = -1000000000002
GROUP = -1000000000003
BLOCKED_USER = 42
OWN_ID = 777
ALIASES = {
    "@allowed": ALLOWED,
    "@blocked": BLOCKED,
    "@group": GROUP,
    "@blocked_user": BLOCKED_USER,
}
DATE = datetime(2026, 1, 1, tzinfo=UTC)


def _input_peer(marked_id: int) -> Any:
    real_id, kind = utils.resolve_id(marked_id)
    if kind is types.PeerChannel:
        return types.InputPeerChannel(channel_id=real_id, access_hash=1)
    return types.InputPeerUser(user_id=real_id, access_hash=1)


def _entity(marked_id: int) -> Any:
    real_id, kind = utils.resolve_id(marked_id)
    if kind is types.PeerChannel:
        # Только у группы обсуждения признак связи True, как у разобранной сущности Telegram.
        return types.Channel(
            id=real_id, title="Чат", photo=types.ChatPhotoEmpty(), date=DATE,
            access_hash=1, has_link=(marked_id == GROUP),
        )  # fmt: skip
    return types.User(id=real_id, first_name="Ivan", access_hash=1)


class AccessClient(FakeTelethonClient):
    """Клиент, у которого @-имена и числа разрешаются в пиров с настоящими ID."""

    def __init__(self) -> None:
        super().__init__()
        self.dialog_list: list[Any] = []

    @staticmethod
    def _marked(peer: Any) -> int:
        return peer if isinstance(peer, int) else ALIASES[peer]

    @staticmethod
    def _known(peer: Any) -> bool:
        return isinstance(peer, int) or peer in ALIASES

    async def __call__(self, request: object) -> Any:
        if isinstance(request, functions.messages.GetCommonChatsRequest):
            self.requests.append(request)
            # Настоящий канал: ID берётся из сущности, как у ответа Telegram.
            return SimpleNamespace(chats=[_entity(-1000000000789)])
        return await super().__call__(request)

    async def get_input_entity(self, peer: Any) -> Any:
        if peer == "me":
            return types.InputPeerSelf()
        if self._known(peer):
            return _input_peer(self._marked(peer))
        return await super().get_input_entity(peer)

    async def get_entity(self, peer: Any) -> Any:
        if peer == "me":
            return types.User(id=OWN_ID, first_name="Я", is_self=True, access_hash=1)
        if self._known(peer):
            return _entity(self._marked(peer))
        return await super().get_entity(peer)

    async def get_peer_id(self, peer: Any, add_mark: bool = True) -> int:
        if isinstance(peer, types.InputPeerSelf):
            return OWN_ID
        return utils.get_peer_id(peer)

    def iter_dialogs(self, limit: int | None = None, **kwargs: Any) -> Any:
        dialogs = list(self.dialog_list)

        async def gen() -> Any:
            for dialog in dialogs:
                yield dialog

        return gen()


def _access(disabled: set[int], links: dict[int, int] | None = None) -> ChatAccess:
    async def discussion_of(chat_id: int) -> int | None:
        return (links or {}).get(chat_id)

    return ChatAccess(frozenset(disabled), discussion_of)


def _toolbox(
    disabled: set[int],
    links: dict[int, int] | None = None,
    **kwargs: Any,
) -> tuple[TelegramToolbox, AccessClient]:
    client = AccessClient()
    toolbox = TelegramToolbox(cast(Any, client), chat_access=_access(disabled, links), **kwargs)
    return toolbox, client


def _dialog(marked_id: int, title: str) -> Any:
    entity = SimpleNamespace(username=None, is_self=False, has_link=False)
    return SimpleNamespace(id=marked_id, title=title, unread_count=0, entity=entity)


def _failure(result: Any) -> dict[str, Any]:
    """Результат инструмента как словарь: у инструментов-списков отказ — первый элемент."""
    return result[0] if isinstance(result, list) and result else result


def _refused(result: Any) -> bool:
    item = _failure(result)
    return item.get("success") is False and item.get("error_code") == "ChatDisabledError"


Call = Callable[[TelegramToolbox], Awaitable[Any]]

REFUSED_CALLS: dict[str, Call] = {
    "send_text_message": lambda tb: tb.send_text_message("@blocked", "привет"),
    "numeric_peer_string": lambda tb: tb.send_text_message(str(BLOCKED), "привет"),
    "private_chat": lambda tb: tb.send_text_message("@blocked_user", "привет"),
    "get_messages": lambda tb: tb.get_messages("@blocked"),
    "search_messages": lambda tb: tb.search_messages("@blocked", "q"),
    "forward_to_blocked": lambda tb: tb.forward_messages("@allowed", "@blocked", [1]),
    "forward_from_blocked": lambda tb: tb.forward_messages("@blocked", "@allowed", [1]),
    "invite_to_channel": lambda tb: tb.invite_to_channel("@blocked", ["username"]),
    "kick_chat_member": lambda tb: tb.kick_chat_member("@blocked", "username"),
    "ban_chat_member": lambda tb: tb.ban_chat_member("@blocked", "username"),
    "archive_dialogs": lambda tb: tb.archive_dialogs(["@allowed", "@blocked"]),
    "start_bot": lambda tb: tb.start_bot("@blocked_user"),
    "query_inline_bot_peer": lambda tb: tb.query_inline_bot("username", "q", peer="@blocked"),
    "join_channel": lambda tb: tb.join_channel("@blocked"),
    "delete_channel": lambda tb: tb.delete_channel("@blocked"),
    "get_discussion_messages": lambda tb: tb.get_discussion_messages("@blocked", 1),
    # send_file сам подменяет тексты ошибок на «Не удалось отправить медиа»: отказ — исключение.
    "send_file": lambda tb: tb.send_file("@blocked", "https://example.com/a.png"),
    "chat_folder": lambda tb: tb.create_or_update_chat_folder(
        2, "Работа", include_peers=["@allowed", "@blocked"]
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(REFUSED_CALLS))
async def test_disabled_chat_is_refused_with_its_own_error(name: str) -> None:
    toolbox, client = _toolbox({BLOCKED, BLOCKED_USER})

    result = await REFUSED_CALLS[name](toolbox)

    assert _refused(result), f"{name}: {result}"
    assert "отключён в настройках агента" in _failure(result)["error"]
    assert [call for call in client.calls if call[0] in ("send_message", "send_file")] == []
    assert not [r for r in client.requests if type(r).__name__ == "UpdateDialogFilterRequest"]


@pytest.mark.asyncio
async def test_archive_changes_nothing_when_one_of_the_chats_is_disabled() -> None:
    toolbox, client = _toolbox({BLOCKED})

    await toolbox.archive_dialogs(["@allowed", "@blocked"])

    assert not [r for r in client.requests if type(r).__name__ == "EditPeerFoldersRequest"]


@pytest.mark.asyncio
async def test_enabled_chat_keeps_working() -> None:
    toolbox, client = _toolbox({BLOCKED})

    result = await toolbox.send_text_message("@allowed", "привет")

    assert result["success"] is True
    assert [call[0] for call in client.calls].count("send_message") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        # as_input=False: разрешение в полную сущность (User с is_self).
        lambda tb: tb.get_messages("me"),
        # as_input=True: InputPeerSelf, который utils.get_peer_id не приводит.
        lambda tb: tb.send_text_message("me", "заметка"),
    ],
    ids=["entity", "input_peer_self"],
)
async def test_saved_messages_are_checked_by_the_own_id(call: Call) -> None:
    toolbox, _ = _toolbox({OWN_ID})

    assert _refused(await call(toolbox))


@pytest.mark.asyncio
async def test_people_are_not_chats_for_profile_and_contacts() -> None:
    toolbox, _ = _toolbox({BLOCKED_USER})

    result = await toolbox.get_profile("username")

    assert result.get("error_code") != "ChatDisabledError"


@pytest.mark.asyncio
async def test_discussion_group_of_an_enabled_channel_is_readable() -> None:
    toolbox, _ = _toolbox({GROUP}, links={GROUP: ALLOWED})

    result = await toolbox.get_messages("@group")

    assert not _refused(result)


@pytest.mark.asyncio
async def test_discussion_group_of_a_disabled_channel_is_refused() -> None:
    toolbox, _ = _toolbox({GROUP, ALLOWED}, links={GROUP: ALLOWED})

    assert _refused(await toolbox.get_messages("@group"))


@pytest.mark.asyncio
async def test_invite_link_join_is_not_checked() -> None:
    toolbox, _ = _toolbox({BLOCKED})

    result = await toolbox.join_channel("https://t.me/+AbCdEf123")

    assert result["success"] is True


@pytest.mark.asyncio
async def test_get_dialogs_hides_disabled_chats_and_still_fills_the_limit() -> None:
    toolbox, client = _toolbox({BLOCKED})
    client.dialog_list = [
        _dialog(BLOCKED, "Закрытый"),
        _dialog(ALLOWED, "Открытый"),
        _dialog(BLOCKED_USER, "Анна"),
    ]

    result = await toolbox.get_dialogs(limit=2)

    assert [d["id"] for d in result] == [ALLOWED, BLOCKED_USER]


@pytest.mark.asyncio
async def test_chat_folders_hide_disabled_peers() -> None:
    # Подделка отдаёт папку: закреплён user 123, включён channel 456.
    toolbox, _ = _toolbox({-1000000000456})

    folders = await toolbox.get_chat_folders()

    custom = next(f for f in folders if f["id"] == 2)
    assert custom["pinned_peers"] == [{"type": "user", "id": 123}]
    assert custom["include_peers"] == []


@pytest.mark.asyncio
async def test_common_chats_hide_disabled_chats() -> None:
    # Подделка отдаёт общий канал с ID 789.
    toolbox, _ = _toolbox({-1000000000789})

    assert await toolbox.get_common_chats("username") == []


@pytest.mark.asyncio
async def test_wakeup_timer_for_a_disabled_chat_is_refused_before_touching_the_database() -> None:
    session_factory = MagicMock()
    toolbox, _ = _toolbox({BLOCKED}, agent_id=MagicMock(), session_factory=session_factory)

    result = await toolbox.set_wakeup_timer("@blocked", 60, "напомнить")

    assert _refused(result)
    session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_toolbox_without_an_access_rule_does_not_resolve_ids() -> None:
    client = AccessClient()
    toolbox = TelegramToolbox(cast(Any, client))

    result = await toolbox.send_text_message("@blocked", "привет")

    assert result["success"] is True


CHAT_PARAMS = {
    "peer", "peers", "from_peer", "to_peer", "channel", "broadcast", "group",
    "pinned_peers", "include_peers", "exclude_peers",
}  # fmt: skip
# Параметр peer здесь — человек, а не чат: результат фильтруется или не проверяется.
PEOPLE_TOOLS = {"get_profile", "delete_contact", "get_common_chats"}


def test_every_chat_addressed_tool_goes_through_the_access_guard() -> None:
    """Новый инструмент с чат-параметром не должен обойти настройку «Чаты и каналы»."""
    unguarded: list[str] = []
    for name, method in inspect.getmembers(TelegramToolbox, inspect.iscoroutinefunction):
        if name.startswith("_") or name in PEOPLE_TOOLS:
            continue
        if not CHAT_PARAMS & set(inspect.signature(method).parameters):
            continue
        source = inspect.getsource(method)
        if "_resolve_chat(" not in source and "_guard_chat(" not in source:
            unguarded.append(name)
    assert unguarded == []
```

- [ ] **Step 8: Сверка с документацией и кодом**

Перечитать `_resolve_peer` и `get_peer_id` Telethon (https://docs.telethon.dev/en/stable/concepts/chats-vs-channels.html): строки `-100…` превращаются в `int` в `_resolve_peer`, `InputPeerSelf` → `client.get_peer_id`. Убедиться по `grep`, что 11 оставшихся `_resolve_peer(` — именно «людские». Проверить, что в фикстуре `FakeTelethonClient` (`tests/integrations/test_telegram_tools.py`) для `GetDialogFiltersRequest` закреплён `InputPeerUser(user_id=123)`, а включён `InputPeerChannel(channel_id=456)` — иначе поправить числа в `test_chat_folders_hide_disabled_peers`. Для «общих чатов» `AccessClient` сам отдаёт настоящий `types.Channel` (ID 789), потому что `MagicMock(spec=types.Channel)` не приводится `utils.get_peer_id`.

- [ ] **Step 9: Commit**

```bash
git add src/mimic42/integrations/telegram_tools.py tests/integrations/test_telegram_tools_chat_access.py
git diff --cached --stat
git commit -m "feat(chats): инструменты Telegram не работают с отключёнными чатами"
```

---

### Task 5: Проверка доступа в рантайме: входящие, первый комментарий, таймеры, список чатов

**Files:**
- Modify: `src/mimic42/core/agent_runtime.py`
- Test: `tests/core/test_chat_access_runtime.py`, `tests/integration/test_agent_timers.py` (маркер `db`)

**Interfaces:**
- Consumes: `ChatAccess`, `ChatDisabledError`, `link_hint` (Task 1); `ChatDirectory`, `ChatItem` (Task 1); поля `_chat_access`/`_chat_directory` (Task 3).
- Produces:
  - `class ChatListUnavailableError(RuntimeError)` в `agent_runtime.py`.
  - `MimicAgentRuntime.list_chats() -> list[ChatItem]` (поднимает `ChatListUnavailableError`, если рантайм не `RUNNING` или нет каталога).
  - Внутренние `_chat_allowed(event) -> bool`, `_ensure_peer_allowed(peer: str) -> None`.

- [ ] **Step 1: Исключение и `list_chats`**

Импорты в `agent_runtime.py` расширить (в Task 3 добавлены `ChatAccess` и `ChatDirectory`):

```python
from mimic42.core.chat_access import ChatAccess, ChatDisabledError, link_hint
from mimic42.core.chat_directory import ChatDirectory, ChatItem
```

Рядом с `TelegramAuthorizationRequired`:

```python
class ChatListUnavailableError(RuntimeError):
    """Список чатов недоступен: агент не запущен, а клиент Telegram не подключён."""
```

Метод класса (рядом с `status`):

```python
    async def list_chats(self) -> list[ChatItem]:
        """Диалоги аккаунта для настроек; только у запущенного агента."""
        if self._state is not AgentRuntimeState.RUNNING or self._chat_directory is None:
            raise ChatListUnavailableError(
                "Агент не запущен: запустите его, чтобы увидеть чаты."
            )
        return await self._chat_directory.list_chats()
```

- [ ] **Step 2: Проверка чата входящего события**

Методы класса (рядом с `_is_chat_muted`):

```python
    async def _chat_allowed(self, event: TelegramEventLike) -> bool:
        """Доступен ли агенту чат события: отключённые в настройках не получают ходов."""
        access = self._chat_access
        chat_id = getattr(event, "chat_id", None)
        if access is None or not isinstance(chat_id, int) or chat_id not in access.disabled:
            return True
        hint: bool | None = None
        get_chat = getattr(event, "get_chat", None)
        if callable(get_chat):
            try:
                hint = link_hint(await get_chat())
            except Exception:
                logger.warning("Не удалось получить чат для проверки доступа", exc_info=True)
        return await access.allows(chat_id, has_link=hint)

    async def _ensure_peer_allowed(self, peer: str) -> None:
        """Проверка чата по строке peer (таймеры): недоступен — ``ChatDisabledError``.

        Не удалось разрешить peer — доступность не подтвердить, и ошибка идёт
        вызывающему: таймер получит ``failed``, а не сработает вслепую.
        """
        access = self._chat_access
        if access is None:
            return
        get_peer_id = getattr(self._telegram_client, "get_peer_id", None)
        if not callable(get_peer_id):
            raise ChatDisabledError()
        chat_id = await get_peer_id(_peer_for_send(peer))
        if not await access.allows(chat_id):
            raise ChatDisabledError(chat_id)
```

- [ ] **Step 3: Входящие и первый комментарий**

В `_dispatch_incoming` сразу после блока `if warmup_verdict is False: ... return`:

```python
        if warmup_verdict is None and not await self._chat_allowed(event):
            logger.info("Чат %s отключён в настройках агента, входящее без ответа", peer)
            return
```

В `_handle_channel_post` сразу после `if not _is_broadcast_post(event): return`:

```python
        if not await self._chat_allowed(event):
            return
```

- [ ] **Step 4: Таймеры**

В `_check_and_trigger_timers` первой строкой внутри `try:` цикла `for timer in due_timers:`:

```python
                    await self._ensure_peer_allowed(timer.peer)
```

(исключение попадает в существующий `except Exception`: таймер получает `failed`, событие `timer.failed` с `error_code: "ChatDisabledError"`.)

- [ ] **Step 5: Тесты `tests/core/test_chat_access_runtime.py`**

```python
"""Отключённые чаты не получают ходов, первых комментариев и таймеров."""

from __future__ import annotations

import pytest

from mimic42.core.agent_runtime import ChatListUnavailableError, MimicAgentRuntime
from mimic42.core.chat_access import ChatAccess, ChatDisabledError
from mimic42.core.chat_directory import ChatItem
from mimic42.core.first_comment import FirstCommentSettings, FirstCommentVariant
from mimic42.testing.telegram import FakeTelegramClient
from tests.core.test_agent_runtime import FakeLangChainAgent, make_config
from tests.core.test_warmup_runtime import StubGate

CHANNEL = -1001111111111
GROUP = -1002222222222


def _access(disabled: set[int], links: dict[int, int] | None = None) -> ChatAccess:
    async def discussion_of(chat_id: int) -> int | None:
        return (links or {}).get(chat_id)

    return ChatAccess(frozenset(disabled), discussion_of)


def _runtime(
    access: ChatAccess | None, directory: object | None = None
) -> tuple[MimicAgentRuntime, FakeTelegramClient, FakeLangChainAgent]:
    telegram = FakeTelegramClient()
    agent = FakeLangChainAgent(response="ответ")
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram,
        langchain_agent=agent,
        chat_access=access,
        chat_directory=directory,  # ty: ignore[invalid-argument-type]
    )
    return runtime, telegram, agent


@pytest.mark.asyncio
async def test_incoming_from_a_disabled_chat_starts_no_turn() -> None:
    runtime, telegram, agent = _runtime(_access({99}))
    await runtime.start()

    await telegram.account.deliver(chat_id=99, text="привет")

    assert agent.inputs == []
    assert telegram.sent_messages == []


@pytest.mark.asyncio
async def test_other_chats_are_answered_as_before() -> None:
    runtime, telegram, agent = _runtime(_access({99}))
    await runtime.start()

    await telegram.account.deliver(chat_id=100, text="привет")

    assert len(agent.inputs) == 1
    assert telegram.sent_messages == [("100", "ответ")]


@pytest.mark.asyncio
async def test_comments_of_an_enabled_channel_are_answered_even_if_the_group_is_disabled() -> None:
    runtime, telegram, agent = _runtime(_access({GROUP}, {GROUP: CHANNEL}))
    await runtime.start()

    await telegram.account.deliver(chat_id=GROUP, text="комментарий")

    assert len(agent.inputs) == 1


@pytest.mark.asyncio
async def test_comments_of_a_disabled_channel_stay_silent() -> None:
    runtime, telegram, agent = _runtime(_access({GROUP, CHANNEL}, {GROUP: CHANNEL}))
    await runtime.start()

    await telegram.account.deliver(chat_id=GROUP, text="комментарий")

    assert agent.inputs == []


@pytest.mark.asyncio
async def test_dialog_with_another_mimic_ignores_the_disabled_list() -> None:
    runtime, telegram, agent = _runtime(_access({555}))
    runtime.set_warmup_gate(StubGate(True))
    await runtime.start()

    await telegram.account.deliver(chat_id=555, text="привет", sender_id=555)

    assert len(agent.inputs) == 1


@pytest.mark.asyncio
async def test_ordinary_person_in_a_disabled_chat_is_still_ignored_with_a_warmup_gate() -> None:
    runtime, telegram, agent = _runtime(_access({555}))
    runtime.set_warmup_gate(StubGate(None))
    await runtime.start()

    await telegram.account.deliver(chat_id=555, text="привет", sender_id=555)

    assert agent.inputs == []


def _comment_runtime(access: ChatAccess) -> tuple[MimicAgentRuntime, FakeTelegramClient]:
    runtime, telegram, _ = _runtime(access)
    runtime.config.first_comment = FirstCommentSettings(
        enabled=True, variants=[FirstCommentVariant(text="Первый!")]
    )
    return runtime, telegram


@pytest.mark.asyncio
async def test_disabled_channel_gets_no_first_comment() -> None:
    runtime, telegram = _comment_runtime(_access({-100500}))
    await runtime.start()

    await telegram.account.deliver_post(chat_id=-100500, text="Новый пост")

    assert [m for m in telegram.account.sent if "comment_to" in m.kwargs] == []


@pytest.mark.asyncio
async def test_other_channels_still_get_the_first_comment() -> None:
    runtime, telegram = _comment_runtime(_access({-100600}))
    await runtime.start()

    await telegram.account.deliver_post(chat_id=-100500, text="Новый пост")

    assert len([m for m in telegram.account.sent if "comment_to" in m.kwargs]) == 1


@pytest.mark.asyncio
async def test_peer_check_resolves_the_peer_through_the_client() -> None:
    runtime, telegram, _ = _runtime(_access({CHANNEL}))

    async def get_peer_id(peer: object, add_mark: bool = True) -> int:
        return {"@news": CHANNEL}.get(str(peer), peer)  # type: ignore[return-value]

    telegram.get_peer_id = get_peer_id  # type: ignore[attr-defined]

    with pytest.raises(ChatDisabledError):
        await runtime._ensure_peer_allowed("@news")
    with pytest.raises(ChatDisabledError):
        await runtime._ensure_peer_allowed(str(CHANNEL))
    await runtime._ensure_peer_allowed("-1009999999999")


@pytest.mark.asyncio
async def test_peer_check_without_a_rule_resolves_nothing() -> None:
    runtime, _, _ = _runtime(None)

    await runtime._ensure_peer_allowed("@anything")


class _StubDirectory:
    async def list_chats(self) -> list[ChatItem]:
        return [ChatItem(id=7, title="Анна", kind="private")]

    async def discussion_of(self, chat_id: int) -> int | None:
        return None


@pytest.mark.asyncio
async def test_list_chats_needs_a_running_agent() -> None:
    runtime, _, _ = _runtime(None, _StubDirectory())

    with pytest.raises(ChatListUnavailableError):
        await runtime.list_chats()

    await runtime.start()
    assert [chat.id for chat in await runtime.list_chats()] == [7]

    await runtime.stop()
    with pytest.raises(ChatListUnavailableError):
        await runtime.list_chats()


@pytest.mark.asyncio
async def test_list_chats_without_a_directory_is_unavailable() -> None:
    runtime, _, _ = _runtime(None, None)
    await runtime.start()

    with pytest.raises(ChatListUnavailableError):
        await runtime.list_chats()
```

- [ ] **Step 6: DB-тест таймера в `tests/integration/test_agent_timers.py`**

Импорты: добавить `from mimic42.core.chat_access import ChatAccess`. Тест в конец файла:

```python
async def test_timer_for_a_disabled_chat_fails_without_a_turn(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("empty").user_id
    agent_id = uuid4()
    async with db_session_factory() as session:
        session.add(AgentModel(id=agent_id, owner_id=owner_id, name="Test Agent"))
        await session.commit()
    async with db_session_factory() as session:
        session.add(
            AgentTimerModel(
                agent_id=agent_id,
                peer="12345",
                trigger_at=datetime.now(UTC) - timedelta(seconds=1),
                description="Напомнить",
                status="pending",
            )
        )
        await session.commit()

    async def never_linked(chat_id: int) -> int | None:
        return None

    telegram = FakeTelegramClient()

    async def get_peer_id(peer: object, add_mark: bool = True) -> int:
        return int(str(peer))

    telegram.get_peer_id = get_peer_id  # type: ignore[attr-defined]
    runtime = MimicAgentRuntime(
        config=make_config(agent_id=agent_id, owner_id=owner_id),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(response="не должен ответить"),
        session_factory=db_session_factory,
        chat_access=ChatAccess(frozenset({12345}), never_linked),
    )

    await runtime._check_and_trigger_timers()

    async with db_session_factory() as session:
        timers = list(
            await session.scalars(select(AgentTimerModel).where(AgentTimerModel.agent_id == agent_id))
        )
    assert [timer.status for timer in timers] == ["failed"]
    assert telegram.sent_messages == []
```

и импорт `from datetime import UTC, datetime, timedelta` в шапке файла.

- [ ] **Step 7: Перечитать диф против спеки**

Раздел «Входящие»: проверка после вердикта прогрева и только при `warmup_verdict is None`; раздел «Таймеры»: `failed`, без миграции статусов. `_handle_channel_post` — проверка до `grouped_id`-guard (чтобы альбом отключённого канала не занимал слот guard).

Проверить фактический порядок в коде: проверка `_chat_allowed` стоит **после** `_is_broadcast_post` и **до** `message_id`/`grouped_id`; если нет — переставить.

- [ ] **Step 8: Commit**

```bash
git add src/mimic42/core/agent_runtime.py tests/core/test_chat_access_runtime.py tests/integration/test_agent_timers.py
git diff --cached --stat
git commit -m "feat(chats): рантайм не отвечает из отключённых чатов и не комментирует их посты"
```

---

### Task 6: Эндпоинт списка чатов

**Files:**
- Modify: `src/mimic42/core/manager.py` (метод `list_chats`)
- Modify: `src/mimic42/api/app.py` (протокол, эндпоинт, хелпер)
- Test: `tests/api/test_chats_api.py`, `tests/core/test_chat_access_wiring.py` (дописать)

**Interfaces:**
- Consumes: `ChatItem` (Task 1); `MimicAgentRuntime.list_chats`, `ChatListUnavailableError` (Task 5).
- Produces:
  - `AgentManager.list_chats(agent_id: UUID) -> list[ChatItem]`.
  - `GET /api/v1/agents/{agent_id}/chats` → `200 list[ChatItem]`; `404` — нет агента; `403` — чужой; `409` — агент не запущен (detail из `ChatListUnavailableError`); `501` — менеджер без поддержки; `502` — Telegram не отдал список.
  - `@runtime_checkable ChatDirectoryControl` Protocol (`async list_chats(agent_id) -> list[ChatItem]`).

- [ ] **Step 1: Метод менеджера**

В `AgentManager` рядом с `get_warmup_state`:

```python
    async def list_chats(self, agent_id: UUID) -> list[ChatItem]:
        """Диалоги аккаунта агента; у остановленного рантайма — ChatListUnavailableError."""
        return await (await self.get_agent(agent_id)).list_chats()
```

Импорт: `from mimic42.core.chat_directory import ChatItem`.

- [ ] **Step 2: Эндпоинт**

В `src/mimic42/api/app.py` импорты: `ChatListUnavailableError` в блок `from mimic42.core.agent_runtime import (...)`, `from mimic42.core.chat_directory import ChatItem`.

Протокол рядом с `WarmupControl`:

```python
@runtime_checkable
class ChatDirectoryControl(Protocol):
    """Список диалогов агента: есть не у всякого менеджера (подделки в тестах его не имеют)."""

    async def list_chats(self, agent_id: UUID) -> list[ChatItem]: ...
```

Эндпоинт после `start_warmup_recovery`:

```python
    @app.get("/api/v1/agents/{agent_id}/chats", response_model=list[ChatItem])
    async def list_agent_chats(
        agent_id: UUID,
        current_user: CurrentUserDep,
    ) -> list[ChatItem]:
        """Диалоги аккаунта для настройки «Чаты и каналы»; нужен запущенный агент."""
        directory = _get_chat_directory_control(app)
        try:
            await _ensure_runtime_owner(app, agent_id=agent_id, user_id=current_user.user_id)
            return await directory.list_chats(agent_id)
        except AgentNotFoundError as exc:
            raise _not_found(exc.agent_id) from exc
        except ChatListUnavailableError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Failed to list chats of agent %s", agent_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Не удалось получить список чатов из Telegram.",
            ) from exc
```

Хелпер рядом с `_get_warmup_control`:

```python
def _get_chat_directory_control(app: FastAPI) -> ChatDirectoryControl:
    manager = _get_agent_manager(app)
    if not isinstance(manager, ChatDirectoryControl):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Список чатов недоступен.",
        )
    return manager
```

- [ ] **Step 3: Тесты API `tests/api/test_chats_api.py`**

```python
"""GET /agents/{id}/chats: диалоги аккаунта для настройки доступных чатов."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import AgentRuntimeConfig, ChatListUnavailableError
from mimic42.core.chat_directory import ChatItem
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier
from tests.api.fakes import FakeAgentManager

CHATS = [
    ChatItem(id=-1001000000001, title="Новости", username="news", kind="channel"),
    ChatItem(
        id=-1001000000002,
        title="Комментарии",
        kind="group",
        discussion_of=-1001000000001,
    ),
    ChatItem(id=42, title="Анна", kind="private"),
]


class ChatsAgentManager(FakeAgentManager):
    def __init__(self) -> None:
        super().__init__()
        self.chats: list[ChatItem] = []
        self.unavailable = False
        self.broken = False

    async def list_chats(self, agent_id: UUID) -> list[ChatItem]:
        if self.unavailable:
            raise ChatListUnavailableError("Агент не запущен: запустите его, чтобы увидеть чаты.")
        if self.broken:
            raise RuntimeError("telegram is down")
        return self.chats


async def _agent(manager: FakeAgentManager, owner_id: UUID) -> UUID:
    agent_id = uuid4()
    await manager.create_agent(
        AgentRuntimeConfig(
            agent_id=agent_id,
            owner_id=owner_id,
            telegram_api_id=1,
            telegram_api_hash="hash",
            telegram_session_string="session",
            system_prompt="system",
        )
    )
    return agent_id


def _client(manager: FakeAgentManager, user_id: UUID) -> AsyncClient:
    app = create_app(manager=manager, auth_verifier=FakeAuthVerifier(user_id))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.mark.asyncio
async def test_owner_gets_the_dialogs() -> None:
    owner_id = uuid4()
    manager = ChatsAgentManager()
    agent_id = await _agent(manager, owner_id)
    manager.chats = CHATS

    async with _client(manager, owner_id) as client:
        response = await client.get(f"/api/v1/agents/{agent_id}/chats", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": -1001000000001,
            "title": "Новости",
            "username": "news",
            "kind": "channel",
            "discussion_of": None,
        },
        {
            "id": -1001000000002,
            "title": "Комментарии",
            "username": None,
            "kind": "group",
            "discussion_of": -1001000000001,
        },
        {"id": 42, "title": "Анна", "username": None, "kind": "private", "discussion_of": None},
    ]


@pytest.mark.asyncio
async def test_stopped_agent_is_a_conflict_with_a_readable_reason() -> None:
    owner_id = uuid4()
    manager = ChatsAgentManager()
    agent_id = await _agent(manager, owner_id)
    manager.unavailable = True

    async with _client(manager, owner_id) as client:
        response = await client.get(f"/api/v1/agents/{agent_id}/chats", headers=AUTH_HEADERS)

    assert response.status_code == 409
    assert "запустите его" in response.json()["detail"]


@pytest.mark.asyncio
async def test_other_users_cannot_read_the_dialogs() -> None:
    manager = ChatsAgentManager()
    agent_id = await _agent(manager, uuid4())
    manager.chats = CHATS

    async with _client(manager, uuid4()) as client:
        response = await client.get(f"/api/v1/agents/{agent_id}/chats", headers=AUTH_HEADERS)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_telegram_failure_is_a_bad_gateway_without_leaking_details() -> None:
    owner_id = uuid4()
    manager = ChatsAgentManager()
    agent_id = await _agent(manager, owner_id)
    manager.broken = True

    async with _client(manager, owner_id) as client:
        response = await client.get(f"/api/v1/agents/{agent_id}/chats", headers=AUTH_HEADERS)

    assert response.status_code == 502
    assert "telegram is down" not in response.text


@pytest.mark.asyncio
async def test_manager_without_chat_support_answers_not_implemented() -> None:
    owner_id = uuid4()
    manager = FakeAgentManager()
    agent_id = await _agent(manager, owner_id)

    async with _client(manager, owner_id) as client:
        response = await client.get(f"/api/v1/agents/{agent_id}/chats", headers=AUTH_HEADERS)

    assert response.status_code == 501
```

- [ ] **Step 4: Тест менеджера** — дописать в `tests/core/test_chat_access_wiring.py`:

```python
@pytest.mark.asyncio
async def test_manager_lists_chats_through_the_runtime() -> None:
    from mimic42.core.agent_runtime import ChatListUnavailableError

    manager = _memory_manager()
    config = _config()
    await manager.create_agent(config)

    with pytest.raises(ChatListUnavailableError):
        await manager.list_chats(config.agent_id)
```

- [ ] **Step 5: Commit**

```bash
git add src/mimic42/core/manager.py src/mimic42/api/app.py tests/api/test_chats_api.py tests/core/test_chat_access_wiring.py
git diff --cached --stat
git commit -m "feat(chats): GET /agents/{id}/chats отдаёт диалоги аккаунта"
```

---

### Task 7: Фронтенд: типы, логика, API, хук

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/lib/validators.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/activity/errorCatalog.ts`
- Modify: `frontend/src/hooks/useAgent.ts`
- Create: `frontend/src/lib/chats/agentChats.ts`
- Test: `frontend/src/__tests__/agent-chats.test.ts`

**Interfaces:**
- Consumes: эндпоинт `GET /agents/:id/chats` (Task 6).
- Produces:
  - `AgentChatKind`, `AgentChat` (`types/index.ts`).
  - `agentsApi.listChats(id): Promise<AgentChat[]>`.
  - `useAgentChats(agentId: string)` — `useQuery` (`retry: false`, `staleTime: 60_000`, `refetchOnWindowFocus: false`).
  - `readDisabledChats(settings): number[]`; `mergeDisabledChats(existing, disabled: number[] | undefined): Record<string, unknown>` (пустой список удаляет ключ); `CHAT_GROUPS: { id: AgentChatKind; title: string }[]`; `buildChatRows(chats, disabled: ReadonlySet<number>): ChatRow[]`; `ChatRow = { chat: AgentChat; enabled: boolean; lockedBy: { id: number; title: string } | null }`; `toggleChats(disabled: number[], ids: number[], enable: boolean): number[]`.
  - `agentSettingsSchema.disabled_chats`.

- [ ] **Step 1: Типы** — в `frontend/src/types/index.ts` после `WarmupState`:

```ts
/** Вид диалога в настройке «Чаты и каналы» — зеркало ChatKind из core/chat_directory.py. */
export type AgentChatKind = 'channel' | 'group' | 'private';

/** Диалог аккаунта: GET /agents/:id/chats. */
export interface AgentChat {
  /** ID в формате Telethon (marked): `-100…` у каналов и супергрупп. */
  id: number;
  title: string;
  username: string | null;
  kind: AgentChatKind;
  /** ID канала, если это группа обсуждения (комментарии) его постов. */
  discussion_of: number | null;
}
```

- [ ] **Step 2: Валидатор** — в `agentSettingsSchema` после `enabled_tools`:

```ts
  // Необязательное: у агентов без настройки ключа нет — доступны все чаты.
  disabled_chats: z
    .array(z.number().int('ID чата должен быть целым числом'))
    .max(20_000, 'Слишком много отключённых чатов')
    .optional(),
```

- [ ] **Step 3: API** — в `frontend/src/lib/api.ts` добавить `AgentChat` в импорт типов и метод в `agentsApi` после `startWarmupRecovery`:

```ts
  /** GET /api/v1/agents/:id/chats — диалоги аккаунта (409, пока агент не запущен) */
  listChats: (id: string) =>
    apiClient.get<AgentChat[]>(`/agents/${id}/chats`).then((r) => r.data),
```

- [ ] **Step 4: Каталог ошибок** — в `errorCatalog.ts` после `PeerIdInvalidError`:

```ts
  ChatDisabledError: 'Чат отключён в настройках агента',
```

- [ ] **Step 5: Хук** — в `frontend/src/hooks/useAgent.ts` добавить в конец:

```ts
/**
 * Диалоги аккаунта для настройки «Чаты и каналы». Читаются из клиента запущенного
 * агента: 409 — штатное «агент не запущен», поэтому без повторов и без перезапроса
 * на каждый возврат в окно (список кешируется на бэкенде на минуту).
 */
export function useAgentChats(agentId: string) {
  const isValidId = agentIdSchema.safeParse(agentId).success;

  return useQuery({
    queryKey: [...queryKeys.agents.detail(agentId), 'chats'],
    queryFn: () => agentsApi.listChats(agentId),
    enabled: isValidId,
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}
```

- [ ] **Step 6: Логика `frontend/src/lib/chats/agentChats.ts`**

```ts
/**
 * Настройка отключённых чатов в `agents.settings` — зеркало
 * `src/mimic42/core/chat_access.py`.
 */
import type { AgentChat, AgentChatKind } from '@/types';

export const CHAT_GROUPS: { id: AgentChatKind; title: string }[] = [
  { id: 'channel', title: 'Каналы' },
  { id: 'group', title: 'Группы' },
  { id: 'private', title: 'Личные' },
];

/**
 * Прочитать ID отключённых чатов из settings.
 *
 * Ключа нет или значение нечитаемо — пустой список (доступны все чаты). Остаются
 * только целые числа: `true` и строки из ручной правки JSON отбрасываются, как на бэкенде.
 */
export function readDisabledChats(
  settings: Record<string, unknown> | null | undefined,
): number[] {
  const value = settings?.disabled_chats;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is number => typeof item === 'number' && Number.isInteger(item));
}

/**
 * Вернуть настройки с обновлённым `disabled_chats`.
 *
 * Пустой список и `undefined` удаляют ключ: «ничего не отключено» — отсутствие
 * настройки, как у существующих агентов. Исходный объект не мутируется.
 */
export function mergeDisabledChats(
  existing: Record<string, unknown>,
  disabled: number[] | undefined,
): Record<string, unknown> {
  const merged = { ...existing };
  if (disabled && disabled.length > 0) {
    merged.disabled_chats = Array.from(new Set(disabled));
  } else {
    delete merged.disabled_chats;
  }
  return merged;
}

export interface ChatRow {
  chat: AgentChat;
  /** Доступен ли чат агенту: включён сам или включён его канал (комментарии). */
  enabled: boolean;
  /** Канал, из-за которого группа обсуждения доступна и переключатель заблокирован. */
  lockedBy: { id: number; title: string } | null;
}

/** Строки списка с учётом правила комментариев: группа обсуждения идёт за своим каналом. */
export function buildChatRows(chats: AgentChat[], disabled: ReadonlySet<number>): ChatRow[] {
  const byId = new Map(chats.map((chat) => [chat.id, chat]));
  return chats.map((chat) => {
    const channelId = chat.discussion_of;
    const channelEnabled = channelId !== null && !disabled.has(channelId);
    const lockedBy =
      channelId !== null && channelEnabled
        ? { id: channelId, title: byId.get(channelId)?.title ?? `Канал ${channelId}` }
        : null;
    return { chat, enabled: !disabled.has(chat.id) || lockedBy !== null, lockedBy };
  });
}

/** Включить (`enable`) или отключить чаты; остальные ID — в том числе неизвестные — сохраняются. */
export function toggleChats(disabled: number[], ids: number[], enable: boolean): number[] {
  const next = new Set(disabled);
  for (const id of ids) {
    if (enable) next.delete(id);
    else next.add(id);
  }
  return Array.from(next);
}
```

- [ ] **Step 7: Тесты `frontend/src/__tests__/agent-chats.test.ts`**

```ts
import { describe, expect, test } from 'bun:test';
import {
  buildChatRows,
  mergeDisabledChats,
  readDisabledChats,
  toggleChats,
} from '@/lib/chats/agentChats';
import { agentSettingsSchema } from '@/lib/validators';
import type { AgentChat } from '@/types';

const NEWS: AgentChat = {
  id: -1001000000001,
  title: 'Новости',
  username: 'news',
  kind: 'channel',
  discussion_of: null,
};
const COMMENTS: AgentChat = {
  id: -1001000000002,
  title: 'Комментарии',
  username: null,
  kind: 'group',
  discussion_of: NEWS.id,
};
const ANNA: AgentChat = { id: 42, title: 'Анна', username: null, kind: 'private', discussion_of: null };

describe('readDisabledChats', () => {
  test('без настроек и без ключа ничего не отключено', () => {
    expect(readDisabledChats(null)).toEqual([]);
    expect(readDisabledChats({})).toEqual([]);
    expect(readDisabledChats({ disabled_chats: null })).toEqual([]);
  });

  test('список ID возвращается как есть', () => {
    expect(readDisabledChats({ disabled_chats: [NEWS.id, 42] })).toEqual([NEWS.id, 42]);
  });

  test('мусор отбрасывается, как на бэкенде', () => {
    expect(readDisabledChats({ disabled_chats: [NEWS.id, true, '42', 1.5, null] })).toEqual([
      NEWS.id,
    ]);
    expect(readDisabledChats({ disabled_chats: { id: 1 } })).toEqual([]);
  });
});

describe('mergeDisabledChats', () => {
  test('список записывается без дублей, другие ключи сохраняются', () => {
    expect(mergeDisabledChats({ model: 'm' }, [1, 2, 1])).toEqual({
      model: 'm',
      disabled_chats: [1, 2],
    });
  });

  test('пустой список и undefined удаляют ключ', () => {
    const existing = { model: 'm', disabled_chats: [1], alien: 1 };
    expect(mergeDisabledChats(existing, [])).toEqual({ model: 'm', alien: 1 });
    expect(mergeDisabledChats(existing, undefined)).toEqual({ model: 'm', alien: 1 });
  });

  test('исходный объект не мутируется', () => {
    const existing = { disabled_chats: [1] };
    mergeDisabledChats(existing, [2]);
    mergeDisabledChats(existing, []);
    expect(existing).toEqual({ disabled_chats: [1] });
  });
});

describe('buildChatRows', () => {
  test('по умолчанию все чаты включены', () => {
    const rows = buildChatRows([NEWS, ANNA], new Set());
    expect(rows.map((row) => row.enabled)).toEqual([true, true]);
    expect(rows.every((row) => row.lockedBy === null)).toBe(true);
  });

  test('отключённый чат выключен', () => {
    const rows = buildChatRows([NEWS, ANNA], new Set([ANNA.id]));
    expect(rows.map((row) => row.enabled)).toEqual([true, false]);
  });

  test('группа обсуждения включённого канала включена и заблокирована им', () => {
    const rows = buildChatRows([NEWS, COMMENTS], new Set([COMMENTS.id]));
    const comments = rows[1];
    expect(comments.enabled).toBe(true);
    expect(comments.lockedBy).toEqual({ id: NEWS.id, title: 'Новости' });
  });

  test('при отключённом канале группа живёт своим состоянием', () => {
    const rows = buildChatRows([NEWS, COMMENTS], new Set([NEWS.id, COMMENTS.id]));
    expect(rows[1].enabled).toBe(false);
    expect(rows[1].lockedBy).toBeNull();
    const rowsEnabledOwn = buildChatRows([NEWS, COMMENTS], new Set([NEWS.id]));
    expect(rowsEnabledOwn[1].enabled).toBe(true);
    expect(rowsEnabledOwn[1].lockedBy).toBeNull();
  });

  test('канал вне списка диалогов тоже блокирует группу', () => {
    const rows = buildChatRows([COMMENTS], new Set());
    expect(rows[0].lockedBy).toEqual({ id: NEWS.id, title: `Канал ${NEWS.id}` });
  });
});

describe('toggleChats', () => {
  test('отключение добавляет ID, включение убирает', () => {
    expect(toggleChats([], [NEWS.id], false)).toEqual([NEWS.id]);
    expect(toggleChats([NEWS.id, 42], [NEWS.id], true)).toEqual([42]);
  });

  test('неизвестные списку диалогов ID не теряются', () => {
    expect(toggleChats([999, 42], [NEWS.id], false)).toEqual([999, 42, NEWS.id]);
    expect(toggleChats([999, 42], [42], true)).toEqual([999]);
  });

  test('исходный массив не мутируется', () => {
    const base = [1];
    toggleChats(base, [2], false);
    expect(base).toEqual([1]);
  });
});

describe('agentSettingsSchema.disabled_chats', () => {
  const base = { name: 'Мимик', soul_prompt: '', model: 'openrouter/free' };

  test('принимает список целых, пустой список и отсутствие ключа', () => {
    expect(agentSettingsSchema.safeParse({ ...base, disabled_chats: [NEWS.id, 42] }).success).toBe(true);
    expect(agentSettingsSchema.safeParse({ ...base, disabled_chats: [] }).success).toBe(true);
    expect(agentSettingsSchema.safeParse(base).success).toBe(true);
  });

  test('отклоняет нецелые и нечисловые ID', () => {
    expect(agentSettingsSchema.safeParse({ ...base, disabled_chats: [1.5] }).success).toBe(false);
    expect(agentSettingsSchema.safeParse({ ...base, disabled_chats: ['1'] }).success).toBe(false);
  });
});
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/lib/validators.ts frontend/src/lib/api.ts frontend/src/lib/activity/errorCatalog.ts frontend/src/hooks/useAgent.ts frontend/src/lib/chats/agentChats.ts frontend/src/__tests__/agent-chats.test.ts
git diff --cached --stat
git commit -m "feat(chats): типы, логика и хук настройки чатов на фронтенде"
```

---

### Task 8: Фронтенд: секция «Чаты и каналы»

**Files:**
- Create: `frontend/src/components/agent/ChatsSettings.tsx`
- Modify: `frontend/src/components/agent/TabSettings.tsx`
- Test: `frontend/src/__tests__/chats-settings.test.tsx`

**Interfaces:**
- Consumes: `useAgentChats`, `buildChatRows`, `toggleChats`, `CHAT_GROUPS`, `readDisabledChats`, `mergeDisabledChats` (Task 7); `Switch`, `Button`, `Input`, `Skeleton` из `components/ui`.
- Produces: `ChatsSettings({ agentId, value, onChange })` — `value: number[]` (ID отключённых), `onChange(next: number[])`. Контракт интерфейса (тесты и e2e опираются на него):
  - корень `data-testid="chats-settings"`; поле поиска с меткой «Поиск чатов»; кнопка «Включить все»; кнопка-иконка «Обновить список».
  - счётчик «Доступно N из M» (N — чаты с `enabled`, M — все диалоги списка);
  - группы: кнопка `data-testid="chat-group-{channel|group|private}"` (раскрытие) и переключатель группы с меткой «Все чаты группы «{название}»»; по умолчанию свёрнуты, при непустом поиске раскрыты; в группе первые 100 строк и кнопка «Показать ещё»;
  - строка чата: переключатель с `aria-label` = название чата; заблокированная группа обсуждения — `aria-checked="true"`, `disabled`, подсказка «Комментарии канала «X»: доступна, пока канал включён»;
  - блок «Нет в списке диалогов» с отключёнными ID вне списка (переключатель `Чат {id}`);
  - 409 → пояснение «Запустите агента, чтобы увидеть чаты» (`data-testid="chats-not-running"`) и блок отключённых ID; прочие ошибки → сообщение и кнопка «Повторить».

**Перед UI-кодом (обязательно по правилам проекта):**

- [ ] **Step 1: Скилл Impeccable**

Выполнить Setup из `.claude/skills/impeccable/SKILL.md`: `.agents/skills/impeccable/scripts/impeccable context` (один раз за сессию), режим — **Operate** (настройки), задача — доработка существующей формы, а не новый визуальный мир: сохраняем идентичность `ToolsSettings`. Прочитать `reference/craft-floor.md` непосредственно перед правкой UI. Проверку делать одним пакетом (десктоп + мобильная ширина), без бесконечных итераций.

- [ ] **Step 2: Изучить образец** — `frontend/src/components/agent/ToolsSettings.tsx` (структура секции, группы со сворачиванием, `Switch`, счётчики) и `FirstCommentSettings.tsx` (пустые состояния). Секция «Чаты и каналы» повторяет их разметку и токены; иконки — `lucide-react`: `Radio` (каналы), `Users` (группы), `User` (личные), `Search`, `RefreshCw`, `MessagesSquare` (комментарии), `ChevronDown/ChevronRight`.

- [ ] **Step 3: Компонент `ChatsSettings.tsx`**

```tsx
'use client';

import { useMemo, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  MessagesSquare,
  Radio,
  RefreshCw,
  User,
  Users,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { useAgentChats } from '@/hooks/useAgent';
import { buildChatRows, CHAT_GROUPS, toggleChats, type ChatRow } from '@/lib/chats/agentChats';
import type { AgentChatKind, ApiError } from '@/types';

const PAGE_SIZE = 100;

const GROUP_ICONS: Record<AgentChatKind, typeof Radio> = {
  channel: Radio,
  group: Users,
  private: User,
};

/**
 * Переключатели чатов и каналов агента.
 *
 * `value` — ID отключённых чатов; пусто — доступны все, включая будущие. ID, которых
 * нет в живом списке (вышел из чата, агент остановлен), сохраняются как есть.
 */
export function ChatsSettings({
  agentId,
  value,
  onChange,
}: {
  agentId: string;
  value: number[];
  onChange: (next: number[]) => void;
}) {
  const { data: chats, error, isLoading, isFetching, refetch } = useAgentChats(agentId);
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState<AgentChatKind[]>([]);
  const [shown, setShown] = useState<Record<string, number>>({});

  const disabled = useMemo(() => new Set(value), [value]);
  const rows = useMemo(() => buildChatRows(chats ?? [], disabled), [chats, disabled]);
  const knownIds = useMemo(() => new Set((chats ?? []).map((chat) => chat.id)), [chats]);
  const orphans = value.filter((id) => !knownIds.has(id));

  const normalizedQuery = query.trim().toLowerCase();
  const matches = (row: ChatRow) =>
    normalizedQuery.length === 0 ||
    row.chat.title.toLowerCase().includes(normalizedQuery) ||
    (row.chat.username ?? '').toLowerCase().includes(normalizedQuery);

  // Ошибки запроса нормализованы перехватчиком axios в ApiError.
  const apiError = error as unknown as ApiError | null;
  const notRunning = apiError?.status === 409;
  const enabledCount = rows.filter((row) => row.enabled).length;

  const setChat = (id: number, next: boolean) => onChange(toggleChats(value, [id], next));
  const setGroup = (kind: AgentChatKind, next: boolean) => {
    const ids = rows
      .filter((row) => row.chat.kind === kind && row.lockedBy === null)
      .map((row) => row.chat.id);
    onChange(toggleChats(value, ids, next));
  };

  return (
    <section className="space-y-3" data-testid="chats-settings">
      <div className="space-y-1">
        <h3 className="font-display text-sm text-foreground">Чаты и каналы</h3>
        <p className="font-mono text-xs text-muted-foreground max-w-prose">
          С какими чатами Мимик работает. Отключённый чат не получает ответов и недоступен
          инструментам. Новые чаты и каналы включаются автоматически. Если канал включён,
          его комментарии тоже доступны.
        </p>
      </div>

      {isLoading && <Skeleton style={{ height: 96 }} />}

      {notRunning && (
        <p
          data-testid="chats-not-running"
          className="font-mono text-xs text-muted-foreground max-w-prose"
        >
          Запустите агента, чтобы увидеть чаты. Уже отключённые чаты остаются в силе.
        </p>
      )}

      {apiError && !notRunning && (
        <div className="flex flex-wrap items-center gap-3">
          <p role="alert" className="font-mono text-xs text-crimson-400">
            {apiError.message ?? 'Не удалось получить список чатов.'}
          </p>
          <Button type="button" variant="ghost" size="sm" onClick={() => void refetch()}>
            Повторить
          </Button>
        </div>
      )}

      {chats && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-mono text-xs text-muted-foreground">
              Доступно {enabledCount} из {rows.length}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onChange([])}
              disabled={value.length === 0}
            >
              Включить все
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Обновить список"
              title="Обновить список"
              onClick={() => void refetch()}
              disabled={isFetching}
            >
              <RefreshCw
                className={isFetching ? 'h-3.5 w-3.5 animate-spin' : 'h-3.5 w-3.5'}
                aria-hidden="true"
              />
            </Button>
          </div>

          <Input
            label="Поиск чатов"
            placeholder="Название или @username"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />

          <div className="space-y-2">
            {CHAT_GROUPS.map((group) => {
              const groupRows = rows.filter((row) => row.chat.kind === group.id);
              const visibleRows = groupRows.filter(matches);
              if (visibleRows.length === 0) return null;

              const isOpen = normalizedQuery.length > 0 || expanded.includes(group.id);
              const limit = shown[group.id] ?? PAGE_SIZE;
              const onCount = groupRows.filter((row) => row.enabled).length;
              const Icon = GROUP_ICONS[group.id];

              return (
                <div key={group.id} className="rounded-sm border border-border">
                  <div className="flex items-center justify-between gap-3 px-3 py-2">
                    <button
                      type="button"
                      aria-expanded={isOpen}
                      data-testid={`chat-group-${group.id}`}
                      onClick={() =>
                        setExpanded((prev) =>
                          prev.includes(group.id)
                            ? prev.filter((id) => id !== group.id)
                            : [...prev, group.id],
                        )
                      }
                      className="flex min-w-0 flex-1 items-center gap-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                    >
                      {isOpen ? (
                        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                      )}
                      <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                      <span className="font-mono text-xs text-foreground">{group.title}</span>
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {onCount} из {groupRows.length}
                      </span>
                    </button>
                    <Switch
                      checked={onCount === groupRows.length}
                      onChange={(next) => setGroup(group.id, next)}
                      label={`Все чаты группы «${group.title}»`}
                    />
                  </div>

                  {isOpen && (
                    <ul className="divide-y divide-border border-t border-border">
                      {visibleRows.slice(0, limit).map((row) => (
                        <ChatItemRow key={row.chat.id} row={row} onToggle={setChat} />
                      ))}
                      {visibleRows.length > limit && (
                        <li className="px-3 py-2">
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() =>
                              setShown((prev) => ({ ...prev, [group.id]: limit + PAGE_SIZE }))
                            }
                          >
                            Показать ещё
                          </Button>
                        </li>
                      )}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {orphans.length > 0 && (
        <div className="rounded-sm border border-border">
          <p className="px-3 py-2 font-mono text-xs text-muted-foreground">
            Нет в списке диалогов
          </p>
          <ul className="divide-y divide-border border-t border-border">
            {orphans.map((id) => (
              <li key={id} className="flex items-center justify-between gap-3 px-3 py-2">
                <span className="font-mono text-xs text-foreground">Чат {id}</span>
                <Switch checked={false} onChange={() => setChat(id, true)} label={`Чат ${id}`} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function ChatItemRow({
  row,
  onToggle,
}: {
  row: ChatRow;
  onToggle: (id: number, next: boolean) => void;
}) {
  const { chat, enabled, lockedBy } = row;
  return (
    <li className="flex items-start justify-between gap-3 px-3 py-2">
      <div className="min-w-0">
        <span className="block font-mono text-xs text-foreground">{chat.title}</span>
        {chat.username && (
          <span className="block font-mono text-[11px] text-muted-foreground">@{chat.username}</span>
        )}
        {lockedBy && (
          <span className="mt-0.5 flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
            <MessagesSquare className="h-3 w-3 shrink-0" aria-hidden="true" />
            Комментарии канала «{lockedBy.title}»: доступна, пока канал включён
          </span>
        )}
      </div>
      <Switch
        checked={enabled}
        onChange={(next) => onToggle(chat.id, next)}
        label={chat.title}
        disabled={lockedBy !== null}
      />
    </li>
  );
}
```

`Switch` сейчас не принимает `disabled` — в `frontend/src/components/ui/switch.tsx` добавить необязательный проп (поведение остальных использований не меняется):

```tsx
export function Switch({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        'disabled:cursor-not-allowed disabled:opacity-60',
        checked ? 'border-primary bg-primary' : 'border-border bg-muted',
      )}
    >
      {/* …без изменений… */}
    </button>
  );
}
```

(Файл `switch.tsx` правится точечно через `Edit`: добавить `disabled`, `disabled={disabled}` и класс `disabled:…`; JSX бегунка не трогать.)

- [ ] **Step 4: Подключить в `TabSettings.tsx`**

Импорты:

```tsx
import { ChatsSettings } from '@/components/agent/ChatsSettings';
import { readDisabledChats, mergeDisabledChats } from '@/lib/chats/agentChats';
```

Начальное состояние формы: добавить `disabled_chats: [],` после `enabled_tools: null,`. В `useSyncedDraft`: после `enabled_tools: readEnabledTools(fresh.settings),` добавить `disabled_chats: readDisabledChats(fresh.settings),`. В `handleSave` заменить

```tsx
      const submissionSettings = mergeEnabledTools(mergedSettings, result.data.enabled_tools);
```

на

```tsx
      const submissionSettings = mergeDisabledChats(
        mergeEnabledTools(mergedSettings, result.data.enabled_tools),
        result.data.disabled_chats,
      );
```

В разметке сразу после `<ToolsSettings … />`:

```tsx
      <ChatsSettings
        agentId={agentId}
        value={values.disabled_chats ?? []}
        onChange={(disabledChats) => {
          setValues((v) => ({ ...v, disabled_chats: disabledChats }));
          setDirty(true);
        }}
      />
```

- [ ] **Step 5: Тесты `frontend/src/__tests__/chats-settings.test.tsx`**

```tsx
import { afterEach, describe, expect, mock, spyOn, test } from 'bun:test';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatsSettings } from '@/components/agent/ChatsSettings';
import { agentsApi } from '@/lib/api';
import type { AgentChat } from '@/types';

const AGENT_ID = '2dbc9cfd-4860-4c43-8c95-653d5155de00';

const NEWS: AgentChat = {
  id: -1001000000001,
  title: 'Новости дня',
  username: 'daily_news',
  kind: 'channel',
  discussion_of: null,
};
const COMMENTS: AgentChat = {
  id: -1001000000002,
  title: 'Комментарии дня',
  username: null,
  kind: 'group',
  discussion_of: NEWS.id,
};
const FRIENDS: AgentChat = {
  id: -1001000000003,
  title: 'Чат друзей',
  username: null,
  kind: 'group',
  discussion_of: null,
};
const ANNA: AgentChat = { id: 42, title: 'Анна', username: null, kind: 'private', discussion_of: null };

let listChats: ReturnType<typeof spyOn>;

afterEach(() => listChats?.mockRestore());

function renderSection(value: number[], onChange: (next: number[]) => void = () => {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ChatsSettings agentId={AGENT_ID} value={value} onChange={onChange} />
    </QueryClientProvider>,
  );
  return screen.getByTestId('chats-settings');
}

function mockChats(chats: AgentChat[]) {
  listChats = spyOn(agentsApi, 'listChats').mockResolvedValue(chats);
}

describe('ChatsSettings', () => {
  test('счётчик, группы свёрнуты, раскрытие показывает чаты', async () => {
    mockChats([NEWS, FRIENDS, ANNA]);
    const user = userEvent.setup();
    const section = renderSection([]);

    expect(await within(section).findByText('Доступно 3 из 3')).toBeTruthy();
    expect(within(section).queryByRole('switch', { name: 'Новости дня' })).toBeNull();

    await user.click(within(section).getByTestId('chat-group-channel'));
    expect(within(section).getByRole('switch', { name: 'Новости дня' })).toBeTruthy();
  });

  test('выключение чата отдаёт список отключённых с его ID', async () => {
    mockChats([NEWS, ANNA]);
    const user = userEvent.setup();
    const onChange = mock((_next: number[]) => {});
    const section = renderSection([999], onChange);
    await user.click(await within(section).findByTestId('chat-group-channel'));

    await user.click(within(section).getByRole('switch', { name: 'Новости дня' }));

    expect(onChange).toHaveBeenCalledWith([999, NEWS.id]);
  });

  test('отключённые чаты показываются выключенными и считаются', async () => {
    mockChats([NEWS, ANNA]);
    const user = userEvent.setup();
    const section = renderSection([ANNA.id]);
    expect(await within(section).findByText('Доступно 1 из 2')).toBeTruthy();

    await user.click(within(section).getByTestId('chat-group-private'));
    expect(within(section).getByRole('switch', { name: 'Анна' }).getAttribute('aria-checked')).toBe(
      'false',
    );
  });

  test('переключатель группы отключает все её чаты и сохраняет чужие ID', async () => {
    mockChats([NEWS, FRIENDS, COMMENTS, ANNA]);
    const user = userEvent.setup();
    const onChange = mock((_next: number[]) => {});
    const section = renderSection([ANNA.id], onChange);
    await within(section).findByText(/Доступно/);

    await user.click(within(section).getByRole('switch', { name: 'Все чаты группы «Группы»' }));

    const [next] = onChange.mock.calls[0] as [number[]];
    expect(next).toContain(ANNA.id);
    expect(next).toContain(FRIENDS.id);
    // Группа обсуждения включённого канала заблокирована им и не трогается групповым выключением.
    expect(next).not.toContain(COMMENTS.id);
  });

  test('группа обсуждения включённого канала заблокирована с пояснением', async () => {
    mockChats([NEWS, COMMENTS]);
    const user = userEvent.setup();
    const section = renderSection([COMMENTS.id]);
    await user.click(await within(section).findByTestId('chat-group-group'));

    const comments = within(section).getByRole('switch', { name: 'Комментарии дня' });
    expect(comments.getAttribute('aria-checked')).toBe('true');
    expect((comments as HTMLButtonElement).disabled).toBe(true);
    expect(
      within(section).getByText(/Комментарии канала «Новости дня»: доступна, пока канал включён/),
    ).toBeTruthy();
  });

  test('при отключённом канале группа обсуждения переключается сама', async () => {
    mockChats([NEWS, COMMENTS]);
    const user = userEvent.setup();
    const section = renderSection([NEWS.id, COMMENTS.id]);
    await user.click(await within(section).findByTestId('chat-group-group'));

    const comments = within(section).getByRole('switch', { name: 'Комментарии дня' });
    expect(comments.getAttribute('aria-checked')).toBe('false');
    expect((comments as HTMLButtonElement).disabled).toBe(false);
  });

  test('поиск по названию и @username раскрывает группы', async () => {
    mockChats([NEWS, FRIENDS, ANNA]);
    const user = userEvent.setup();
    const section = renderSection([]);
    await within(section).findByText(/Доступно/);

    await user.type(within(section).getByLabelText('Поиск чатов'), 'daily_news');

    expect(within(section).getByRole('switch', { name: 'Новости дня' })).toBeTruthy();
    expect(within(section).queryByRole('switch', { name: 'Чат друзей' })).toBeNull();
  });

  test('«Включить все» очищает список отключённых', async () => {
    mockChats([NEWS]);
    const user = userEvent.setup();
    const onChange = mock((_next: number[]) => {});
    const section = renderSection([NEWS.id], onChange);
    await within(section).findByText(/Доступно/);

    await user.click(within(section).getByRole('button', { name: 'Включить все' }));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  test('отключённые ID вне списка диалогов показываются и включаются обратно', async () => {
    mockChats([ANNA]);
    const user = userEvent.setup();
    const onChange = mock((_next: number[]) => {});
    const section = renderSection([777, ANNA.id], onChange);
    await within(section).findByText(/Доступно/);

    expect(within(section).getByText('Нет в списке диалогов')).toBeTruthy();
    await user.click(within(section).getByRole('switch', { name: 'Чат 777' }));

    expect(onChange).toHaveBeenCalledWith([ANNA.id]);
  });

  test('длинный список показывается порциями по 100', async () => {
    const many: AgentChat[] = Array.from({ length: 130 }, (_, index) => ({
      id: 1000 + index,
      title: `Человек ${index}`,
      username: null,
      kind: 'private',
      discussion_of: null,
    }));
    mockChats(many);
    const user = userEvent.setup();
    const section = renderSection([]);
    await user.click(await within(section).findByTestId('chat-group-private'));

    expect(within(section).getAllByRole('switch', { name: /^Человек \d+$/ })).toHaveLength(100);
    await user.click(within(section).getByRole('button', { name: 'Показать ещё' }));
    expect(within(section).getAllByRole('switch', { name: /^Человек \d+$/ })).toHaveLength(130);
  });

  test('остановленный агент (409): пояснение вместо списка, отключённые ID на месте', async () => {
    listChats = spyOn(agentsApi, 'listChats').mockRejectedValue({
      status: 409,
      message: 'Агент не запущен: запустите его, чтобы увидеть чаты.',
    });
    const section = renderSection([ANNA.id]);

    expect(await within(section).findByTestId('chats-not-running')).toBeTruthy();
    expect(within(section).getByRole('switch', { name: `Чат ${ANNA.id}` })).toBeTruthy();
    expect(within(section).queryByText(/Доступно/)).toBeNull();
  });

  test('прочая ошибка показывает сообщение и «Повторить»', async () => {
    listChats = spyOn(agentsApi, 'listChats').mockRejectedValue({
      status: 502,
      message: 'Не удалось получить список чатов из Telegram.',
    });
    const section = renderSection([]);

    await waitFor(() =>
      expect(within(section).getByRole('alert').textContent).toContain('Не удалось получить'),
    );
    expect(within(section).getByRole('button', { name: 'Повторить' })).toBeTruthy();
  });
});
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/agent/ChatsSettings.tsx frontend/src/components/agent/TabSettings.tsx frontend/src/components/ui/switch.tsx frontend/src/__tests__/chats-settings.test.tsx
git diff --cached --stat
git commit -m "feat(chats): секция «Чаты и каналы» в настройках агента"
```

---

### Task 9: Инфраструктура e2e и сценарий в браузере

**Files:**
- Modify: `src/mimic42/testing/telegram/account.py` (`FakeDialog`, `account.dialogs`)
- Modify: `src/mimic42/testing/telegram/client.py` (`iter_dialogs`)
- Modify: `src/mimic42/testing/telegram/__init__.py` (экспорт `FakeDialog`)
- Modify: `src/mimic42/testing/server.py` (маршрут `POST /__test__/telegram/{agent_id}/dialogs`)
- Modify: `tests/e2e/helpers.py` (`seed_dialogs`)
- Modify: `tests/e2e/test_agent.py` (сценарии)
- Test: `tests/testing/test_fake_telegram.py` (дописать)

**Interfaces:**
- Consumes: контракт интерфейса из Task 8; `TelethonChatDirectory.list_chats` (Task 2) читает `iter_dialogs(folder=…)` и `dialog.id/title/entity`.
- Produces:
  - `FakeDialog(id: int, title: str, kind: ChatKind, username: str | None = None, archived: bool = False)` с `.entity` — настоящая Telethon-сущность; `FakeTelegramAccount.dialogs: list[FakeDialog]`.
  - `FakeTelegramClient.iter_dialogs(limit=None, **kwargs)` — асинхронный итератор по диалогам папки `kwargs["folder"]` (0 — основной, 1 — архив).
  - `seed_dialogs(api, agent_id, dialogs: list[dict])` в e2e-хелперах.

- [ ] **Step 1: `FakeDialog` в `account.py`**

Импорты: `from datetime import UTC, datetime`, `from typing import Any, Literal`, `from telethon import types, utils`. После `SentMessage`:

```python
_FAKE_DATE = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class FakeDialog:
    """Диалог подделки аккаунта: ``entity`` — настоящая сущность Telethon,
    потому что каталог чатов различает виды по её типу."""

    id: int
    title: str
    kind: Literal["channel", "group", "private"]
    username: str | None = None
    archived: bool = False

    @property
    def entity(self) -> Any:
        real_id, _ = utils.resolve_id(self.id)
        if self.kind == "private":
            return types.User(
                id=real_id, first_name=self.title, username=self.username, access_hash=1
            )
        return types.Channel(
            id=real_id,
            title=self.title,
            photo=types.ChatPhotoEmpty(),
            date=_FAKE_DATE,
            access_hash=1,
            username=self.username,
            broadcast=True if self.kind == "channel" else None,
            megagroup=True if self.kind == "group" else None,
        )
```

В `FakeTelegramAccount.__init__` добавить `self.dialogs: list[FakeDialog] = []`.

- [ ] **Step 2: `iter_dialogs` в `client.py`** (после `emit_message`):

```python
    def iter_dialogs(self, limit: int | None = None, **kwargs: Any) -> Any:
        """Диалоги папки: 0 — основной список, 1 — архив (как у Telethon)."""
        archived = kwargs.get("folder") == 1
        dialogs = [d for d in self.account.dialogs if d.archived == archived]

        async def gen() -> Any:
            for dialog in dialogs:
                yield type(
                    "Dialog",
                    (),
                    {"id": dialog.id, "title": dialog.title, "entity": dialog.entity},
                )()

        return gen()
```

В `__init__.py` добавить `FakeDialog` в импорт из `account` и в `__all__`.

- [ ] **Step 3: Маршрут тестового сервера** — в `src/mimic42/testing/server.py`:

```python
class DialogSpec(BaseModel):
    id: int
    title: str
    kind: Literal["channel", "group", "private"]
    username: str | None = None
    archived: bool = False


class DialogsRequest(BaseModel):
    dialogs: list[DialogSpec]
```

(импорт: `from typing import Any, Literal`.)

Маршрут рядом с `deliver`:

```python
    @application.post("/__test__/telegram/{agent_id}/dialogs")
    async def seed_dialogs(agent_id: UUID, request: DialogsRequest) -> dict[str, str]:
        """Задаёт диалоги аккаунта агента: их увидит настройка «Чаты и каналы»."""
        registry.account_for(agent_id).dialogs = [
            FakeDialog(**dialog.model_dump()) for dialog in request.dialogs
        ]
        return {"status": "ok"}
```

и импорт `FakeDialog` из `mimic42.testing.telegram`.

- [ ] **Step 4: e2e-хелпер** — в `tests/e2e/helpers.py` после `deliver_message`:

```python
def seed_dialogs(api: httpx.Client, agent_id: str, dialogs: list[dict[str, object]]) -> None:
    _post(api, f"/__test__/telegram/{agent_id}/dialogs", {"dialogs": dialogs})
```

- [ ] **Step 5: Тест подделки** — дописать в `tests/testing/test_fake_telegram.py`:

```python
@pytest.mark.asyncio
async def test_fake_client_lists_dialogs_by_folder() -> None:
    from mimic42.testing.telegram import FakeDialog, FakeTelegramClient

    client = FakeTelegramClient()
    client.account.dialogs = [
        FakeDialog(id=42, title="Анна", kind="private"),
        FakeDialog(id=-1001000000001, title="Новости", kind="channel", archived=True),
    ]

    main = [d async for d in client.iter_dialogs(folder=0)]
    archive = [d async for d in client.iter_dialogs(folder=1)]

    assert [d.id for d in main] == [42]
    assert [d.id for d in archive] == [-1001000000001]
    assert main[0].entity.first_name == "Анна"
```

(Если в файле нет `import pytest` — добавить.)

- [ ] **Step 6: e2e-сценарии** — в `tests/e2e/test_agent.py` в класс `TestAgentPage` после `test_preset_applies_tool_settings`:

```python
    def test_chat_toggle_survives_save_and_reload(
        self, persona_page: Callable[..., Page], api: httpx.Client, users: dict
    ) -> None:
        agent_id = _new_agent(api, users, "Чаты", "running")
        seed_dialogs(
            api,
            agent_id,
            [
                {"id": -1001000000001, "title": "Новости дня", "kind": "channel"},
                {"id": -1001000000002, "title": "Чат друзей", "kind": "group"},
                {"id": 4242, "title": "Анна", "kind": "private"},
            ],
        )
        page = persona_page("full")
        page.goto(f"/agent/{agent_id}?tab=settings")

        chats = page.get_by_test_id("chats-settings")
        expect(chats.get_by_text("Доступно 3 из 3")).to_be_visible()

        chats.get_by_label("Поиск чатов", exact=True).fill("Новости")
        toggle = chats.get_by_role("switch", name="Новости дня")
        expect(toggle).to_have_attribute("aria-checked", "true")
        toggle.click()
        expect(chats.get_by_text("Доступно 2 из 3")).to_be_visible()

        page.get_by_role("button", name="Сохранить изменения").click()
        expect(page.get_by_test_id("toast-container")).to_contain_text("Настройки сохранены")

        page.reload()
        chats = page.get_by_test_id("chats-settings")
        expect(chats.get_by_text("Доступно 2 из 3")).to_be_visible()
        chats.get_by_label("Поиск чатов", exact=True).fill("Новости")
        expect(chats.get_by_role("switch", name="Новости дня")).to_have_attribute(
            "aria-checked", "false"
        )

    def test_chats_need_a_running_agent(
        self, persona_page: Callable[..., Page], api: httpx.Client, users: dict
    ) -> None:
        agent_id = _new_agent(api, users, "Чаты остановленного")
        page = persona_page("full")
        page.goto(f"/agent/{agent_id}?tab=settings")

        expect(page.get_by_test_id("chats-not-running")).to_contain_text("Запустите агента")
```

и импорт `seed_dialogs` в шапке `tests/e2e/test_agent.py` рядом с остальными импортами из `tests.e2e.helpers`.

- [ ] **Step 7: Commit**

```bash
git add src/mimic42/testing/telegram/account.py src/mimic42/testing/telegram/client.py src/mimic42/testing/telegram/__init__.py src/mimic42/testing/server.py tests/e2e/helpers.py tests/e2e/test_agent.py tests/testing/test_fake_telegram.py
git diff --cached --stat
git commit -m "test(chats): подделка диалогов, тестовый маршрут и e2e настройки чатов"
```

---

### Task 10: Живой тест в настоящем Telegram

**Files:**
- Create: `tests/real_tg/backend/test_real_chat_access.py`

**Interfaces:**
- Consumes: фикстуры `real_app`, `checker`, `started_mimics`; хелперы из `tests/real_tg/backend/test_real_first_comment.py` (`reload`, `first_comment`, `channel_with_discussion`, `first_comment_events`, `dsn`, `comments_under`, `WATCH_SECONDS`, `FAST_SECONDS`); `Checker.import_contact/send/collect_messages/resolve_id/post/collect_thread/my_id`.
- Produces: два теста `real_tg`: личный чат (отключённый не получает ответа, включённый получает) и канал с первым комментарием (отключённый не комментируется, включённый — комментируется).

Правила прогона (память проекта): прогон один, в финале (Task 11); замок `RealTelegramLock` берёт сам набор `real_tg`; до прогона перечитать документацию каждого запроса Telegram, который делает тест, и состояние фикстур в Dev-базе (агент `started_mimics[0]` на бесплатной модели).

- [ ] **Step 1: Написать `tests/real_tg/backend/test_real_chat_access.py`**

```python
"""Отключённые чаты в настоящем Telegram: личка без ответа, канал без комментария.

Настройка включается так же, как это делает дашборд: запись в ``agents.settings``
и перезагрузка рантайма. Модель бесплатная, а ожидание ответа ограничено, чтобы
отсутствие реплики было доказательством, а не таймаутом на медленной модели:
в той же сессии «включённый» чат отвечает, значит, молчание — результат настройки.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from mimic42.testing.real_tg.checker import Checker
from tests.real_tg.backend.helpers import jwt
from tests.real_tg.backend.test_real_first_comment import (
    FAST_SECONDS,
    WATCH_SECONDS,
    channel_with_discussion,
    comments_under,
    dsn,
    first_comment,
    first_comment_events,
    reload,
)

pytestmark = pytest.mark.real_tg

# Сколько ждать ответа, который не должен прийти: модель на бесплатном тарифе отвечает
# за десятки секунд, а положительный контроль в конце теста подтверждает, что ответы идут.
SILENCE_SECONDS = 60.0


@asynccontextmanager
async def disabled_chats(
    client: AsyncClient, token: str, agent_id: str, chat_ids: list[int]
) -> AsyncIterator[None]:
    """Отключает чаты и возвращает прежнее значение настройки."""
    conn = await asyncpg.connect(dsn())
    try:
        original = await conn.fetchval(
            "select settings->'disabled_chats' from agents where id = $1::uuid", agent_id
        )
        await conn.execute(
            "update agents set settings = settings"
            " || jsonb_build_object('disabled_chats', $2::jsonb) where id = $1::uuid",
            agent_id,
            json.dumps(chat_ids),
        )
    finally:
        await conn.close()
    try:
        await reload(client, token, agent_id)
        yield
    finally:
        conn = await asyncpg.connect(dsn())
        try:
            if original is None:
                await conn.execute(
                    "update agents set settings = settings - 'disabled_chats'"
                    " where id = $1::uuid",
                    agent_id,
                )
            else:
                await conn.execute(
                    "update agents set settings = jsonb_set(settings, '{disabled_chats}', $2::jsonb)"
                    " where id = $1::uuid",
                    agent_id,
                    original,
                )
        finally:
            await conn.close()
        await reload(client, token, agent_id)


async def test_disabled_private_chat_gets_no_reply_and_enabled_one_does(
    real_app: tuple[FastAPI, AsyncClient],
    checker: Checker,
    started_mimics: list[tuple[str, str]],
) -> None:
    _, client = real_app
    agent_id, phone = started_mimics[0]
    await checker.import_contact(phone)
    mimic_id = await checker.resolve_id(phone)
    checker_id = await checker.my_id()
    token = await jwt()

    async with disabled_chats(client, token, agent_id, [checker_id]):
        watcher = asyncio.ensure_future(
            checker.collect_messages(mimic_id, seconds=SILENCE_SECONDS)
        )
        await asyncio.sleep(1)
        await checker.send(phone, "Ты меня слышишь?")
        seen = await watcher
    replies = [m for m in seen if m.sender_id == mimic_id]
    assert replies == [], f"мимик ответил из отключённого чата: {replies}"

    # Положительный контроль: после включения чата тот же собеседник получает ответ.
    reply = await checker.send_and_wait_reply(phone, "А теперь слышишь?", timeout=300)
    assert reply and reply.strip(), "после включения чата мимик не ответил"


async def test_disabled_channel_gets_no_first_comment_and_enabled_one_gets(
    real_app: tuple[FastAPI, AsyncClient],
    checker: Checker,
    started_mimics: list[tuple[str, str]],
) -> None:
    _, client = real_app
    agent_id, phone = started_mimics[0]
    await checker.import_contact(phone)
    mimic_id = await checker.resolve_id(phone)
    token = await jwt()
    comment = f"Первый! {uuid4().hex[:6]}"
    started = datetime.now(UTC)
    loop = asyncio.get_running_loop()
    channel_id, group_id = await channel_with_discussion(checker, phone)

    async with first_comment(client, token, agent_id, [{"text": comment}]):
        async with disabled_chats(client, token, agent_id, [channel_id]):
            watcher = asyncio.ensure_future(
                checker.collect_thread(group_id, seconds=WATCH_SECONDS)
            )
            await asyncio.sleep(1)
            muted_post = await checker.post(channel_id, "Пост в отключённый канал")
            muted_seen = await watcher

        events_muted = await first_comment_events(agent_id, started)
        assert comments_under_or_empty(muted_seen, [muted_post], mimic_id, comment) == []
        assert [e for e in events_muted if e.get("peer") == str(channel_id)] == [], events_muted

        # Положительный контроль: канал снова включён (disabled_chats вернулся).
        watcher = asyncio.ensure_future(checker.collect_thread(group_id, seconds=WATCH_SECONDS))
        await asyncio.sleep(1)
        post_at = loop.time()
        post_id = await checker.post(channel_id, "Пост во включённый канал")
        seen = await watcher

    on_post = comments_under(seen, [post_id], mimic_id, comment)
    assert len(on_post) == 1, f"под постом {len(on_post)} первых комментариев"
    assert on_post[0].arrived - post_at < FAST_SECONDS


def comments_under_or_empty(seen: list[Any], post_ids: list[int], author: int, text: str) -> list[Any]:
    """Комментарии автора к постам; пересылка поста в обсуждение может не прийти за окно."""
    forwards = {m.message_id for m in seen if m.channel_post in post_ids}
    return [m for m in seen if m.sender_id == author and m.text == text and m.reply_to in forwards]
```

(`comments_under` из первого комментария падает, если пост не переслан в обсуждение; для отрицательного случая используется собственный `comments_under_or_empty`.)

- [ ] **Step 2: Проверить предпосылки до прогона (без запуска теста)**

Прочитать: Telethon `NewMessage(chats=[peer_id])` в `Checker.collect_messages`; что `ensure_channel` возвращает marked ID (`-100…`), так как `first_comment_events` сравнивает `peer` со `str(quiet_id)`; что настройки `started_mimics[0]` — бесплатная модель (`ensure_free_model`). Состояние Dev-базы: у `started_mimics[0]` нет сторонних `disabled_chats` в `settings`.

- [ ] **Step 3: Commit**

```bash
git add tests/real_tg/backend/test_real_chat_access.py
git diff --cached --stat
git commit -m "test(chats): живая проверка отключённых чатов в Telegram"
```

---

### Task 11: Ревью, слияние main, единый прогон, доска

**Files:** диф ветки целиком.

**Interfaces:** Consumes: все предыдущие задачи. Produces: ветка, готовая к проверке пользователем (PR не открывается).

- [ ] **Step 1: Ревьюеры на диф до любого запуска тестов**

Запустить `feature-dev:code-reviewer` на `git diff origin/main...HEAD` с контекстом: спека `docs/superpowers/specs/2026-10-07-target-chats-design.md`, этот план, список «Review Focus». Попросить проверить против документации Telethon: (a) `get_peer_id`/`InputPeerSelf`, (b) `linked_chat_id` у супергруппы, (c) что ни один чат-параметр инструментов не обходит `_resolve_chat/_guard_chat` (структурный тест это стережёт, но ревьюер читает код), (d) порядок проверок в `_dispatch_incoming`, (e) гонки: `ChatAccess` неизменяем, кеш каталога под `asyncio` без блокировок — допустимо ли. Исправить всё найденное одним пакетом; повторное ревью — только если правки нетривиальны.

- [ ] **Step 2: Слить свежий main**

```bash
git fetch origin
git merge origin/main
```

Разрешить конфликты (вероятные места: `agent_runtime.py`, `telegram_tools.py`, `TabSettings.tsx`, `app.py`), снова просмотреть диф конфликтных файлов.

- [ ] **Step 3: Один полный прогон (набор из CLAUDE.md «Pre-PR»)**

Бэкенд, по одной команде за вызов, в фоне, вывод не обрезать:

```bash
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -m "not db and not e2e and not real_tg and not real_llm" -W error -q
```

Фронтенд:

```bash
bun install --cwd=frontend --frozen-lockfile
bun run --cwd=frontend lint
bun run --cwd=frontend typecheck
bun run --cwd=frontend test
```

Дополнительно (Dev-база, один раз): `uv run pytest -m db tests/integration/test_database_agent_store.py tests/integration/test_agent_timers.py -W error -q`; e2e только сценарии чатов: `uv run pytest tests/e2e/test_agent.py -m e2e -k "chat" -W error -q`; живой — `uv run pytest tests/real_tg/backend/test_real_chat_access.py -m real_tg -W error -q` (замок `RealTelegramLock` берёт набор сам; занят — дождаться чужого прогона, не обходить).

Если что-то упало — разобрать причину по полному выводу, исправить всё найденное, потом повторить прогон один раз. Если падает старый (не связанный) тест — тоже довести до рабочего состояния.

- [ ] **Step 4: Доска и ветка**

```bash
gh api user -q .login
git push -u origin feat/target-chats
```

(`gh` должен работать от `crbanana`; иначе `gh auth switch --hostname github.com --user crbanana`.) Найти идентификаторы поля «Status» и опции «В работе» командой `gh project field-list 2 --owner 42-Z --format json` и перевести задачу #94 в работу через `gh project item-edit` (идентификатор элемента — из `gh project item-list 2 --owner 42-Z --format json`). Если ветка уже на GitHub и CI запускается на push — одно ожидание: `gh pr checks` появится только после PR, поэтому статус CI смотрится после открытия PR.

- [ ] **Step 5: Передать пользователю на локальную проверку**

Сообщить: ветка `feat/target-chats` запушена, как проверить локально (запустить агента, открыть «Настройки» → «Чаты и каналы», отключить чат/канал, сохранить, убедиться в тишине; включить канал с комментариями). **PR не открывать до её подтверждения.** После подтверждения: открыть PR (описание с трейлером из контекста сессии), дождаться CI одним ожиданием (`gh pr checks`), затем по правилам репозитория: миграций нет, поэтому на прод — только мерж с `--admin`; проверить дальнейшие шаги по базе (их нет) и скинуть итог владелице.

---

## Self-Review

**1. Spec coverage**

| Раздел спеки | Задача |
|---|---|
| Правило доступа, формат настройки, миграции нет | Task 1, 3 |
| Комментарии (`linked_chat_id`) | Task 1 (`allows`), Task 2 (`discussion_of`) |
| Политика `ChatAccess`, `parse_disabled_chats` | Task 1 |
| Конфиг и сборка (общий объект с тулзами) | Task 3 |
| Входящие (после вердикта прогрева, не в ленту), первый комментарий | Task 5 |
| Инструменты (`_resolve_chat`, люди не проверяются, `get_dialogs`/папки/общие чаты, `join_channel`, `set_wakeup_timer`, media_id не проверяются) | Task 4 |
| Таймеры (`failed` без миграции) | Task 5 |
| API (`GET …/chats`, 409/403/404/501, `discussion_of`, архив) | Task 2, 6 |
| Интерфейс (счётчик, поиск, группы, блокировка группы обсуждения, «Нет в списке», 409, `merge/read`, хук, каталог ошибок) | Task 7, 8 |
| Тестирование (core, tools, runtime, api, db, bun, e2e, real_tg) | Task 1–10 |
| Чего не делаем | не реализуется ни одной задачей |

Пробелов нет. Прогрев: личка от мимика проходит (Task 5), зачины не проверяются (код `send_warmup_opener` не меняется).

**2. Placeholder scan:** TBD/TODO в плане нет; везде приведён код или точная команда. Единственный «по месту» момент — Step 4 Task 4 (механическая замена `_resolve_peer` → `_resolve_chat` по перечню методов с проверкой `grep`), код замены тривиален, перечень полный, критерий проверки — ровно 11 оставшихся вызовов.

**3. Type consistency:** `ChatAccess.allows(chat_id, *, has_link)`, `.disabled`; `ChatDisabledError(chat_id)`; `link_hint`; `DiscussionLookup`; `ChatItem`/`ChatDirectory` (Task 1) → `TelethonChatDirectory` (Task 2) → менеджер (Task 3) → рантайм `_chat_directory`/`list_chats` (Task 5) → `ChatDirectoryControl.list_chats(agent_id)` (Task 6) → `AgentChat`/`agentsApi.listChats`/`useAgentChats` (Task 7) → `ChatsSettings` (Task 8). Параметр `chat_access` одинаково назван в `MimicAgentRuntime`, `TelegramToolbox`, `build_telegram_langchain_tools`. Поле конфига `disabled_chats` (frozenset) ↔ `settings.disabled_chats` (массив) ↔ форма `disabled_chats: number[]`.
