from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from telethon import errors, types

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
    mime_type: str | None = None
    attributes: tuple[types.DocumentAttributeAudio | types.DocumentAttributeVideo, ...] = ()
    download_source: Any | None = field(default=None, repr=False, compare=False)

    def as_payload(self) -> dict[str, Any]:
        """JSON metadata only; the refreshed Telethon object stays in memory."""
        payload: dict[str, Any] = {}
        for key in ("peer", "message_id", "storage_path", "mime_type"):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.attributes:
            attributes = []
            for attribute in self.attributes:
                data = attribute.to_dict()
                waveform = data.get("waveform")
                if isinstance(waveform, bytes):
                    data["waveform"] = waveform.hex()
                attributes.append(data)
            payload["attributes"] = attributes
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> MediaRef:
        """Restore archive coordinates and Telegram audio/video metadata."""
        attribute_types = {
            "DocumentAttributeAudio": types.DocumentAttributeAudio,
            "DocumentAttributeVideo": types.DocumentAttributeVideo,
        }
        attributes = []
        entries = payload.get("attributes")
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            data = entry.copy()
            name = data.pop("_", "")
            constructor = attribute_types.get(name) if isinstance(name, str) else None
            if constructor is None:
                continue
            try:
                if isinstance(data.get("waveform"), str):
                    data["waveform"] = bytes.fromhex(data["waveform"])
                attributes.append(constructor(**data))
            except (TypeError, ValueError):
                continue
        peer = payload.get("peer")
        message_id = payload.get("message_id")
        storage_path = payload.get("storage_path")
        mime_type = payload.get("mime_type")
        return cls(
            peer=peer if type(peer) in (str, int) else None,
            message_id=message_id if type(message_id) is int else None,
            storage_path=storage_path if isinstance(storage_path, str) and storage_path else None,
            mime_type=mime_type if isinstance(mime_type, str) and mime_type else None,
            attributes=tuple(attributes),
        )

    def merged_with(self, ref: MediaRef) -> MediaRef:
        """Keep message coordinates together and retain known archive metadata."""
        peer, message_id = (
            (ref.peer, ref.message_id)
            if ref.peer is not None and ref.message_id is not None
            else (self.peer, self.message_id)
        )
        return MediaRef(
            peer=peer,
            message_id=message_id,
            storage_path=ref.storage_path or self.storage_path,
            mime_type=ref.mime_type or self.mime_type,
            attributes=ref.attributes or self.attributes,
            download_source=(
                ref.download_source if ref.download_source is not None else self.download_source
            ),
        )

    @classmethod
    def from_message(
        cls, message: Any, *, peer: str | int | None = None, message_id: int | None = None
    ) -> MediaRef:
        """Keep original document metadata needed to upload an archived copy."""
        media = getattr(message, "media", None)
        document = media.document if isinstance(media, types.MessageMediaDocument) else None
        if not isinstance(document, types.Document):
            return cls(peer=peer, message_id=message_id)
        attributes = tuple(
            attr
            for attr in document.attributes
            if isinstance(attr, (types.DocumentAttributeAudio, types.DocumentAttributeVideo))
        )
        return cls(
            peer=peer,
            message_id=message_id,
            mime_type=document.mime_type,
            attributes=attributes,
        )


class MediaRefCache:
    """Кеш media_id → MediaRef (LRU), общий для тулзов и рантайма.

    Тулзы скачивают медиа по media_id, в который запечён file_reference
    момента чтения; без сообщения и архивной копии протухшую ссылку
    обновить нечем. Рантайм запоминает сообщение и путь в Storage при
    получении, тулзы — при чтении истории.

    Кеш живёт в одном event loop, поэтому lock не нужен. После рестарта
    архивные ссылки восстанавливаются из payload сообщений и событий БД.
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
            ref = existing.merged_with(ref)
        self._entries[media_id] = ref
        self._entries.move_to_end(media_id)
        while len(self._entries) > self._capacity:
            # Message references can be recovered from Telegram; TTL media
            # whose only surviving copy is in Storage cannot.
            victim = next(
                (
                    key
                    for key, value in self._entries.items()
                    if key != media_id and not value.storage_path
                ),
                next((key for key in self._entries if key != media_id), media_id),
            )
            del self._entries[victim]

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
    if file is bytes:
        return
    seek = getattr(file, "seek", None)
    truncate = getattr(file, "truncate", None)
    if not callable(seek) or not callable(truncate):
        raise OSError("Повторная загрузка требует потока с seek и truncate")
    try:
        seek(0)
        truncate()
    except (OSError, ValueError) as exc:
        # Retrying into a dirty, non-seekable stream would corrupt bytes.
        raise OSError("Не удалось подготовить поток для повторной загрузки") from exc


async def _refetch_message(client: Any, message_ref: tuple[Any, int] | None) -> Any | None:
    """Перечитать сообщение, чтобы получить свежий file_reference."""
    if message_ref is None:
        return None
    chat, msg_id = message_ref
    message = await client.get_messages(chat, ids=msg_id)
    if message is None or getattr(message, "media", None) is None:
        return None
    return message


def _media_object_identity(obj: Any) -> tuple[str, int] | None:
    """Вид и id объекта внутри сообщения либо объекта, восстановленного из media_id."""
    inner = getattr(obj, "media", None) or obj
    if isinstance(inner, types.MessageMediaPhoto):
        carrier, kind = inner.photo, "photo"
    elif isinstance(inner, types.MessageMediaDocument):
        carrier, kind = inner.document, "document"
    elif isinstance(inner, (types.Photo, types.InputPhoto)):
        carrier, kind = inner, "photo"
    elif isinstance(inner, (types.Document, types.InputDocument)):
        carrier, kind = inner, "document"
    else:
        return None
    obj_id = getattr(carrier, "id", None)
    return (kind, obj_id) if isinstance(obj_id, int) else None


async def download_media_with_refresh(
    client: Any,
    media: Any,
    *,
    message_ref: tuple[Any, int] | None = None,
    file: Any = bytes,
    on_refresh: Callable[[Any], None] | None = None,
) -> Any:
    """Скачать медиа, при протухшей ссылке — перечитав сообщение.

    Передаём media, а не Message: иначе Telethon сам обновляет документы
    внутри download_media, не возвращая свежий объект в наш кеш.
    """
    try:
        return await client.download_media(getattr(media, "media", None) or media, file=file)
    except RETRYABLE_DOWNLOAD_ERRORS as exc:
        fresh = await _refetch_message(client, message_ref)
        original_id = _media_object_identity(media)
        fresh_id = _media_object_identity(fresh) if fresh is not None else None
        if fresh is None:
            raise MediaUnavailableError() from exc
        if original_id is not None and fresh_id != original_id:
            # Сообщение отредактировали: под старый media_id чужое медиа
            # не подсовываем (так же проверяет и Telethon).
            raise MediaUnavailableError() from exc
        _rewind(file)
        try:
            result = await client.download_media(fresh.media, file=file)
        except RETRYABLE_DOWNLOAD_ERRORS as retry_exc:
            raise MediaUnavailableError() from retry_exc
        if on_refresh is not None and result:
            on_refresh(fresh)
        return result
