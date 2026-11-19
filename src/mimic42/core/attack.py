"""Домен атаки: типы, цель, контент, темп и классификация сбоев.

Правила кампании живут в одном модуле без сети, базы и рантайма: это позволяет
проверять их на голых значениях, не подделывая Telethon-клиент и хранилище.
Классы ошибок Telethon импортируются лениво внутри классификатора, поэтому
модуль импортируется и там, где Telethon не нужен.
"""

from __future__ import annotations

import asyncio
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal
from urllib.parse import SplitResult, parse_qs, urlsplit
from uuid import UUID

MAX_TEXT_WITH_MEDIA = 1024
MAX_TEXT = 4096
MAX_ATTACHMENTS = 10
MAX_TITLE_LENGTH = 200
DEFAULT_PAUSE_SECONDS = 10

_TELEGRAM_HOSTS = frozenset({"t.me", "www.t.me", "telegram.me", "www.telegram.me"})
_USERNAME = re.compile(r"[A-Za-z0-9_]+")
_PRIVATE_CHANNEL_PREFIX = "-100"


class AttackNotFoundError(LookupError):
    """Атаки или агента нет у владельца."""


class AttackVersionConflictError(RuntimeError):
    """Правка пришла со старой версией: между чтением и записью атаку изменили."""


class AttackStateError(RuntimeError):
    """Операция недопустима в текущем статусе атаки."""


class AttackStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    CANCELLED = "cancelled"
    FINISHED = "finished"


class AttackLimitType(StrEnum):
    MESSAGES = "messages"
    MINUTES = "minutes"


class AttackAgentStatus(StrEnum):
    ASSIGNED = "assigned"
    ACTIVE = "active"
    EXITED = "exited"


class AttackEndReason(StrEnum):
    LIMIT_REACHED = "limit_reached"
    DEADLINE = "deadline"
    CANCELLED_BY_USER = "cancelled_by_user"
    NO_AGENTS = "no_agents"
    ALL_BLOCKED = "all_blocked"
    TARGET_UNAVAILABLE = "target_unavailable"


class ExitReason(StrEnum):
    ATTACK_FINISHED = "attack_finished"
    ATTACK_CANCELLED = "attack_cancelled"
    PAUSED = "paused"
    MOVED = "moved"
    AGENT_STOPPED = "agent_stopped"
    AGENT_REMOVED = "agent_removed"
    PEER_FLOOD = "peer_flood"
    BANNED_IN_CHANNEL = "banned_in_channel"
    JOIN_BLOCKED = "join_blocked"
    SESSION_REVOKED = "session_revoked"
    START_FAILED = "start_failed"
    TARGET_UNAVAILABLE = "target_unavailable"
    SEND_FAILED = "send_failed"


class SendFailure(StrEnum):
    FLOOD_WAIT = "flood_wait"
    SLOW_MODE = "slow_mode"
    PEER_FLOOD = "peer_flood"
    BANNED_IN_CHANNEL = "banned_in_channel"
    JOIN_BLOCKED = "join_blocked"
    SESSION_REVOKED = "session_revoked"
    TARGET_UNAVAILABLE = "target_unavailable"
    TRANSIENT = "transient"
    MEDIA_STALE = "media_stale"
    SEND_FAILED = "send_failed"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class TargetRef:
    """Пост-цель в каноничном виде: ссылка, peer канала и номер сообщения."""

    link: str
    channel: str
    post_id: int


@dataclass(frozen=True)
class MessagesLimit:
    count: int


@dataclass(frozen=True)
class MinutesLimit:
    minutes: int


@dataclass(frozen=True)
class AttackConfig:
    title: str | None
    target: TargetRef
    texts: tuple[str, ...]
    media_paths: tuple[str, ...]
    limit: MessagesLimit | MinutesLimit

    @property
    def limit_type(self) -> AttackLimitType:
        """Тип лимита для колонки limit_type: вариант выражается типом, а не полем."""
        if isinstance(self.limit, MessagesLimit):
            return AttackLimitType.MESSAGES
        return AttackLimitType.MINUTES

    @property
    def limit_value(self) -> int:
        return self.limit.count if isinstance(self.limit, MessagesLimit) else self.limit.minutes


@dataclass(frozen=True)
class AttackPatch:
    """Правка атаки: ссылка неизменяема, поэтому её здесь нет.

    Храним полное редактируемое состояние, а не набор необязательных полей:
    форма всегда присылает все поля, и так нельзя случайно стереть очищенное
    название, приняв ``None`` за «не менять».
    """

    version: int
    title: str | None
    texts: tuple[str, ...]
    media_paths: tuple[str, ...]
    limit: MessagesLimit | MinutesLimit


