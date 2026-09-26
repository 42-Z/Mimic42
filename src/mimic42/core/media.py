from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

MAX_MEDIA_BYTES = 20 * 1024 * 1024
# Предел Telegram для фото: больше уйдёт только документом, а не картинкой.
MAX_PHOTO_BYTES = 10 * 1024 * 1024

# Форматы, которые Telethon шлёт фотографией (`telethon.utils.is_image`
# смотрит на расширение): Pillow-формат → (mime, расширение).
_PHOTO_FORMATS = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png")}

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME = 120


def safe_filename(name: str) -> str:
    """Привести имя файла к виду, безопасному для URL-пути Storage.

    supabase-py подставляет ключ объекта в URL без квотирования: ``#``/``?``
    обрежут путь, пробелы и юникод ломают загрузку/скачивание, а ``..`` даёт
    выход из «папки» агента. Оставляем только ASCII-буквы, цифры, точку,
    дефис и подчёркивание; расширение по возможности сохраняем.
    """
    base = (name or "").strip().replace("\\", "_")
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", base).strip("._") or "file"
    if len(cleaned) <= _MAX_FILENAME:
        return cleaned
    stem, dot, ext = cleaned.rpartition(".")
    if dot and len(ext) <= 10:
        return f"{stem[: _MAX_FILENAME - len(ext) - 1]}.{ext}"
    return cleaned[:_MAX_FILENAME]


def detect_photo_type(data: bytes) -> tuple[str, str] | None:
    """(mime, расширение) по содержимому файла, ``None`` — не JPEG и не PNG.

    Заявленному клиентом типу верить нельзя: под видом картинки придёт что
    угодно, и Telethon отправит это документом на каждый пост. Pillow
    читает заголовок и проверяет целостность, не декодируя всё изображение.
    """
    from io import BytesIO

    from PIL import Image

    try:
        with Image.open(BytesIO(data), formats=list(_PHOTO_FORMATS)) as image:
            image_format = image.format
            image.verify()
    except Exception:
        # verify() сообщает о битом файле разными исключениями — любое значит «не фото».
        return None
    return _PHOTO_FORMATS.get(image_format or "")


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
