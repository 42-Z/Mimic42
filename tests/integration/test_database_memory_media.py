from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import types

from mimic42.core.activity import ActivityRecorder
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.media import MediaFile
from mimic42.core.media_download import MediaRef
from mimic42.core.memory import TurnInput
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.integrations.database_memory import DatabaseShortTermMemory
from mimic42.integrations.database_models import (
    AgentEventModel,
    AgentMessageModel,
    AgentModel,
    MessageThreadModel,
)
from mimic42.integrations.telegram_tools import TelegramToolbox
from mimic42.testing.slots import Slot

MEDIA = [
    {
        "kind": "photo",
        "name": "photo.jpeg",
        "mime_type": "image/jpeg",
        "size": 3,
        "storage_path": "00000000-0000-0000-0000-000000000000/u1/photo.jpeg",
    },
]

REPLY = {"message_id": 42, "preview": "предыдущее сообщение"}


async def _create_agent(
    db_session_factory: async_sessionmaker[AsyncSession], owner_id: UUID
) -> UUID:
    agent_id = uuid4()
    async with db_session_factory() as session:
        session.add(
            AgentModel(
                id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                status=AgentRuntimeState.STOPPED.value,
                soul_prompt="Soul",
            )
        )
        await session.commit()
    return agent_id


async def test_save_input_attaches_media_to_incoming_row(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    agent_id = await _create_agent(db_session_factory, owner_id)
    store = DatabaseShortTermMemory(db_session_factory)

    turn_id = str(uuid4())
    await store.save_input(
        TurnInput(
            agent_id=agent_id,
            peer="12345",
            text="[Сообщение] Привет",
            raw_text="Привет",
            peer_name="Ivan",
            turn_id=turn_id,
            created_at=datetime.now(UTC),
            media=MEDIA,
            reply=REPLY,
        )
    )

    async with db_session_factory() as session:
        row = await session.scalar(
            select(AgentMessageModel)
            .where(AgentMessageModel.agent_id == agent_id)
            .where(AgentMessageModel.direction == "incoming")
            .order_by(AgentMessageModel.created_at.desc())
            .limit(1)
        )
        assert row is not None
        assert row.content == "Привет"
        assert row.payload.get("media") == MEDIA
        assert row.payload.get("reply") == REPLY
        assert row.payload.get("turn_id") == turn_id
        assert row.id == UUID(turn_id)


async def test_save_input_is_idempotent_and_preserves_media(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    agent_id = await _create_agent(db_session_factory, owner_id)
    store = DatabaseShortTermMemory(db_session_factory)
    incoming = TurnInput(
        agent_id=agent_id,
        peer="12345",
        text="Привет",
        raw_text="Привет",
        turn_id=str(uuid4()),
        created_at=datetime.now(UTC),
        media=MEDIA,
    )
    await store.save_input(incoming)
    await store.save_input(incoming)

    async with db_session_factory() as session:
        rows = list(
            await session.scalars(
                select(AgentMessageModel)
                .where(AgentMessageModel.agent_id == agent_id)
                .where(AgentMessageModel.direction == "incoming")
                .order_by(AgentMessageModel.created_at.asc())
            )
        )
        assert len(rows) == 1
        assert rows[0].payload.get("media") == MEDIA


async def test_save_messages_does_not_duplicate_explicit_raw_input(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Форматированный human в messages не должен дублировать raw-строку:
    две incoming-строки в одном turn_id ломают ленту (одинаковые id блоков)."""
    owner_id = clean_slot.persona("twofa").user_id
    agent_id = await _create_agent(db_session_factory, owner_id)
    store = DatabaseShortTermMemory(db_session_factory)
    formatted = "[Входящее сообщение]\nСодержимое: Привет"
    turn_id = str(uuid4())
    await store.save_input(
        TurnInput(
            agent_id=agent_id,
            peer="12345",
            text=formatted,
            raw_text="Привет",
            turn_id=turn_id,
            created_at=datetime.now(UTC),
        )
    )

    await store.save_messages(
        agent_id=agent_id,
        peer="12345",
        messages=[
            {"role": "user", "content": formatted},
            {"role": "assistant", "content": "Ответ"},
        ],
        turn_id=turn_id,
    )

    async with db_session_factory() as session:
        rows = list(
            await session.scalars(
                select(AgentMessageModel)
                .where(AgentMessageModel.agent_id == agent_id)
                .where(AgentMessageModel.direction == "incoming")
            )
        )
        assert len(rows) == 1
        assert rows[0].content == "Привет"
    assert rows[0].payload.get("turn_id") == turn_id


@pytest.mark.parametrize("raw_text", ["caption", "", " \n "])
async def test_input_preserves_thread_names_and_media_with_display_fallback(
    db_session_factory: async_sessionmaker[AsyncSession], clean_slot: Slot, raw_text: str
) -> None:
    agent_id = await _create_agent(db_session_factory, clean_slot.persona("twofa").user_id)
    thread_id = uuid4()
    async with db_session_factory() as session:
        session.add(MessageThreadModel(id=thread_id, agent_id=agent_id, telegram_peer_id="12345"))
        await session.commit()
    turn_id = str(uuid4())
    await DatabaseShortTermMemory(db_session_factory).save_input(
        TurnInput(
            agent_id=agent_id,
            turn_id=turn_id,
            peer="12345",
            text="[Фото] enriched prompt",
            raw_text=raw_text,
            created_at=datetime.now(UTC),
            thread_id=thread_id,
            peer_name="Partner",
            agent_name="Mimic",
            media=MEDIA,
            reply=REPLY,
        )
    )
    async with db_session_factory() as session:
        row = await session.get(AgentMessageModel, UUID(turn_id))
        assert row is not None
        assert row.thread_id == thread_id
        assert row.content == (raw_text if raw_text.strip() else "[Фото] enriched prompt")
        assert row.payload == {
            "peer": "12345",
            "turn_id": turn_id,
            "peer_name": "Partner",
            "agent_name": "Mimic",
            "media": MEDIA,
            "reply": REPLY,
        }


async def test_context_excludes_current_turn_without_losing_legacy_null_rows(
    db_session_factory: async_sessionmaker[AsyncSession], clean_slot: Slot
) -> None:
    agent_id = await _create_agent(db_session_factory, clean_slot.persona("twofa").user_id)
    current_turn = str(uuid4())
    async with db_session_factory() as session:
        for content, payload in [
            ("legacy missing", {"peer": "chat"}),
            ("legacy null", {"peer": "chat", "turn_id": None}),
            ("prior", {"peer": "chat", "turn_id": str(uuid4())}),
            ("current", {"peer": "chat", "turn_id": current_turn}),
            ("other peer", {"peer": "other"}),
        ]:
            session.add(
                AgentMessageModel(
                    agent_id=agent_id,
                    role="user",
                    direction="incoming",
                    content=content,
                    payload=payload,
                )
            )
        await session.commit()
    messages = await DatabaseShortTermMemory(db_session_factory).load_recent_messages(
        agent_id=agent_id,
        peer="chat",
        since=datetime.now(UTC) - timedelta(hours=1),
        exclude_turn_id=current_turn,
    )
    assert {message["content"] for message in messages} == {
        "legacy missing",
        "legacy null",
        "prior",
    }


async def test_input_and_output_use_same_database_clock_as_timer_events(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mimic42.integrations import database_memory

    class SkewedDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return datetime.now(tz) - timedelta(days=1)

    monkeypatch.setattr(database_memory, "datetime", SkewedDatetime)
    agent_id = await _create_agent(db_session_factory, clean_slot.persona("twofa").user_id)
    await ActivityRecorder(db_session_factory).record(
        agent_id=agent_id, event_type="timer.fired", status="succeeded", payload={"peer": "chat"}
    )
    incoming = TurnInput(
        agent_id=agent_id,
        turn_id=str(uuid4()),
        peer="chat",
        text="timer prompt",
        raw_text="",
        created_at=datetime.now(UTC) - timedelta(days=1),
    )
    memory = DatabaseShortTermMemory(db_session_factory)
    await memory.save_input(incoming)
    await memory.save_messages(
        agent_id=agent_id,
        peer="chat",
        messages=[{"role": "assistant", "content": "reply"}],
        turn_id=incoming.turn_id,
    )
    async with db_session_factory() as session:
        fired = await session.scalar(
            select(AgentEventModel).where(AgentEventModel.agent_id == agent_id)
        )
        rows = list(
            await session.scalars(
                select(AgentMessageModel)
                .where(AgentMessageModel.agent_id == agent_id)
                .order_by(AgentMessageModel.created_at)
            )
        )
    assert fired is not None
    assert [row.content for row in rows] == ["timer prompt", "reply"]
    assert fired.created_at <= rows[0].created_at <= rows[1].created_at


@pytest.mark.parametrize(
    ("kind", "filename", "mime"),
    [
        ("photo", "photo.jpeg", "image/jpeg"),
        ("doc", "notes.txt", "text/plain"),
        ("voice", "voice.ogg", "audio/ogg"),
        ("round", "round.mp4", "video/mp4"),
    ],
)
async def test_archived_attachment_is_resolved_after_restart_outside_context_window(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    filename: str,
    mime: str,
) -> None:
    agent_id = await _create_agent(db_session_factory, clean_slot.persona("twofa").user_id)
    media_id = f"{kind}:123:456:0102:2" + (f":{filename}" if kind == "doc" else "")
    path = f"{agent_id}/u1/{filename}"
    attributes = (
        (types.DocumentAttributeAudio(duration=25, voice=True, waveform=b"\x10"),)
        if kind == "voice"
        else (types.DocumentAttributeVideo(duration=3.5, w=240, h=240, round_message=True),)
        if kind == "round"
        else ()
    )
    ref = MediaRef(peer=-100500, message_id=55, mime_type=mime, attributes=attributes)
    media = MediaFile(
        kind=kind,
        name=filename,
        mime_type=mime,
        size=8,
        storage_path=path,
        media_id=media_id,
        telegram_ref=ref,
    )
    await DatabaseShortTermMemory(db_session_factory).save_input(
        TurnInput(
            agent_id=agent_id,
            peer="-100500",
            text="Вложение",
            raw_text="",
            turn_id=str(uuid4()),
            created_at=datetime.now(UTC),
            media=[media.as_payload()],
        )
    )
    async with db_session_factory() as session:
        row = await session.scalar(
            select(AgentMessageModel).where(AgentMessageModel.agent_id == agent_id)
        )
        agent = await session.get(AgentModel, agent_id)
        assert row is not None and agent is not None
        row.created_at = datetime.now(UTC) - timedelta(days=365)
        agent.context_reset_at = datetime.now(UTC)
        await session.commit()

    restored = await DatabaseAgentStore(db_session_factory).lookup_media_ref(
        agent_id=agent_id, media_id=media_id
    )
    assert restored is not None
    assert restored.storage_path == path
    assert (restored.peer, restored.message_id) == (-100500, 55)
    assert restored.mime_type == mime
    assert [attr.to_dict() for attr in restored.attributes] == [
        attr.to_dict() for attr in attributes
    ]
    client = MagicMock()
    client.download_media = AsyncMock(side_effect=AssertionError("Archive must avoid Telegram"))
    uploader = MagicMock()
    uploader.open = AsyncMock(return_value=b"ARCHIVED")
    toolbox = TelegramToolbox(
        client, agent_id=agent_id, session_factory=db_session_factory, media_uploader=uploader
    )
    monkeypatch.setattr(
        toolbox, "_transcribe_audio_via_openrouter_whisper", AsyncMock(return_value="Расшифровка")
    )

    if kind == "photo":
        result = await toolbox.view_image(media_id)
        assert result[0]["storage_path"] == path
        assert base64.b64encode(b"ARCHIVED").decode() in result[1]["image_url"]["url"]
    elif kind == "doc":
        assert await toolbox.read_document_file(media_id) == {
            "success": True,
            "content": "ARCHIVED",
        }
    else:
        assert await toolbox.transcribe_voice_note(media_id) == {
            "success": True,
            "transcription": "Расшифровка",
        }
    client.download_media.assert_not_awaited()
    uploader.open.assert_awaited_once_with(path)


@pytest.mark.parametrize("legacy", [False, True])
async def test_view_image_event_restores_tool_only_archive(
    db_session_factory: async_sessionmaker[AsyncSession], clean_slot: Slot, legacy: bool
) -> None:
    agent_id = await _create_agent(db_session_factory, clean_slot.persona("twofa").user_id)
    media_id = "photo:123:456:0102:2"
    path = f"{agent_id}/u1/view_photo_123.jpeg"
    artifact: dict[str, Any] = {
        "type": "media_ref",
        "storage_path": path,
        "mime_type": "image/jpeg",
    }
    if not legacy:
        artifact.update(media_id=media_id, peer=-100500, message_id=55)
    await ActivityRecorder(db_session_factory).record(
        agent_id=agent_id,
        event_type="tool.view_image",
        status="succeeded",
        payload={"args": {"media_id": media_id}},
        result={"items": [artifact]},
    )

    restored = await DatabaseAgentStore(db_session_factory).lookup_media_ref(
        agent_id=agent_id, media_id=media_id
    )

    assert restored is not None and restored.storage_path == path


async def test_new_metadata_only_registration_does_not_hide_an_existing_archive(
    db_session_factory: async_sessionmaker[AsyncSession], clean_slot: Slot
) -> None:
    agent_id = await _create_agent(db_session_factory, clean_slot.persona("twofa").user_id)
    media_id = "photo:123:456:0102:2"
    path = f"{agent_id}/u1/photo.jpeg"
    memory = DatabaseShortTermMemory(db_session_factory)
    await memory.save_input(
        TurnInput(
            agent_id=agent_id,
            peer="-100500",
            text="Архив",
            raw_text="",
            turn_id=str(uuid4()),
            created_at=datetime.now(UTC),
            media=[{"media_id": media_id, "storage_path": path, "peer": -100500, "message_id": 55}],
        )
    )
    await memory.save_input(
        TurnInput(
            agent_id=agent_id,
            peer="42",
            text="Повторное вложение без архива",
            raw_text="",
            turn_id=str(uuid4()),
            created_at=datetime.now(UTC),
            media=[{"media_id": media_id, "peer": 42, "message_id": 77}],
        )
    )

    assert await DatabaseAgentStore(db_session_factory).lookup_media_ref(
        agent_id=agent_id, media_id=media_id
    ) == MediaRef(storage_path=path, peer=42, message_id=77)


@pytest.mark.parametrize("long_history", [False, True])
async def test_history_event_keeps_message_coordinates_for_next_process(
    db_session_factory: async_sessionmaker[AsyncSession], clean_slot: Slot, long_history: bool
) -> None:
    agent_id = await _create_agent(db_session_factory, clean_slot.persona("twofa").user_id)
    media_id = "photo:123:456:0102:2"
    items: list[dict[str, Any]] = [{"text": "Long history " * 500}] if long_history else []
    items.append(
        {
            "id": 55,
            "text": f"[Фото id={media_id}]",
            "media": {"media_id": media_id, "peer": -100500, "message_id": 55},
        }
    )
    await ActivityRecorder(db_session_factory).record(
        agent_id=agent_id,
        event_type="tool.get_messages",
        status="succeeded",
        payload={"args": {"peer": "-100500"}},
        result={"items": items},
    )

    assert await DatabaseAgentStore(db_session_factory).lookup_media_ref(
        agent_id=agent_id, media_id=media_id
    ) == MediaRef(peer=-100500, message_id=55)


@pytest.mark.parametrize("source", ["message", "view_image", "get_messages"])
async def test_media_lookup_never_reads_another_agents_records(
    db_session_factory: async_sessionmaker[AsyncSession], clean_slot: Slot, source: str
) -> None:
    owner = clean_slot.persona("twofa").user_id
    agent_id = await _create_agent(db_session_factory, owner)
    other_agent_id = await _create_agent(db_session_factory, owner)
    media_id = "photo:123:456:0102:2"
    metadata = {
        "media_id": media_id,
        "peer": -100500,
        "message_id": 55,
        "storage_path": f"{other_agent_id}/u1/photo.jpeg",
    }
    async with db_session_factory() as session:
        if source == "message":
            session.add(
                AgentMessageModel(
                    agent_id=other_agent_id,
                    direction="incoming",
                    role="user",
                    content="Вложение",
                    payload={"media": [metadata]},
                )
            )
        else:
            session.add(
                AgentEventModel(
                    agent_id=other_agent_id,
                    event_type=f"tool.{source}",
                    status="succeeded",
                    payload={"args": {"media_id": media_id}},
                    result={
                        "items": [
                            {"type": "media_ref", **metadata}
                            if source == "view_image"
                            else {"media": metadata}
                        ]
                    },
                )
            )
        await session.commit()

    store = DatabaseAgentStore(db_session_factory)
    assert await store.lookup_media_ref(agent_id=agent_id, media_id=media_id) is None
    assert await store.lookup_media_ref(agent_id=other_agent_id, media_id=media_id) is not None


@pytest.mark.parametrize("path_suffix", ["foreign", "../other/file", "u1/../../file"])
async def test_persisted_archive_path_cannot_escape_the_agent_prefix(
    db_session_factory: async_sessionmaker[AsyncSession], clean_slot: Slot, path_suffix: str
) -> None:
    agent_id = await _create_agent(db_session_factory, clean_slot.persona("twofa").user_id)
    media_id = "photo:123:456:0102:2"
    path = f"{uuid4()}/u1/file" if path_suffix == "foreign" else f"{agent_id}/{path_suffix}"
    await DatabaseShortTermMemory(db_session_factory).save_input(
        TurnInput(
            agent_id=agent_id,
            peer="-100500",
            text="Вложение",
            raw_text="",
            turn_id=str(uuid4()),
            created_at=datetime.now(UTC),
            media=[{"media_id": media_id, "storage_path": path, "peer": -100500, "message_id": 55}],
        )
    )

    assert await DatabaseAgentStore(db_session_factory).lookup_media_ref(
        agent_id=agent_id, media_id=media_id
    ) == MediaRef(peer=-100500, message_id=55)