@dataclass(frozen=True)
class CommentContent:
    text: str
    media: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.media) > MAX_ATTACHMENTS:
            raise ValueError(f"В одном комментарии не больше {MAX_ATTACHMENTS} картинок.")


@dataclass(frozen=True)
class SendOutcome:
    """Исход отправки: успех, известный отказ, неизвестность или прерывание.

    Неизвестный исход держит резерв и повторяется с тем же random_id; известный
    отказ освобождает слот. Разница в поведении счётчика, поэтому кодируется видом.
    """

    kind: Literal["sent", "not_sent", "unknown", "interrupted"]
    message_id: int | None = None
    failure: SendFailure | None = None
    delivered: int | None = None
    """Сколько сообщений реально дошло. None — весь заявленный набор."""

    @classmethod
    def sent(cls, message_id: int, delivered: int | None = None) -> SendOutcome:
        return cls(kind="sent", message_id=message_id, delivered=delivered)

    @classmethod
    def not_sent(cls, failure: SendFailure) -> SendOutcome:
        return cls(kind="not_sent", failure=failure)

    @classmethod
    def unknown(cls, failure: SendFailure) -> SendOutcome:
        return cls(kind="unknown", failure=failure)

    @classmethod
    def interrupted(cls) -> SendOutcome:
        return cls(kind="interrupted")


@dataclass(frozen=True)
class Settlement:
    sent_count: int
    claimed_count: int
    finished: bool
    end_reason: AttackEndReason | None


@dataclass(frozen=True)
class ParticipationView:
    id: UUID
    attack_id: UUID
    agent_id: UUID
    status: AttackAgentStatus
    sent_count: int
    next_at: datetime | None
    last_error: str | None
    exit_reason: ExitReason | None
    note_written_at: datetime | None


@dataclass(frozen=True)
class AttackView:
    id: UUID
    owner_id: UUID
    config: AttackConfig
    status: AttackStatus
    sent_count: int
    claimed_count: int
    version: int
    started_at: datetime | None
    finished_at: datetime | None
    end_reason: AttackEndReason | None
    participations: tuple[ParticipationView, ...]
    target_channel_id: int | None = None
    anchor_message_id: int | None = None
    slowmode_seconds: int | None = None
    deadline_at: datetime | None = None


@dataclass(frozen=True)
class SlotClaim:
    attack_id: UUID
    agent_id: UUID
    participation_id: UUID
    random_id: int
    text: str
    media: tuple[str, ...]
    message_count: int


def parse_target_link(link: str) -> TargetRef:
    """Разобрать ссылку на пост канала.

    Принимаются публичная форма ``t.me/<username>/<post>``, приватная
    ``t.me/c/<internal>/<post>`` и ``tg://resolve``. Хвост ``?single`` и
    ``?comment=`` относится к тому же посту, поэтому отбрасывается. Ссылка на
    канал без номера поста, приглашение и чужой хост не являются целью атаки.
    """
    raw = link.strip()
    if not raw:
        raise ValueError("Ссылка на пост не может быть пустой.")
    if "://" not in raw:
        raw = f"https://{raw}"
    split = urlsplit(raw)

    if split.scheme == "tg":
        return _parse_tg_link(split)
    if split.scheme not in {"http", "https"}:
        raise ValueError("Ссылка должна вести на t.me или tg://resolve.")
    if (split.hostname or "").lower() not in _TELEGRAM_HOSTS:
        raise ValueError("Ссылка должна вести на t.me.")
    return _parse_tme_path(split.path)


def _parse_tg_link(split: SplitResult) -> TargetRef:
    if split.netloc.lower() != "resolve":
        raise ValueError("Поддерживается только ссылка tg://resolve.")
    params = parse_qs(split.query)
    domain = params.get("domain", [""])[0].strip().lstrip("@")
    post = params.get("post", [""])[0].strip()
    return _build_ref(domain, post)


def _parse_tme_path(path: str) -> TargetRef:
    stripped = path.strip("/")
    parts = stripped.split("/") if stripped else []
    if len(parts) == 3 and parts[0] == "c":
        internal = parts[1]
        if not internal.isdigit():
            raise ValueError("В приватной ссылке t.me/c после c идёт числовой id канала.")
        return _build_ref(f"{_PRIVATE_CHANNEL_PREFIX}{internal}", parts[2], internal=internal)
    if len(parts) == 2 and parts[0] != "c":
        return _build_ref(parts[0], parts[1])
    raise ValueError("Ссылка должна указывать на пост канала, а не на канал целиком.")


