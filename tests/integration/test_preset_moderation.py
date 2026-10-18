"""Database-enforced visibility, moderation, and favorite snapshot behavior."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import asyncpg
import pytest

from mimic42.testing.slots import Slot, plain_dsn


async def _act_as_user(connection: asyncpg.Connection, user_id: UUID) -> None:
    """Set the same role and JWT claims that PostgREST supplies to RLS."""
    await connection.execute("set local role authenticated")
    await connection.execute(
        "select set_config('request.jwt.claims', $1, true)",
        f'{{"sub":"{user_id}","role":"authenticated"}}',
    )
    await connection.execute("select set_config('request.jwt.claim.sub', $1, true)", str(user_id))


async def _create_preset(
    connection: asyncpg.Connection,
    owner_id: UUID | None,
    *,
    title: str,
    summary: str,
    body: str,
    settings: dict[str, object] | None = None,
    is_active: bool = True,
    is_published: bool = True,
) -> UUID:
    """Insert a unique test-owned row without touching persona-owned records."""
    preset_id = uuid4()
    await connection.execute(
        """
        insert into public.prompt_presets
            (id, slug, title, summary, body, settings, owner_id, published_at, is_active)
        values
            ($1, $2, $3, $4, $5, $6::jsonb, $7,
             case when $8 then now() else null end, $9)
        """,
        preset_id,
        f"u_{preset_id}",
        title,
        summary,
        body,
        json.dumps(settings) if settings is not None else None,
        owner_id,
        is_published,
        is_active,
    )
    return preset_id


async def _author_without_live_publication(
    connection: asyncpg.Connection,
    test_slot: Slot,
) -> UUID:
    """Choose a leased test persona with no existing live catalog row."""
    persona_ids = [persona.user_id for persona in test_slot.personas]
    owners = await connection.fetch(
        "select distinct owner_id from public.prompt_presets "
        "where owner_id = any($1::uuid[]) and is_active and published_at is not null",
        persona_ids,
    )
    already_published = {row["owner_id"] for row in owners}
    return next(user_id for user_id in persona_ids if user_id not in already_published)


@pytest.fixture
async def isolated_connection(
    test_dsn: str,
    test_slot: Slot,
) -> AsyncIterator[asyncpg.Connection]:
    """Roll back all test writes while the shared Dev slot is leased."""
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    transaction = connection.transaction()
    await transaction.start()
    try:
        yield connection
    finally:
        if connection.is_in_transaction():
            await transaction.rollback()
        await connection.close()


async def test_catalog_visibility_keeps_owner_access_and_blocks_hidden_republication(
    isolated_connection: asyncpg.Connection,
    test_slot: Slot,
) -> None:
    author = test_slot.persona("empty").user_id
    reader = test_slot.persona("full").user_id
    other_author = test_slot.persona("flow").user_id

    hidden_id = await _create_preset(
        isolated_connection,
        author,
        title="Hidden published preset",
        summary="Hidden summary",
        body="Hidden body",
        is_active=False,
    )
    private_id = await _create_preset(
        isolated_connection,
        author,
        title="Private draft",
        summary="Draft summary",
        body="Draft body",
        is_published=False,
    )
    visible_id = await _create_preset(
        isolated_connection,
        other_author,
        title="Visible published preset",
        summary="Visible summary",
        body="Visible body",
    )
    inactive_official_id = await _create_preset(
        isolated_connection,
        None,
        title="Inactive official preset",
        summary="Official summary",
        body="Official body",
        is_active=False,
        is_published=False,
    )
    active_official_id = await isolated_connection.fetchval(
        "select id from public.prompt_presets where slug = 'rage_comments' and owner_id is null"
    )

    await _act_as_user(isolated_connection, reader)
    assert (
        await isolated_connection.fetchval(
            "select count(*) from public.prompt_presets where id = $1", visible_id
        )
        == 1
    )
    assert (
        await isolated_connection.fetchval(
            "select count(*) from public.prompt_presets where id = $1", hidden_id
        )
        == 0
    )
    assert (
        await isolated_connection.fetchval(
            "select count(*) from public.prompt_presets where id = $1", private_id
        )
        == 0
    )
    assert (
        await isolated_connection.fetchval(
            "select count(*) from public.prompt_presets where id = $1", active_official_id
        )
        == 1
    )
    assert (
        await isolated_connection.fetchval(
            "select count(*) from public.prompt_presets where id = $1", inactive_official_id
        )
        == 0
    )

    await _act_as_user(isolated_connection, author)
    assert (
        await isolated_connection.fetchval(
            "select count(*) from public.prompt_presets where id = $1", hidden_id
        )
        == 1
    )
    assert (
        await isolated_connection.fetchval(
            "select count(*) from public.prompt_presets where id = $1", private_id
        )
        == 1
    )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with isolated_connection.transaction():
            await isolated_connection.execute(
                "update public.prompt_presets set is_active = true where id = $1", hidden_id
            )

    assert (
        await isolated_connection.execute(
            "update public.prompt_presets set body = 'Edited by author' where id = $1", hidden_id
        )
        == "UPDATE 1"
    )
    assert (
        await isolated_connection.execute(
            "update public.prompt_presets set published_at = null where id = $1", hidden_id
        )
        == "UPDATE 1"
    )
    assert (
        await isolated_connection.execute(
            "update public.prompt_presets set published_at = now() where id = $1", hidden_id
        )
        == "UPDATE 1"
    )

    await _act_as_user(isolated_connection, reader)
    assert (
        await isolated_connection.fetchval(
            "select count(*) from public.prompt_presets where id = $1", hidden_id
        )
        == 0
    )
    assert (
        await isolated_connection.fetchval(
            "select count(*) from public.prompt_presets where id = $1 and body = 'Visible body'",
            visible_id,
        )
        == 1
    )


async def test_admin_hide_freezes_favorite_fields_and_unhide_does_not_revive_it(
    isolated_connection: asyncpg.Connection,
    test_slot: Slot,
) -> None:
    author = test_slot.persona("empty").user_id
    reader = test_slot.persona("full").user_id
    snapshot = {
        "enabled_tools": ["get_dialogs", "send_text_message"],
        "nested": {"style": "terse"},
    }
    preset_id = await _create_preset(
        isolated_connection,
        author,
        title="Snapshot title",
        summary="Snapshot summary",
        body="Snapshot body",
        settings=snapshot,
    )

    await _act_as_user(isolated_connection, reader)
    assert await isolated_connection.fetchval("select auth.uid()") == reader
    lockable_preset = await isolated_connection.fetchval(
        "select pp.id from public.prompt_presets pp "
        "where pp.id = $1 and pp.is_active and pp.published_at is not null "
        "and pp.owner_id <> (select auth.uid()) for share",
        preset_id,
    )
    assert lockable_preset == preset_id
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with isolated_connection.transaction():
            await isolated_connection.execute(
                "update public.prompt_presets set body = 'Unauthorized edit' where id = $1",
                preset_id,
            )
    assert (
        await isolated_connection.fetchval(
            "select body from public.prompt_presets where id = $1", preset_id
        )
        == "Snapshot body"
    )

    favorite_id = await isolated_connection.fetchval(
        "insert into public.preset_favorites (preset_id) values ($1) returning id", preset_id
    )
    live_favorite = await isolated_connection.fetchrow(
        "select preset_id, frozen_at from public.preset_favorites where id = $1", favorite_id
    )
    assert live_favorite["preset_id"] == preset_id
    assert live_favorite["frozen_at"] is None

    await isolated_connection.execute("reset role")
    assert (
        await isolated_connection.execute(
            "update public.prompt_presets set is_active = false where id = $1", preset_id
        )
        == "UPDATE 1"
    )

    await _act_as_user(isolated_connection, reader)
    frozen = await isolated_connection.fetchrow(
        "select preset_id, frozen_title, frozen_summary, frozen_body, frozen_settings, frozen_at "
        "from public.preset_favorites where id = $1",
        favorite_id,
    )
    assert frozen["preset_id"] is None
    assert frozen["frozen_title"] == "Snapshot title"
    assert frozen["frozen_summary"] == "Snapshot summary"
    assert frozen["frozen_body"] == "Snapshot body"
    assert json.loads(frozen["frozen_settings"]) == snapshot
    assert frozen["frozen_at"] is not None
    frozen_at = frozen["frozen_at"]

    await isolated_connection.execute("reset role")
    assert (
        await isolated_connection.execute(
            "update public.prompt_presets set is_active = true where id = $1", preset_id
        )
        == "UPDATE 1"
    )

    await _act_as_user(isolated_connection, reader)
    after_unhide = await isolated_connection.fetchrow(
        "select preset_id, frozen_title, frozen_summary, frozen_body, frozen_settings, frozen_at "
        "from public.preset_favorites where id = $1",
        favorite_id,
    )
    assert after_unhide["preset_id"] is None
    assert after_unhide["frozen_title"] == "Snapshot title"
    assert after_unhide["frozen_summary"] == "Snapshot summary"
    assert after_unhide["frozen_body"] == "Snapshot body"
    assert json.loads(after_unhide["frozen_settings"]) == snapshot
    assert after_unhide["frozen_at"] == frozen_at


async def test_hidden_published_preset_cannot_be_favorited(
    isolated_connection: asyncpg.Connection,
    test_slot: Slot,
) -> None:
    author = test_slot.persona("empty").user_id
    reader = test_slot.persona("full").user_id
    hidden_id = await _create_preset(
        isolated_connection,
        author,
        title="Not favoritable",
        summary="Hidden from the catalog",
        body="Hidden body",
        is_active=False,
    )

    await _act_as_user(isolated_connection, reader)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with isolated_connection.transaction():
            await isolated_connection.execute(
                "insert into public.preset_favorites (preset_id) values ($1)", hidden_id
            )


async def test_preset_authors_only_include_active_publications(
    isolated_connection: asyncpg.Connection,
    test_slot: Slot,
) -> None:
    hidden_author = await _author_without_live_publication(isolated_connection, test_slot)
    visible_author = next(
        persona.user_id for persona in test_slot.personas if persona.user_id != hidden_author
    )
    hidden_id = await _create_preset(
        isolated_connection,
        hidden_author,
        title="Hidden author's preset",
        summary="Hidden author summary",
        body="Hidden author body",
        is_active=False,
    )
    visible_id = await _create_preset(
        isolated_connection,
        visible_author,
        title="Visible author's preset",
        summary="Visible author summary",
        body="Visible author body",
    )

    view_columns = await isolated_connection.fetch(
        "select column_name from information_schema.columns "
        "where table_schema = 'public' and table_name = 'preset_authors' order by ordinal_position"
    )
    assert [row["column_name"] for row in view_columns] == ["id", "display_name"]
    visible_name = await isolated_connection.fetchval(
        "select display_name from public.profiles where id = $1", visible_author
    )

    await _act_as_user(isolated_connection, test_slot.persona("code").user_id)
    assert (
        await isolated_connection.fetchval(
            "select count(*) from public.prompt_presets where id = $1", hidden_id
        )
        == 0
    )
    assert (
        await isolated_connection.fetchval(
            "select count(*) from public.prompt_presets where id = $1", visible_id
        )
        == 1
    )
    assert (
        await isolated_connection.fetchval(
            "select count(*) from public.preset_authors where id = $1", hidden_author
        )
        == 0
    )
    assert (
        await isolated_connection.fetchval(
            "select display_name from public.preset_authors where id = $1", visible_author
        )
        == visible_name
    )


async def test_concurrent_favorite_then_hide_leaves_no_live_hidden_reference(
    test_dsn: str,
    test_slot: Slot,
) -> None:
    author = test_slot.persona("empty").user_id
    reader = test_slot.persona("full").user_id
    preset_id = uuid4()
    slug = f"u_{preset_id}"
    setup = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        await setup.execute(
            """
            insert into public.prompt_presets
                (id, slug, title, summary, body, owner_id, published_at, is_active)
            values ($1, $2, 'Concurrent title', 'Concurrent summary', 'Concurrent body',
                    $3, now(), true)
            """,
            preset_id,
            slug,
            author,
        )
    finally:
        await setup.close()

    favorite_connection = await asyncpg.connect(plain_dsn(test_dsn))
    hide_connection = await asyncpg.connect(plain_dsn(test_dsn))
    observer = await asyncpg.connect(plain_dsn(test_dsn))
    favorite_transaction = favorite_connection.transaction()
    hide_task: asyncio.Task[str] | None = None
    favorite_id: UUID | None = None
    try:
        await favorite_transaction.start()
        await _act_as_user(favorite_connection, reader)
        favorite_id = await favorite_connection.fetchval(
            "insert into public.preset_favorites (preset_id) values ($1) returning id", preset_id
        )

        hide_backend_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

        async def hide_preset() -> str:
            async with hide_connection.transaction():
                hide_backend_pid.set_result(
                    await hide_connection.fetchval("select pg_backend_pid()")
                )
                return await hide_connection.execute(
                    "update public.prompt_presets set is_active = false where id = $1", preset_id
                )

        hide_task = asyncio.create_task(hide_preset())
        hide_pid = await asyncio.wait_for(hide_backend_pid, timeout=10)
        deadline = asyncio.get_running_loop().time() + 10
        waiting_for_favorite_lock = False
        while asyncio.get_running_loop().time() < deadline:
            waiting_for_favorite_lock = await observer.fetchval(
                "select exists ("
                "select 1 from pg_stat_activity "
                "where pid = $1 and state = 'active' and wait_event_type = 'Lock'"
                ")",
                hide_pid,
            )
            if waiting_for_favorite_lock or hide_task.done():
                break
            await asyncio.sleep(0.01)
        assert hide_task is not None
        if hide_task.done():
            await hide_task
        activity = await observer.fetch(
            "select pid, state, wait_event_type, wait_event, left(query, 160) as query "
            "from pg_stat_activity where pid = $1",
            hide_pid,
        )
        assert waiting_for_favorite_lock, (
            "moderation did not wait for the favorite trigger's FOR SHARE lock; "
            f"hide_done={hide_task.done()}, activity={activity!r}"
        )

        await favorite_transaction.commit()
        assert await hide_task == "UPDATE 1"
        favorite = await observer.fetchrow(
            "select preset_id, frozen_title, frozen_summary, frozen_body, frozen_at "
            "from public.preset_favorites where id = $1",
            favorite_id,
        )
        assert favorite is not None
        assert favorite["preset_id"] is None
        assert favorite["frozen_title"] == "Concurrent title"
        assert favorite["frozen_summary"] == "Concurrent summary"
        assert favorite["frozen_body"] == "Concurrent body"
        assert favorite["frozen_at"] is not None
        assert (
            await observer.fetchval(
                "select is_active from public.prompt_presets where id = $1", preset_id
            )
            is False
        )
    finally:
        if favorite_connection.is_in_transaction():
            await favorite_transaction.rollback()
        if hide_task is not None and not hide_task.done():
            try:
                await hide_task
            except Exception:
                pass
        await favorite_connection.close()
        await hide_connection.close()
        await observer.close()

        cleanup = await asyncpg.connect(plain_dsn(test_dsn))
        try:
            if favorite_id is not None:
                await cleanup.execute(
                    "delete from public.preset_favorites where id = $1", favorite_id
                )
            await cleanup.execute("delete from public.prompt_presets where id = $1", preset_id)
        finally:
            await cleanup.close()
