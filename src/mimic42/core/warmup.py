"""Прогрев аккаунтов: мимики пишут друг другу в личку, как живые знакомые.

Здесь только решения, без Telegram и БД: когда писать, кому, что и сколько
сообщений в диалоге. Всё детерминировано от Random, чтобы тесты и расписание
были воспроизводимыми.

Расписание дня считается из (agent_id, дата) и не хранится: после рестарта
процесса агент получает те же слоты, а уже случившееся видно по событиям.
"""

from __future__ import annotations

import random
from collections import deque
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from mimic42.core.warmup_messages import CHECK_INS, GREETINGS, OPENERS, QUESTIONS

DEFAULT_TIMEZONE: Final = "Europe/Moscow"
ACTIVE_FROM_HOUR: Final = 10
ACTIVE_TO_HOUR: Final = 23
MIN_SLOT_GAP: Final = timedelta(hours=2)
# «Пару диалогов в день»: чаще два, иногда один или три.
DIALOGS_PER_DAY: Final = (1, 2, 3)
DIALOGS_PER_DAY_WEIGHTS: Final = (3, 5, 2)
# Доля диалогов с тем, с кем уже общались: люди пишут знакомым, а не каждый раз новым.
REPEAT_PARTNER_CHANCE: Final = 0.6
# Диалог — это всего сообщений от обеих сторон вместе с зачином.
DIALOG_LENGTH_RANGE: Final = (4, 9)
DIALOG_IDLE_TIMEOUT: Final = timedelta(hours=3)
# Режим восстановления: аккаунт не может писать первым, поэтому диалогов с ним
# больше и они дольше — активность живого человека, а не разовый «привет».
RECOVERY_DIALOGS_PER_DAY: Final = (4, 5, 6, 7)
RECOVERY_SLOT_GAP: Final = timedelta(minutes=75)
RECOVERY_DIALOG_LENGTH_RANGE: Final = (7, 14)
# Общий бюджет отправителя: зачины в обычном прогреве и в помощи ограниченным вместе.
MAX_OPENERS_PER_DAY: Final = 6
MIN_OPENER_INTERVAL: Final = timedelta(minutes=30)
# Попытка и её запись в журнал разнесены во времени: так события считаются одной попыткой.
ATTEMPT_MATCH_WINDOW: Final = timedelta(minutes=10)
# Как часто спрашивать @SpamBot, снято ли ограничение.
SPAMBOT_CHECK_INTERVAL: Final = timedelta(hours=6)
SPAMBOT_REPLY_WAIT_SECONDS: Final = 6.0
EVENT_OPENER_SENT: Final = "warmup.opener_sent"
EVENT_OPENER_FAILED: Final = "warmup.opener_failed"
EVENT_RESTRICTED: Final = "warmup.restricted"
EVENT_RECOVERY_STARTED: Final = "warmup.recovery_started"
EVENT_RECOVERED: Final = "warmup.recovered"


@dataclass(frozen=True)
class WarmupSettings:
    """Настройка прогрева (``agents.settings["warmup"]``): только то, что меняет пользователь.

    Прогрев выключен, пока пользователь сам его не включит. Ограничение Telegram и
    режим восстановления сюда не входят: их ведёт сервер (см. ``WarmupState``).
    """

    enabled: bool = False
    timezone: str = DEFAULT_TIMEZONE


@dataclass(frozen=True)
class WarmupState:
    """Ограничение аккаунта: когда Telegram запретил писать первым и выбрано ли восстановление.

    Хранится в колонках ``agents.warmup_restricted_at`` и ``agents.warmup_recovery``, а не в
    ``settings``: форма настроек перезаписывает ``settings`` целиком.
    """

    restricted_at: datetime | None = None
    recovery: bool = False


def parse_warmup(raw: object) -> WarmupSettings:
    """Настройка из ``agents.settings["warmup"]``.

    Чужая или устаревшая форма не должна ронять сборку рантайма, поэтому всё
    нераспознанное считается значением по умолчанию (прогрев выключен).
    """
    if not isinstance(raw, Mapping):
        return WarmupSettings()
    values = cast("Mapping[str, Any]", raw)
    enabled = values.get("enabled")
    timezone = values.get("timezone")
    return WarmupSettings(
        enabled=enabled if isinstance(enabled, bool) else False,
        timezone=(
            timezone if isinstance(timezone, str) and _is_timezone(timezone) else DEFAULT_TIMEZONE
        ),
    )