def _build_ref(channel: str, post: str, *, internal: str | None = None) -> TargetRef:
    if internal is None and not _USERNAME.fullmatch(channel):
        raise ValueError("В ссылке нет имени канала.")
    if not post.isdigit():
        raise ValueError("Номер поста в ссылке должен быть положительным числом.")
    post_id = int(post)
    if post_id <= 0:
        raise ValueError("Номер поста в ссылке должен быть положительным числом.")
    path = f"c/{internal}/{post_id}" if internal is not None else f"{channel}/{post_id}"
    return TargetRef(link=f"https://t.me/{path}", channel=channel, post_id=post_id)


def validate_config(config: AttackConfig) -> None:
    """Проверить конфиг до записи в базу.

    Длины зависят от наличия картинок: подпись к медиа Telegram режет на 1024
    символах, а обычное сообщение на 4096. Лимит проверяется здесь же, потому
    что база принимает только положительное значение, а форма обязана ответить
    понятной ошибкой до вставки.
    """
    if not isinstance(config.limit, (MessagesLimit, MinutesLimit)):
        raise ValueError("Лимит атаки задаётся либо сообщениями, либо минутами.")
    if config.limit_value <= 0:
        raise ValueError("Лимит атаки должен быть больше нуля.")
    if config.title is not None and _text_length(config.title) > MAX_TITLE_LENGTH:
        raise ValueError(f"Название атаки длиннее {MAX_TITLE_LENGTH} символов.")
    if not config.texts:
        raise ValueError("У атаки должен быть хотя бы один текст.")
    for path in config.media_paths:
        if not path.strip():
            raise ValueError("Путь к картинке не может быть пустым.")

    limit = MAX_TEXT_WITH_MEDIA if config.media_paths else MAX_TEXT
    for text in config.texts:
        if not text.strip():
            raise ValueError("Текст комментария не может быть пустым.")
        if _text_length(text) > limit:
            raise ValueError(f"Текст длиннее {limit} символов.")


def _text_length(text: str) -> int:
    """Длина в единицах Telegram: эмодзи занимает две, как в браузере.

    Фронтенд меряет строку через ``length``, то есть в UTF-16. Если считать
    кодовые точки Python, форма пропустит текст, который сервер потом отклонит.
    """
    return len(text.encode("utf-16-le")) // 2


def compose_comment(
    texts: Sequence[str], media_paths: Sequence[str], rng: random.Random
) -> CommentContent:
    """Собрать комментарий по правилам R34-R39.

    Текст берётся случайно с повторами. Пул до 10 картинок входит целиком в
    случайном порядке (перестановка); больший пул даёт 10 разных картинок
    (размещение). Повтор между комментариями возможен, внутри одного — нет.
    """
    text = rng.choice(texts)
    if len(media_paths) <= MAX_ATTACHMENTS:
        media = tuple(rng.sample(media_paths, len(media_paths)))
    else:
        media = tuple(rng.sample(media_paths, MAX_ATTACHMENTS))
    return CommentContent(text=text, media=media)


def base_pause(slow_mode_seconds: int | None) -> int:
    """База паузы между комментариями.

    10 секунд — не нижняя граница для любого slow mode, а замена отсутствующего:
    если группа разрешает писать чаще, мимик не обязан ждать дольше (R47-R48).
    """
    if isinstance(slow_mode_seconds, int) and slow_mode_seconds > 0:
        return slow_mode_seconds
    return DEFAULT_PAUSE_SECONDS


def next_send_at(
    now: datetime,
    slow_mode_seconds: int | None,
    rng: random.Random,
    failure: SendFailure | None = None,
    *,
    retry_after: int | None = None,
) -> datetime:
    """Когда можно отправлять следующий комментарий.

    К базе добавляется разброс 15-45%: одинаковые интервалы выдают бота. Разброс
    только увеличивает паузу (R49). Ожидание из FloodWait или SlowModeWait важнее
    базы (R54) и приходит отдельным retry_after, потому что его знает исключение.
    """
    base = float(base_pause(slow_mode_seconds))
    if failure in (SendFailure.FLOOD_WAIT, SendFailure.SLOW_MODE):
        if isinstance(retry_after, int) and retry_after > 0:
            base = max(base, float(retry_after))
    return now + timedelta(seconds=base * (1.0 + rng.uniform(0.15, 0.45)))


