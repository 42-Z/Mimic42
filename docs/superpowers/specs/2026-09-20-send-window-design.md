# Дизайн: окно отправки (медленный режим и запрет писать)

Issue: https://github.com/42-Z/Mimic42/issues/72
Дата: 2026-09-20

## Цель

Агент не должен пытаться писать туда, где писать сейчас нельзя: в чате включён медленный
режим и слот ещё не открылся, либо у аккаунта забрали право отправлять сообщения.

Ключевая мысль: обе ситуации — одно состояние, **окно отправки закрыто до момента T**.
Для медленного режима T — момент открытия слота, для ограничения прав T — `until_date`
(возможно, бесконечность). Один механизм закрывает обе половины issue.

Вторая ключевая мысль: медленный режим — не ошибка отправки, а бюджет. В живом чате
сообщения приходят чаще, чем раз в 30 секунд, поэтому «подождать и отправить» приводит к
тому, что агент отвечает на устаревшее. Значит нужно не ждать, а схлопывать очередь и
давать агенту видеть цену слота.

## Контекст (по коду)

- Основной ответ уходит через `MimicAgentRuntime._humanized_send`
  (`src/mimic42/core/agent_runtime.py:292`), решение об отправке принимается в
  `trigger_message` по структурированному ответу `AgentResponse`
  (`send_any_message`, `text`, `reply_to`).
- Входящее проходит путь `_handle_incoming_message` → `AlbumGrouper` →
  `_process_incoming(events)`. `_process_incoming` уже принимает список событий, но
  склеивает их как один альбом: общая шапка берётся от первого события.
- В `_process_incoming` уже есть проверка мьюта — но это мьют **уведомлений**
  (`account.GetNotifySettings`), то есть «агент сам приглушил чат». К правам на отправку
  отношения не имеет и остаётся как есть.
- `AlbumGrouper` (`src/mimic42/core/album_grouper.py`) — готовый образец буфера с
  дедлайном, отменой на `close()` и защитой flush'а в полёте. Новый буфер делается по
  его образцу.
- Инструменты отправки живут в `TelegramToolbox` (`integrations/telegram_tools.py`),
  каждый заворачивает исключение в `_tool_failure(exc)`.
- У `send_text_message` уже есть собственный кулдаун в 5 минут — он про другое
  (чтобы агент не слал инструментом то, что должен был сказать основным ответом).
  Остаётся, но в тексте ошибки различается с медленным режимом.
- `agent_events.event_type` — свободный `text`, миграция для новых событий не нужна.

## Фактура Telethon и Telegram API

Проверено по документации и установленной версии Telethon.

- Медленный режим есть только в супергруппах. В ЛС и обычных группах его не бывает.
- `types.Channel` приходит вместе с сущностью чата и уже содержит всё дешёвое:
  `slowmode_enabled`, `banned_rights` (личное ограничение **этого** аккаунта),
  `default_banned_rights` (общий запрет для всех), `admin_rights`, `creator`,
  `broadcast`, `megagroup`, `left`.
- `types.Chat` (обычная группа) содержит только `default_banned_rights` — личных
  ограничений в базовых группах не бывает.
- `ChatBannedRights` — флаги `send_messages`, `send_media`, `send_plain`, `send_photos`,
  `send_videos`, `send_voices`, `send_stickers`, `send_polls` и `until_date`.
  `until_date == 0` или дата дальше чем через 366 дней означает «навсегда».
- Точные числа медленного режима — в `ChannelFull`
  (`channels.GetFullChannelRequest`): `slowmode_seconds` («писать можно не чаще раза в
  N секунд») и `slowmode_next_send_date` («когда именно этому аккаунту снова можно
  писать», unixtime). Запрос дорогой, поэтому кэшируется.
- Админ супергруппы не подчиняется ни медленному режиму, ни `default_banned_rights`.
- Ошибки, которые Telegram отдаёт по этой теме (все есть в `telethon.errors`):
  `SlowModeWaitError` (несёт точный остаток в `.seconds`), `ChatWriteForbiddenError`,
  `UserBannedInChannelError`, `ChatRestrictedError`, `ChatSendPlainForbiddenError`,
  `ChatSendMediaForbiddenError`, `ChatSendStickersForbiddenError`,
  `ChatSendGifsForbiddenError`, `ChatSendPhotosForbiddenError`,
  `ChatSendVideosForbiddenError`, `ChatSendVoicesForbiddenError`,
  `ChatSendPollForbiddenError`, `ChatAdminRequiredError`.
  `SlowModeWaitError` и `FloodWaitError` — общий предок `FloodError`.

## Принятые решения

