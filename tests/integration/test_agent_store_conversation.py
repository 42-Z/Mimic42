from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.integrations.database_models import (
    AgentEventModel,
    AgentMessageModel,
    AgentModel,
)
from mimic42.testing.slots import Slot


async def _seed(
    db_session_factory: async_sessionmaker[AsyncSession],
    owner_id: UUID,
    base: datetime,
) -> UUID:
    """Three complete turns, each: incoming → tool event → agent_response."""
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
    async with db_session_factory() as session:
        for i, offset in enumerate((2, 1, 0)):
            t = base + timedelta(minutes=i * 10)
            session.add(
                AgentMessageModel(
                    agent_id=agent_id,
                    direction="incoming",
                    role="user",
                    content=f"turn-{offset}",
                    payload={"peer": "chat", "turn_id": f"t{offset}"},
                    created_at=t,
                )
            )
            session.add(
                AgentEventModel(
                    agent_id=agent_id,
                    event_type="tool.get_dialogs",
                    status="succeeded",
                    payload={"turn_id": f"t{offset}"},
                    created_at=t + timedelta(seconds=1),
                    started_at=t,
                    completed_at=t + timedelta(seconds=1),
                )
            )
            session.add(
                AgentMessageModel(
                    agent_id=agent_id,
                    direction="agent_response",
                    role="assistant",
                    content=f"reply-{offset}",
                    payload={"peer": "chat", "turn_id": f"t{offset}"},
                    created_at=t + timedelta(seconds=2),
                )
            )
        await session.commit()
    return agent_id


