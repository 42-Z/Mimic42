from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from telethon import errors

logger = logging.getLogger("mimic42.media")

__all__ = [
    "FILE_REFERENCE_ERRORS",
    "RETRYABLE_DOWNLOAD_ERRORS",
    "UNAVAILABLE_MARKER_TEXT",
    "UNAVAILABLE_TEXT",
    "MediaRef",
    "MediaRefCache",
    "MediaUnavailableError",
    "download_media_with_refresh",
    "normalize_peer_ref",
]

# Telegram шлёт их, когда file_reference внутри объекта протух: так случается
# с media_id, запечёнными при чтении сообщения, и со старыми сообщениями.
# Файл самоуничтожающегося медиа Telegram отдаёт ту же ошибку — повторное
# скачивание после первого просмотра невозможно в принципе.
FILE_REFERENCE_ERRORS: tuple[type[BaseException], ...] = (
    errors.FileReferenceExpiredError,
    errors.FileReferenceInvalidError,
    errors.FileReferenceEmptyError,
    errors.FilerefUpgradeNeededError,
)

# Медиа нет вовсе (или оно заменено) — перечитывание сообщения тоже может помочь.
RETRYABLE_DOWNLOAD_ERRORS: tuple[type[BaseException], ...] = FILE_REFERENCE_ERRORS + (
    errors.MediaEmptyError,
)

UNAVAILABLE_TEXT = "Медиа больше недоступно: ссылка на файл устарела или файл самоуничтожился"

# Короткий вариант для маркеров в тексте, который видит LLM.
UNAVAILABLE_MARKER_TEXT = "недоступно: ссылка устарела или медиа самоуничтожилось"


class MediaUnavailableError(Exception):
    """Медиа не скачать: ссылка на файл протухла или файл самоуничтожился."""

    def __init__(self, reason: str = UNAVAILABLE_TEXT) -> None:
        super().__init__(reason)


@dataclass(frozen=True)
class MediaRef:
    """Где найти свежую ссылку на файл и уже заархивированную копию медиа."""

    peer: str | int | None = None
    message_id: int | None = None
    storage_path: str | None = None


class MediaRefCache:
    """Кеш media_id → MediaRef (LRU), общий для тулзов и рантайма.

    Тулзы скачивают медиа по media_id, в который запечён file_reference
    момента чтения; без сообщения и архивной копии протухшую ссылку
    обновить нечем. Рантайм запоминает сообщение и путь в Storage при
    получении, тулзы — при чтении истории.

    Предположения: кеш живёт в памяти процесса и в одном event loop
    (память о медиа из прошлых запусков теряется — пока это осознанное
    ограничение), многопоточности нет, поэтому lock не нужен.
    """

    def __init__(self, capacity: int = 512) -> None:
        self._capacity = capacity
        self._entries: OrderedDict[str, MediaRef] = OrderedDict()

    def remember(self, media_id: str, ref: MediaRef) -> None:
        """Запомнить ссылку, не теряя уже известное: повторные регистрации
        (получение, чтение истории, просмотр) дополняют запись, а не
        затирают её — иначе архивная копия «исчезает» после get_messages."""
        if not media_id:
            return
        existing = self._entries.get(media_id)
        if existing is not None:
            ref = MediaRef(
                peer=ref.peer if ref.peer is not None else existing.peer,
                message_id=ref.message_id if ref.message_id is not None else existing.message_id,
                storage_path=ref.storage_path or existing.storage_path,
            )
        self._entries[media_id] = ref
        self._entries.move_to_end(media_id)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def lookup(self, media_id: str) -> MediaRef | None:
        ref = self._entries.get(media_id)
        if ref is not None:
            self._entries.move_to_end(media_id)
        return ref


def normalize_peer_ref(peer: Any) -> Any:
    """Нормализовать адрес чата, чтобы сообщение можно было перечитать.

    Числовые строки становятся int (так их понимает get_messages),
    "username#123" — 123 (id после #, как в _resolve_peer), прочее —
    строка без лишних пробелов.
    """
    if not isinstance(peer, str):
        return peer
    value = peer.split("#", 1)[-1].strip()
    if value.lstrip("-").isdigit():
        return int(value)
    return value


def _rewind(file: Any) -> None:
    """Подготовить поток к повторной записи после неудачной попытки."""
    seek = getattr(file, "seek", None)
    truncate = getattr(file, "truncate", None)
    if callable(seek) and callable(truncate):
        seek(0)
        truncate()


async def _refetch_message(client: Any, message_ref: tuple[Any, int] | None) -> Any | None:
    """Перечитать сообщение, чтобы получить свежий file_reference."""
    if message_ref is None:
        return None
    chat, msg_id = message_ref
    try:
        message = await client.get_messages(chat, ids=msg_id)
    except Exception:
        logger.warning("Failed to refetch message %s in %s", msg_id, chat, exc_info=True)
        return None
    if message is None or getattr(message, "media", None) is None:
        return None
    return message


def _media_object_id(obj: Any) -> int | None:
    """Id объекта (фото/документа) внутри сообщения или самого объекта."""
    inner = getattr(obj, "media", None) or obj
    carrier = getattr(inner, "photo", None) or getattr(inner, "document", None) or inner
    obj_id = getattr(carrier, "id", None)
    return obj_id if isinstance(obj_id, int) else None


async def download_media_with_refresh(
    client: Any,
    media: Any,
    *,
    message_ref: tuple[Any, int] | None = None,
    file: Any = bytes,
) -> Any:
    """Скачать медиа, при протухшей ссылке — перечитав сообщение.

    Telethon сам обновляет file_reference только для документов,
    скачиваемых из Message (см. telethon.client.downloads), а фото и
    объекты, восстановленные из media_id, падают с FileReferenceExpired.
    """
    try:
        return await client.download_media(media, file=file)
    except RETRYABLE_DOWNLOAD_ERRORS as exc:
        fresh = await _refetch_message(client, message_ref)
        original_id = _media_object_id(media)
        fresh_id = _media_object_id(fresh) if fresh is not None else None
        if fresh is None:
            raise MediaUnavailableError() from exc
        if original_id is not None and fresh_id is not None and fresh_id != original_id:
            # Сообщение отредактировали: под старый media_id чужое медиа
            # не подсовываем (так же проверяет и Telethon).
            raise MediaUnavailableError() from exc
        _rewind(file)
        try:
            return await client.download_media(fresh, file=file)
        except RETRYABLE_DOWNLOAD_ERRORS as retry_exc:
            raise MediaUnavailableError() from retry_exc
