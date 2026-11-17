"""Проверка дедупликации Telegram по random_id.

Тест отвечает на один вопрос: если повторить метод отправки с тем же
``random_id`` к тому же peer, Telegram вернёт уже созданное сообщение и не
создаст второе. От этого зависит вся идемпотентность recovery-пути атаки.

Проверяются три случая: текст, одна картинка и альбом из двух картинок.
``UploadMediaRequest`` сам сообщение не отправляет, поэтому он не проверяется
на дедупликацию. Все сообщения уходят в «Избранное» проверяющего и удаляются
в ``finally``.
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any, cast
from uuid import uuid4

import pytest
from PIL import Image
from telethon import TelegramClient, errors, functions, types, utils
from telethon.helpers import generate_random_long
from telethon.tl.types import MessageMediaPhoto, TypeInputMedia, TypeInputPeer

from mimic42.testing.real_tg.checker import Checker

pytestmark = pytest.mark.real_tg


def _png() -> bytes:
    image = Image.new("RGB", (8, 8), (180, 20, 20))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def _upload_photo(client: TelegramClient, entity: TypeInputPeer) -> TypeInputMedia:
    stream: Any = BytesIO(_png())
    stream.name = "photo.png"
    uploaded = await client.upload_file(stream)
    result = cast(
        MessageMediaPhoto,
        await client(
            functions.messages.UploadMediaRequest(
                peer=entity,
                media=types.InputMediaUploadedPhoto(uploaded),
            )
        ),
    )
    return utils.get_input_media(result.photo)


async def _messages_with_text(
    client: TelegramClient, entity: TypeInputPeer, text: str
) -> list[Any]:
    messages = cast("list[Any] | None", await client.get_messages(entity, limit=20))
    return [message for message in messages or [] if getattr(message, "message", "") == text]


async def _send_text(
    client: TelegramClient, entity: TypeInputPeer, text: str, random_id: int
) -> None:
    await client(
        functions.messages.SendMessageRequest(
            peer=entity,
            message=text,
            random_id=random_id,
        )
    )


async def _send_media(
    client: TelegramClient,
    entity: TypeInputPeer,
    media: TypeInputMedia,
    text: str,
    random_id: int,
) -> None:
    await client(
        functions.messages.SendMediaRequest(
            peer=entity,
            media=media,
            message=text,
            random_id=random_id,
        )
    )


async def _send_album(
    client: TelegramClient, entity: TypeInputPeer, items: list[types.InputSingleMedia]
) -> None:
    await client(
        functions.messages.SendMultiMediaRequest(
            peer=entity,
            multi_media=items,
        )
    )


async def test_random_id_dedupes_text(checker: Checker) -> None:
    client = checker.client
    entity = await client.get_input_entity("me")
    text = f"mimic42-random-text-{uuid4()}"
    random_id = generate_random_long()

    try:
        await _send_text(client, entity, text, random_id)
        try:
            await _send_text(client, entity, text, random_id)
        except errors.RandomIdDuplicateError:
            await asyncio.sleep(2)
            await _send_text(client, entity, text, random_id)

        await asyncio.sleep(1)
        messages = await _messages_with_text(client, entity, text)
        assert len(messages) == 1, f"ожидалось одно сообщение, получено {len(messages)}"
    finally:
        messages = await _messages_with_text(client, entity, text)
        if messages:
            await client.delete_messages(entity, [message.id for message in messages])


async def test_random_id_dedupes_photo(checker: Checker) -> None:
    client = checker.client
    entity = await client.get_input_entity("me")
    text = f"mimic42-random-photo-{uuid4()}"
    random_id = generate_random_long()

    media = await _upload_photo(client, entity)
    try:
        await _send_media(client, entity, media, text, random_id)
        try:
            await _send_media(client, entity, media, text, random_id)
        except errors.RandomIdDuplicateError:
            await asyncio.sleep(2)
            await _send_media(client, entity, media, text, random_id)

        await asyncio.sleep(1)
        messages = await _messages_with_text(client, entity, text)
        assert len(messages) == 1, f"ожидалось одно фото, получено {len(messages)}"
    finally:
        messages = await _messages_with_text(client, entity, text)
        if messages:
            await client.delete_messages(entity, [message.id for message in messages])


async def test_random_id_dedupes_album(checker: Checker) -> None:
    client = checker.client
    entity = await client.get_input_entity("me")
    text = f"mimic42-random-album-{uuid4()}"
    random_id = generate_random_long()

    first_photo = await _upload_photo(client, entity)
    second_photo = await _upload_photo(client, entity)
    items = [
        types.InputSingleMedia(
            first_photo,
            message=text,
            random_id=random_id,
        ),
        types.InputSingleMedia(
            second_photo,
            message="",
            random_id=random_id + 1,
        ),
    ]

    try:
        await _send_album(client, entity, items)
        try:
            await _send_album(client, entity, items)
        except errors.RandomIdDuplicateError:
            await asyncio.sleep(2)
            await _send_album(client, entity, items)

        await asyncio.sleep(1)
        messages = await _messages_with_text(client, entity, text)
        assert len(messages) == 1, f"ожидался один альбом, получено {len(messages)}"
        recent = cast("list[Any]", await client.get_messages(entity, limit=20))
        grouped_id = messages[0].grouped_id
        assert isinstance(grouped_id, int), "альбом не получил grouped_id"
        album_ids = [message.id for message in recent if message.grouped_id == grouped_id]
        assert len(album_ids) == 2, f"в альбоме {len(album_ids)} сообщений"
    finally:
        recent = cast("list[Any]", await client.get_messages(entity, limit=20))
        grouped = next((message.grouped_id for message in recent if message.message == text), None)
        album_ids = (
            [message.id for message in recent if message.grouped_id == grouped]
            if isinstance(grouped, int)
            else [message.id for message in recent if message.message == text]
        )
        if album_ids:
            await client.delete_messages(entity, album_ids)