async def test_cursor_pagination_no_duplicates_no_gaps(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    base = datetime(2026, 5, 19, 23, 30, tzinfo=UTC)
    agent_id = await _seed(db_session_factory, owner_id, base)
    store = DatabaseAgentStore(db_session_factory)

    page1 = await store.get_conversation(agent_id=agent_id, limit=2)
    assert len(page1.turns) == 2
    assert page1.next_before is not None

    page2 = await store.get_conversation(agent_id=agent_id, limit=2, before=page1.next_before)
    assert len(page2.turns) == 1

    ids = {turn.id for turn in page1.turns} | {turn.id for turn in page2.turns}
    assert len(ids) == 3  # ни дубликатов, ни потерь


async def test_turns_are_newest_first_with_turn_identity(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    base = datetime(2026, 5, 19, 23, 30, tzinfo=UTC)
    agent_id = await _seed(db_session_factory, owner_id, base)
    store = DatabaseAgentStore(db_session_factory)

    page = await store.get_conversation(agent_id=agent_id, limit=10)

    assert [turn.timestamp for turn in page.turns] == sorted(
        [turn.timestamp for turn in page.turns], reverse=True
    )
    assert all(turn.turn_id for turn in page.turns)
    assert all(len(turn.tools) == 1 for turn in page.turns)
    assert all(turn.outgoing for turn in page.turns)
    assert page.next_before == page.turns[-1].timestamp


async def test_incoming_media_surfaces_on_turn(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    owner_id = clean_slot.persona("twofa").user_id
    base = datetime(2026, 5, 19, 23, 30, tzinfo=UTC)
    agent_id = await _seed(db_session_factory, owner_id, base)
    media = [
        {
            "kind": "photo",
            "name": "photo.jpeg",
            "mime_type": "image/jpeg",
            "size": 3,
            "storage_path": "ag/u1/photo.jpeg",
        }
    ]
    async with db_session_factory() as session:
        session.add(
            AgentMessageModel(
                agent_id=agent_id,
                direction="incoming",
                role="user",
                content="[Фото id=photo:1:2:aa:5]",
                payload={"peer": "chat", "turn_id": "t-media", "media": media},
                created_at=base + timedelta(hours=1),
            )
        )
        await session.commit()
    store = DatabaseAgentStore(db_session_factory)

    page = await store.get_conversation(agent_id=agent_id, limit=1)

    assert page.turns[0].turn_id == "t-media"
    assert page.turns[0].incoming_media == media


async def test_lifecycle_events_stay_standalone(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Start/stop events carry no turn_id: they must not be glued to the
    neighbouring message turn (history would duplicate the live feed)."""
    owner_id = clean_slot.persona("twofa").user_id
    base = datetime(2026, 5, 19, 23, 30, tzinfo=UTC)
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
    async with db_session_factory() as session:
        session.add(
            AgentEventModel(
                agent_id=agent_id,
                event_type="agent.started",
                status="succeeded",
                payload={"peer": "chat"},
                created_at=base,
            )
        )
        session.add(
            AgentMessageModel(
                agent_id=agent_id,
                direction="incoming",
                role="user",
                content="Привет",
                payload={"peer": "chat"},
                created_at=base + timedelta(seconds=1),
            )
        )
        session.add(
            AgentMessageModel(
                agent_id=agent_id,
                direction="agent_response",
                role="assistant",
                content="Здравствуйте!",
                payload={"peer": "chat"},
                created_at=base + timedelta(seconds=2),
            )
        )
        session.add(
            AgentEventModel(
                agent_id=agent_id,
                event_type="agent.stopped",
                status="succeeded",
                payload={"peer": "chat"},
                created_at=base + timedelta(seconds=3),
            )
        )
        await session.commit()

    store = DatabaseAgentStore(db_session_factory)
    page = await store.get_conversation(agent_id=agent_id, limit=10)

    message_turns = [turn for turn in page.turns if turn.incoming]
    assert len(message_turns) == 1
    assert message_turns[0].outgoing == "Здравствуйте!"
    assert message_turns[0].tools == []

    lifecycle_turns = [turn for turn in page.turns if turn.direction == "tools"]
    assert len(lifecycle_turns) == 2
    assert {turn.tools[0].name for turn in lifecycle_turns} == {"agent.started", "agent.stopped"}


async def test_real_write_order_keeps_one_merged_turn(
    db_session_factory: async_sessionmaker[AsyncSession],
    clean_slot: Slot,
) -> None:
    """Tool events are persisted while the turn runs; the incoming and
    response rows are saved afterwards with a later timestamp. Grouping by
    turn_id must still yield one block (incoming + tools + response)."""
    owner_id = clean_slot.persona("twofa").user_id
    base = datetime(2026, 5, 19, 23, 30, tzinfo=UTC)
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
    async with db_session_factory() as session:
        # 1) Tool events recorded mid-turn (earliest timestamps)...
        session.add(
            AgentEventModel(
                agent_id=agent_id,
                event_type="tool.get_dialogs",
                status="succeeded",
                payload={"turn_id": "t-real"},
                created_at=base,
                started_at=base,
                completed_at=base + timedelta(seconds=1),
            )
        )
        # 2) ...then the incoming row (written by save_messages at turn end)...
        session.add(
            AgentMessageModel(
                agent_id=agent_id,
                direction="incoming",
                role="user",
                content="Привет",
                payload={"peer": "chat", "peer_name": "Ivan", "turn_id": "t-real"},
                created_at=base + timedelta(seconds=5),
            )
        )
        # 3) ...and the response row, saved in the same batch.
        session.add(
            AgentMessageModel(
                agent_id=agent_id,
                direction="agent_response",
                role="assistant",
                content="Здравствуйте!",
                payload={"peer": "chat", "turn_id": "t-real"},
                created_at=base + timedelta(seconds=5, microseconds=1000),
            )
        )
        await session.commit()

    store = DatabaseAgentStore(db_session_factory)
    page = await store.get_conversation(agent_id=agent_id, limit=10)

    assert len(page.turns) == 1
    turn = page.turns[0]
    assert turn.turn_id == "t-real"
    assert turn.incoming == "Привет"
    assert turn.outgoing == "Здравствуйте!"
    assert turn.direction == "both"
    assert [tool.name for tool in turn.tools] == ["tool.get_dialogs"]
    assert turn.timestamp == base  # oldest item of the turn