| Вопрос | Решение |
|---|---|
| Ждать ли окончания кд внутри хода | Нет. Ожидание держит `_trigger_lock` и копит отставание |
| Что с сообщениями, пока слот закрыт | Копятся в буфере по чату, разбираются одним ходом при открытии |
| Глубина буфера | Кап по количеству и возрасту, устаревшее выбрасывается |
| Знает ли агент про кд | Да, состояние чата пишется в шапку входящего, цена слота видна |
| Реплай при схлопывании | Обязателен. Если модель не указала — рантайм ставит последнее сообщение пачки |
| Забрали право писать надолго | Один ход-уведомление на смене состояния, дальше чат игнорируется до снятия |
| Проверка прав | Дёшево из сущности чата, дорого (`GetFullChannel`) только при медленном режиме |
| Источник истины | Ошибка Telegram. Локальный расчёт — оптимизация, ошибка его перетирает |

## Архитектура

Две новые единицы в `core/`, обе без зависимостей на Telethon-клиент кроме вызова
одного запроса, и обе тестируются изолированно.

### `core/send_window.py` — состояние «когда я снова смогу писать»

```python
Reason = Literal["open", "slowmode", "restricted"]

@dataclass(frozen=True)
class SendWindow:
    reason: Reason
    open_at: float | None      # None при reason="open" или при бессрочном запрете
    forever: bool              # запрет без срока
    slowmode_seconds: int | None

    @property
    def is_open(self) -> bool: ...
    def retry_after(self, now: float) -> int | None: ...
```

`SendWindowTracker` хранит состояние по peer и умеет:

- `async def check(peer, chat=None) -> SendWindow` — текущее окно. Сущность чата берётся
  из переданной (в горячем пути она уже загружена обработчиком входящего) либо через
  `get_entity`. Разбор:
  - `User` — окно открыто; блокировки ловятся реактивно по ошибке
  - `Chat` — `default_banned_rights.send_messages` → `restricted`, иначе открыто
  - `Channel` с `admin_rights` или `creator` — всегда открыто
  - `Channel` с `left` (агента выгнали или он вышел) → `restricted` бессрочно
  - `Channel` с `banned_rights.send_messages` → `restricted` до `until_date`
  - `Channel` с `default_banned_rights.send_messages` → `restricted` бессрочно
  - `Channel` c `broadcast` и без прав на постинг → `restricted` бессрочно
    (комментарии под постом уходят в связанную группу — это другой peer со своим окном)
  - `Channel` с `slowmode_enabled` → `slowmode`; `slowmode_seconds` и
    `slowmode_next_send_date` берутся из `GetFullChannel` один раз и кэшируются
- `def note_sent(peer)` — слот израсходован, окно закрывается на `slowmode_seconds`
- `def note_error(peer, exc)` — синхронизация по ответу Telegram:
  - `SlowModeWaitError` / `FloodWaitError` → закрыть на `exc.seconds`
  - `ChatWriteForbiddenError`, `UserBannedInChannelError`, `ChatRestrictedError`,
    `ChatSend*ForbiddenError`, `ChatAdminRequiredError` → `restricted`, бессрочно,
    кэш сущности сбросить, чтобы следующая проверка перечитала реальные права
- `def note_state_announced(peer)` / `def was_announced(peer)` — чтобы уведомление о
  запрете ушло агенту один раз на переход, а не на каждое сообщение

Кэш сущности и `ChannelFull` — с TTL, по образцу существующих `_chat_mute_cache` и
`_member_tag_cache` в рантайме.

### `core/deferred_inbox.py` — буфер входящих на время закрытого окна

По образцу `AlbumGrouper`, отличия:

- ключ — peer, а не `(chat_id, grouped_id)`
- хранит **группы** событий: альбом остаётся одной группой, поэтому тип —
  `list[list[Event]]`
- дедлайн — момент открытия окна, а не тихое окно
- кап `MAX_GROUPS` (по умолчанию 20) и `MAX_AGE` (по умолчанию 600 с): при переполнении
  вытесняются самые старые, при flush отбрасываются протухшие. Отставание в три часа
  становится невозможным по построению
- `close()` отменяет ожидание и не обрывает flush в полёте — как у `AlbumGrouper`

### Точка врезки в рантайм

`_handle_incoming_message` → `AlbumGrouper` → **новый `_dispatch_incoming(events)`** →
ход либо буфер.

`_dispatch_incoming`:

1. существующая проверка мьюта уведомлений — как сейчас
2. `window = await send_window.check(peer, chat)`
3. окно открыто → `_process_batch([events])`
4. окно откроется скоро (`retry_after <= DEFER_LIMIT`, по умолчанию 300 с) →
   `deferred_inbox.add(peer, events, window.open_at)`, событие `message.deferred`
   (один раз на переход, не на каждое сообщение)
5. окно закрыто надолго или бессрочно → событие `message.write_forbidden`, и, если
   переход ещё не объявлен, один служебный ход-уведомление: агент узнаёт, что в чате X
   ему запретили писать и до какого момента, и может отреагировать иначе (написать
   админу в ЛС, поставить таймер) или промолчать. Дальше входящие из этого чата
   игнорируются, пока окно не откроется