def _is_timezone(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        ZoneInfo(value)
    except (ValueError, KeyError, OSError):
        return False
    return True


def daily_slots(
    agent_id: UUID, day: date, tz: str = DEFAULT_TIMEZONE, *, recovery: bool = False
) -> list[datetime]:
    """Моменты (UTC), когда агент должен начать диалог в этот день.

    Время случайное в активные часы, между слотами не меньше MIN_SLOT_GAP —
    ночью и подряд аккаунты не пишут.
    """
    rng = random.Random(f"warmup{'-recovery' if recovery else ''}:{agent_id}:{day.isoformat()}")
    if recovery:
        count = rng.choice(RECOVERY_DIALOGS_PER_DAY)
        gap = RECOVERY_SLOT_GAP
    else:
        count = rng.choices(DIALOGS_PER_DAY, weights=DIALOGS_PER_DAY_WEIGHTS)[0]
        gap = MIN_SLOT_GAP
    zone = ZoneInfo(tz)
    start = datetime.combine(day, time(ACTIVE_FROM_HOUR), tzinfo=zone)
    window_minutes = (ACTIVE_TO_HOUR - ACTIVE_FROM_HOUR) * 60
    # Минуты назначаются с запасом на зазоры: каждый следующий слот сдвигается
    # на MIN_SLOT_GAP, а случайность делит оставшееся пространство.
    gap_minutes = int(gap.total_seconds() // 60)
    # Последний слот строго до конца окна: 23:00 уже ночь.
    free = max(1, window_minutes - gap_minutes * (count - 1))
    offsets = sorted(rng.randrange(free) for _ in range(count))
    slots = [
        start + timedelta(minutes=offset + gap_minutes * i) for i, offset in enumerate(offsets)
    ]
    return [slot.astimezone(UTC) for slot in slots]


def due_slot(
    slots: Sequence[datetime],
    *,
    now: datetime,
    attempts: Sequence[datetime],
    grace: timedelta = timedelta(hours=1),
) -> datetime | None:
    """Слот, который пора отработать: наступил, не просрочен и ещё не занят попыткой.

    Попытки (отправка или неудача) раскладываются по слотам в порядке времени: каждая
    занимает самый ранний слот, который к тому моменту наступил и ещё не просрочился.
    Слот, пропущенный из-за выключенного сервера, остаётся пропущенным, а не
    «догоняется» следующим тиком: писать задним числом в час ночи нельзя, а поздний
    слот, уже отработанный попыткой, повторно не берётся.
    """
    taken: set[int] = set()
    for attempt in sorted(attempts):
        for index, slot in enumerate(slots):
            if index not in taken and slot <= attempt <= slot + grace:
                taken.add(index)
                break
    for index, slot in enumerate(slots):
        if index in taken:
            continue
        if slot > now:
            return None
        if now - slot <= grace:
            return slot
    return None


def merge_attempts(stored: Sequence[datetime], reserved: Sequence[datetime]) -> list[datetime]:
    """Попытки из журнала плюс ещё не записанные резервы, без двойного счёта одной попытки."""
    merged = list(stored)
    for moment in reserved:
        if not any(abs(moment - known) <= ATTEMPT_MATCH_WINDOW for known in stored):
            merged.append(moment)
    return sorted(merged)


def sender_may_open(attempts: Sequence[datetime], *, now: datetime) -> bool:
    """Хватает ли отправителю дневного бюджета и прошла ли пауза после прошлого зачина."""
    if len(attempts) >= MAX_OPENERS_PER_DAY:
        return False
    return not attempts or now - max(attempts) >= MIN_OPENER_INTERVAL


def pick_partner(
    candidates: Sequence[UUID],
    recent_partners: Sequence[UUID],
    rng: random.Random,
) -> UUID | None:
    """Выбрать собеседника: чаще знакомого, иногда нового."""
    if not candidates:
        return None
    familiar = [p for p in candidates if p in set(recent_partners)]
    fresh = [p for p in candidates if p not in set(recent_partners)]
    if familiar and (not fresh or rng.random() < REPEAT_PARTNER_CHANCE):
        return rng.choice(familiar)
    return rng.choice(fresh or list(candidates))


def pick_opener(used: Collection[str], rng: random.Random) -> str:
    """Зачин, которого ещё не было; когда база исчерпана — самый давний повтор.

    ``used`` — уже отправленные тексты, от старых к новым. Часть фраз
    склеивается («привет, как дела?»), поэтому комбинаций заметно больше, чем
    записей в базе.
    """
    used_set = set(used)
    for _ in range(30):
        candidate = _compose(rng)
        if candidate not in used_set:
            return candidate
    unused = [o for o in OPENERS if o not in used_set]
    if unused:
        return humanize(rng.choice(unused), rng)
    # Всё перебрано: берём самый давно использованный.
    oldest = next((t for t in used if t in OPENERS), rng.choice(OPENERS))
    return humanize(oldest, rng)


def _compose(rng: random.Random) -> str:
    roll = rng.random()
    if roll < 0.25:
        text = f"{rng.choice(GREETINGS)}, {rng.choice(CHECK_INS)}"
    elif roll < 0.35:
        text = f"{rng.choice(GREETINGS)}, {rng.choice(QUESTIONS)}"
    else:
        text = rng.choice(OPENERS)
    return humanize(text, rng)


def humanize(text: str, rng: random.Random) -> str:
    """Небольшая небрежность набора: люди не пишут идеально."""
    if rng.random() < 0.6:
        text = text[:1].lower() + text[1:]
    if text.endswith(("?", ".")) and rng.random() < 0.35:
        text = text[:-1]
    return text


def reply_delay(rng: random.Random) -> float:
    """Секунды до ответа: люди отвечают не сразу, а когда дочитали и освободились.

    Чаще всего от четверти минуты до трёх, иногда несколько минут, изредка
    человек «отвлёкся» почти на час.
    """
    roll = rng.random()
    if roll < 0.65:
        return rng.uniform(15, 180)
    if roll < 0.93:
        return rng.uniform(180, 15 * 60)
    return rng.uniform(15 * 60, 50 * 60)


def dialog_length(rng: random.Random, *, recovery: bool = False) -> int:
    low, high = RECOVERY_DIALOG_LENGTH_RANGE if recovery else DIALOG_LENGTH_RANGE
    return rng.randint(low, high)


@dataclass
class Dialog:
    """Разговор двух мимиков: сколько сообщений позволено и сколько уже было."""

    length: int
    last_at: datetime
    count: int = 1
    """Зачин уже отправлен, он первое сообщение."""

    def is_over(self) -> bool:
        return self.count >= self.length


@dataclass
class DialogTracker:
    """Учёт открытых диалогов прогрева (в памяти процесса).

    После рестарта процесса записи нет, и входящее от другого мимика остаётся
    без ответа: разговор просто заканчивается, как это бывает у людей.
    """

    _dialogs: dict[frozenset[UUID], Dialog] = field(default_factory=dict)
    _history: dict[UUID, deque[UUID]] = field(default_factory=dict)

    def start(self, a: UUID, b: UUID, *, length: int, now: datetime) -> None:
        self._dialogs[frozenset((a, b))] = Dialog(length=length, last_at=now)
        for me, other in ((a, b), (b, a)):
            self._history.setdefault(me, deque(maxlen=20)).append(other)

    def drop(self, a: UUID, b: UUID) -> None:
        """Забыть диалог, который не состоялся (зачин не ушёл)."""
        self._dialogs.pop(frozenset((a, b)), None)

    def recent_partners(self, agent_id: UUID) -> list[UUID]:
        return list(self._history.get(agent_id, ()))

    def is_active(self, a: UUID, b: UUID, *, now: datetime) -> bool:
        dialog = self._dialogs.get(frozenset((a, b)))
        if dialog is None:
            return False
        if now - dialog.last_at > DIALOG_IDLE_TIMEOUT:
            del self._dialogs[frozenset((a, b))]
            return False
        return True

    def claim_reply(self, replier: UUID, other: UUID, *, now: datetime) -> bool:
        """Можно ли ``replier`` ответить ``other``; ответ сразу засчитывается в длину.

        Длина общая на обоих: диалог из N сообщений заканчивается после N-го,
        кто бы его ни написал.
        """
        if not self.is_active(replier, other, now=now):
            return False
        dialog = self._dialogs[frozenset((replier, other))]
        if dialog.is_over():
            return False
        dialog.count += 1
        dialog.last_at = now
        return True


# Фразы @SpamBot про «ограничений нет»; остальное, что похоже на ответ об ограничении,
# считается ограничением. Бот отвечает на языке аккаунта.
_SPAMBOT_FREE = (
    "no limits are currently applied",
    "free as a bird",
    "свободен от каких-либо ограничений",
    "ограничений нет",
)
_SPAMBOT_LIMITED = (
    "limited",
    "restricted",
    "ограничен",
    "ограничения",
    "you will be automatically released",
    "будет автоматически",
)


def classify_spambot_reply(text: str | None) -> bool | None:
    """True — ограничений нет, False — есть, None — ответ непонятен."""
    if not text:
        return None
    lowered = text.lower()
    if any(marker in lowered for marker in _SPAMBOT_FREE):
        return True
    if any(marker in lowered for marker in _SPAMBOT_LIMITED):
        return False
    return None
