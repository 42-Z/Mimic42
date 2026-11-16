"""Общие помощники загрузки картинок из форм дашборда."""

from __future__ import annotations

from fastapi import UploadFile

from mimic42.core.media import safe_filename

_UPLOAD_CHUNK_BYTES = 1024 * 1024


def image_filename(filename: str | None, extension: str) -> str:
    """Имя с расширением настоящего формата: по нему Telethon решает, фото это или файл."""
    base = (filename or "").strip()
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return f"{stem or 'image'}.{extension}"


def safe_upload_name(filename: str | None, extension: str) -> str:
    """Имя, которое Storage сохранит фотографией.

    ``safe_filename`` выбрасывает не-ASCII основу имени и у «картинка.png»
    оставляет голое ``png`` без точки: Telethon по такому имени отправил бы
    файл документом. Поэтому пустая основа заменяется на ``image``.
    """
    safe = safe_filename(image_filename(filename, extension))
    if "." not in safe:
        return f"image.{extension}"
    return safe


async def read_limited_upload(file: UploadFile, limit: int) -> bytes | None:
    """Прочитать загрузку порциями; ``None`` — файл больше ``limit``.

    Целиком в память не читаем: размер клиент может не прислать или соврать.
    """
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(_UPLOAD_CHUNK_BYTES):
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)