Буфер при срабатывании зовёт `_process_batch(groups)`.

### Схлопывание пачки

`_process_incoming` сейчас ~360 строк и форматирует входящее вперемешку с решением о
ходе. Разделяем по ходу дела — это часть работы, а не отдельный рефакторинг:

- `_format_incoming(events) -> IncomingBlock` — форматирование одного сообщения или
  альбома: текст блока, медиа, `message_id`, `reply_to`, имя треда. Ровно то, что сейчас
  делает тело `_process_incoming`
- `_process_batch(groups)` — собирает блоки, формирует общий текст и зовёт
  `trigger_message`

Для одной группы текст не меняется вообще — обратная совместимость сохраняется.
Для пачки сверху добавляется шапка: сколько сообщений пришло, пока агент молчал, какой
медленный режим в чате, и что ответить можно ровно одним сообщением с обязательным
`reply_to`.

### Обязательный реплай

`AgentTrigger` получает `require_reply_to: bool` и `fallback_reply_to: int | None`
(идентификатор последнего сообщения пачки). В `trigger_message`, после разбора
структурированного ответа: если отправка нужна, `require_reply_to` взведён, а модель
`reply_to` не вернула — подставляется `fallback_reply_to`, факт подстановки логируется.
В потоке не остаётся висячих ответов.

### Предохранитель на самой отправке

В `trigger_message` перед `_humanized_send` окно перепроверяется (между решением и
отправкой прошло время на генерацию). Закрыто — не отправляем, пишем событие. После
успешной отправки — `note_sent`, в `except` — `note_error` рядом с уже существующей
записью `message.send_failed`.

### Инструменты

`TelegramToolbox` получает тот же `SendWindowTracker`. Чтобы не размазывать проверку по
дюжине методов — один асинхронный контекстный менеджер:

```python
@asynccontextmanager
async def _sending(self, peer: str):
    window = await self._send_window.check(peer)
    if not window.is_open:
        raise SendWindowClosed(window)
    try:
        yield
    except Exception as exc:
        self._send_window.note_error(peer, exc)
        raise
    else:
        self._send_window.note_sent(peer)
```

Оборачиваются: `send_text_message`, `send_file`, `send_voice_note`, `send_video_note`,
`send_sticker`, `send_poll`, `send_location`, `send_venue`, `send_inline_bot_result`,
`forward_messages`.

`_tool_failure` получает ветку для `SendWindowClosed`: помимо `error` и `error_code`
возвращаются `reason` и `retry_after_seconds`, чтобы модель могла поставить таймер, а не
долбиться в закрытую дверь. Та же ветка срабатывает и на сырые ошибки Telegram, если
Telegram отказал раньше локальной проверки.

`SendWindowTracker` в тулбоксе опционален: при `None` поведение прежнее, поэтому
существующие тесты, создающие `TelegramToolbox` напрямую, не ломаются.

### Промпт

В `BASE_SYSTEM_PROMPT.txt` — короткий абзац о механике: в части групп включён медленный
режим, писать можно не чаще раза в N секунд, состояние видно в шапке входящего, слот
один и при ответе на пачку нужен `reply_to`; если право писать забрали, отправка туда не
сработает. Только факты о среде, без указаний, как себя вести.

### Лента

Два новых типа событий и записи в `frontend/src/lib/activity/eventCatalog.ts`:

- `message.deferred` — «Ответ отложен: медленный режим»
- `message.write_forbidden` — «Нет права писать в чате»

Оба пишутся на смене состояния, а не на каждое входящее, иначе лента забьётся.

## Тесты

- `tests/core/test_send_window.py` — разбор `User` / `Chat` / `Channel`, админ обходит
  ограничения, `until_date == 0` как бессрочный, расход слота, синхронизация по
  `SlowModeWaitError` и `ChatWriteForbiddenError`
- `tests/core/test_deferred_inbox.py` — копит группы, отдаёт одной пачкой на дедлайне,
  вытеснение по глубине, отбрасывание по возрасту, поведение `close()`
  (по образцу `tests/core/test_album_grouper.py`)
- `tests/core/test_agent_runtime.py` — окно закрыто, ход не запускается; окно открылось,
  запускается один ход со всей пачкой; `reply_to` подставляется фоллбэком; предохранитель
  отменяет отправку
- `tests/integrations/test_telegram_tools.py` — `send_*` при закрытом окне возвращает
  `retry_after_seconds` и причину; успешная отправка расходует слот

## Что в объём не входит

- Ограничения по типам контента (`send_media`, `send_stickers`, `send_polls` и прочие
  флаги `ChatBannedRights`). Окно моделирует только право на отправку сообщения как
  таковую; отказы по типам ловятся реактивно и возвращаются агенту как понятная ошибка
- Медленный режим при отправке через связанную группу канала считается по peer этой
  группы, отдельной логики для комментариев нет
- Миграции БД