def typing_delay(text: str, rng: random.Random) -> float:
    """Сколько «печатать» перед комментарием.

    Та же формула, что у обычной отправки: длина текста задаёт темп, границы не
    дают мгновенному короткому и бесконечному длинному тексту выдать автоматику.
    """
    base = min(max(len(text) * 0.07, 0.8), 15.0)
    return base + rng.uniform(0.2, 1.2)


def initial_offset(slow_mode_seconds: int | None, rng: random.Random) -> float:
    """Сдвиг первой отправки внутри базы, чтобы мимики не стартовали залпом (R52)."""
    return rng.uniform(0.0, float(base_pause(slow_mode_seconds)))


def classify_send_error(exc: BaseException) -> SendFailure:
    """Свести исключение отправки к одному классу.

    От этого класса зависит, освобождается ли слот и выходит ли мимик из атаки,
    поэтому соответствие собрано в одном месте. Импорт Telethon ленивый:
    домен проверяется и без него.
    """
    from telethon import errors

    if isinstance(exc, (errors.FloodWaitError, errors.FloodPremiumWaitError)):
        return SendFailure.FLOOD_WAIT
    if isinstance(exc, errors.SlowModeWaitError):
        return SendFailure.SLOW_MODE
    if isinstance(exc, errors.RandomIdDuplicateError):
        return SendFailure.DUPLICATE
    if isinstance(exc, errors.PeerFloodError):
        return SendFailure.PEER_FLOOD
    if isinstance(
        exc,
        (
            errors.UserBannedInChannelError,
            errors.UserRestrictedError,
            errors.ChatWriteForbiddenError,
            errors.ChatRestrictedError,
        ),
    ):
        return SendFailure.BANNED_IN_CHANNEL
    if isinstance(
        exc,
        (errors.UserNotParticipantError, errors.ChatAdminRequiredError, errors.ChannelPrivateError),
    ):
        return SendFailure.JOIN_BLOCKED
    if isinstance(exc, errors.MsgIdInvalidError):
        return SendFailure.TARGET_UNAVAILABLE
    if isinstance(
        exc,
        (
            errors.AuthKeyUnregisteredError,
            errors.SessionRevokedError,
            errors.UserDeactivatedError,
        ),
    ):
        return SendFailure.SESSION_REVOKED
    if isinstance(
        exc,
        (
            errors.FileReferenceExpiredError,
            errors.FileReferenceInvalidError,
            errors.FileReferenceEmptyError,
        ),
    ):
        return SendFailure.MEDIA_STALE
    if isinstance(exc, OSError):
        return SendFailure.TRANSIENT
    if isinstance(exc, errors.TimedOutError):
        return SendFailure.TRANSIENT
    if isinstance(exc, errors.ServerError):
        return SendFailure.TRANSIENT
    if isinstance(exc, errors.RPCError):
        return SendFailure.SEND_FAILED
    return SendFailure.TRANSIENT


def classify_outcome(exc: BaseException) -> SendOutcome:
    """Исход для счётчика: неизвестность держит слот, известный отказ освобождает.

    Отмена и прерывание не отправка, а остановка: комментарий мог уйти, но
    повторить его вслепую нельзя, поэтому исход отдельный.
    """
    if isinstance(exc, asyncio.CancelledError):
        return SendOutcome.interrupted()
    failure = classify_send_error(exc)
    if failure in (SendFailure.TRANSIENT, SendFailure.DUPLICATE):
        return SendOutcome.unknown(failure)
    return SendOutcome.not_sent(failure)


_FAILURE_LABELS: dict[SendFailure, str] = {
    SendFailure.FLOOD_WAIT: "Telegram просит подождать (FloodWait)",
    SendFailure.SLOW_MODE: "окно slow mode обсуждения",
    SendFailure.PEER_FLOOD: "Telegram ограничил аккаунт (PeerFlood)",
    SendFailure.BANNED_IN_CHANNEL: "запрет писать в обсуждении",
    SendFailure.JOIN_BLOCKED: "не удалось вступить в обсуждение",
    SendFailure.SESSION_REVOKED: "сессия Telegram отозвана",
    SendFailure.TARGET_UNAVAILABLE: "пост или обсуждение недоступны",
    SendFailure.TRANSIENT: "обрыв сети или таймаут",
    SendFailure.MEDIA_STALE: "картинка устарела на сервере",
    SendFailure.SEND_FAILED: "отправка не удалась",
    SendFailure.DUPLICATE: "повтор отправки ещё в полёте",
}


def failure_text(failure: SendFailure) -> str:
    """Текст ошибки для карточки участия (R84): класс сбоя без сырого стека."""
    return _FAILURE_LABELS[failure]


_EXIT_LABELS: dict[ExitReason, str] = {
    ExitReason.ATTACK_FINISHED: "атака завершена",
    ExitReason.ATTACK_CANCELLED: "атака отменена",
    ExitReason.PAUSED: "пауза",
    ExitReason.MOVED: "перенос в другую атаку",
    ExitReason.AGENT_STOPPED: "агент остановлен",
    ExitReason.AGENT_REMOVED: "агент удалён",
    ExitReason.PEER_FLOOD: "Telegram ограничил аккаунт (PeerFlood)",
    ExitReason.BANNED_IN_CHANNEL: "запрет писать в обсуждении",
    ExitReason.JOIN_BLOCKED: "не удалось вступить в обсуждение",
    ExitReason.SESSION_REVOKED: "сессия Telegram отозвана",
    ExitReason.START_FAILED: "не удалось запустить агента",
    ExitReason.TARGET_UNAVAILABLE: "пост или обсуждение недоступны",
    ExitReason.SEND_FAILED: "отправка не удалась",
}

_END_LABELS: dict[AttackEndReason, str] = {
    AttackEndReason.LIMIT_REACHED: "лимит достигнут",
    AttackEndReason.DEADLINE: "истёк срок атаки",
    AttackEndReason.CANCELLED_BY_USER: "атака отменена пользователем",
    AttackEndReason.NO_AGENTS: "в атаке не осталось мимиков",
    AttackEndReason.ALL_BLOCKED: "все мимики ограничены",
    AttackEndReason.TARGET_UNAVAILABLE: "пост или обсуждение недоступны",
}


def note_text(attack: AttackView, participation: ParticipationView) -> str:
    """Детерминированная заметка в контекст после выхода из атаки (R73-R76).

    Одинаковый вход даёт одинаковый текст: повторная запись после сбоя не создаёт
    в памяти вторую версию события. Заметка не отправляется в Telegram и не
    считается комментарием.
    """
    title = f" «{attack.config.title}»" if attack.config.title else ""
    reason = participation.exit_reason or attack.end_reason
    if isinstance(reason, ExitReason):
        label = _EXIT_LABELS[reason]
    elif isinstance(reason, AttackEndReason):
        label = _END_LABELS[reason]
    else:
        label = "причина не указана"
    return (
        f"Участие в атаке{title}: комментарии под постом {attack.config.target.link}. "
        f"Отправлено сообщений: {participation.sent_count}. "
        f"Причина выхода: {label}."
    )


_ATTACK_TRANSITIONS: dict[AttackStatus, frozenset[AttackStatus]] = {
    AttackStatus.DRAFT: frozenset({AttackStatus.RUNNING, AttackStatus.CANCELLED}),
    AttackStatus.RUNNING: frozenset({AttackStatus.FINISHED, AttackStatus.CANCELLED}),
    AttackStatus.FINISHED: frozenset(),
    AttackStatus.CANCELLED: frozenset(),
}


def can_transition(status: AttackStatus, to: AttackStatus) -> bool:
    """Разрешён ли переход атаки.

    Повтор того же статуса разрешён: guarded-переходы сервиса идемпотентны, и
    второй cancel или finalize не должен падать, а сходится в то же состояние.
    """
    if status == to:
        return True
    return to in _ATTACK_TRANSITIONS[status]


def attack_end_reason(
    limit_type: AttackLimitType,
    limit_value: int,
    deadline_at: datetime | None,
    sent_count: int,
    claimed_count: int,
    now: datetime,
) -> AttackEndReason | None:
    """Пора ли завершать идущую атаку после очередного settle.

    Пока есть резервы (``claimed_count > sent_count``), атака ждёт их: снижение
    лимита не должно обрывать отправки в полёте. Лимит сообщений сравнивается
    через ``>=``, поэтому правка лимита ниже уже отправленного завершает
    кампанию, как только резервы осядут.
    """
    if claimed_count != sent_count:
        return None
    if limit_type is AttackLimitType.MESSAGES and sent_count >= limit_value:
        return AttackEndReason.LIMIT_REACHED
    if limit_type is AttackLimitType.MINUTES and deadline_at is not None and deadline_at <= now:
        return AttackEndReason.DEADLINE
    return None
