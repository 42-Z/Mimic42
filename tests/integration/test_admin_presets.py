from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, async_sessionmaker

from mimic42.core.admin import (
    AdminNotFoundError,
    AdminUnavailableError,
    PresetCreateValues,
)
from mimic42.integrations.database_admin import DatabaseAdminRepository
from mimic42.integrations.database_models import AdminAuditLogModel, PromptPresetModel
from mimic42.testing.slots import Slot


async def _insert_custom_preset(
    session_factory: async_sessionmaker[Any],
    *,
    owner_id: UUID,
    title: str,
    published: bool = True,
    active: bool = True,
) -> UUID:
    preset_id = uuid4()
    async with session_factory() as session, session.begin():
        session.add(
            PromptPresetModel(
                id=preset_id,
                slug=f"u_{preset_id}",
                title=title,
                summary="Test summary",
                body="Test prompt body",
                settings={"test": "value"},
                sort_order=11,
                is_active=active,
                owner_id=owner_id,
                published_at=datetime.now(UTC) if published else None,
            )
        )
    return preset_id


@pytest.mark.asyncio
async def test_official_creation_and_sort_order_patch_are_audited_atomically(
    admin_db_factory: async_sessionmaker[Any],
    test_slot: Slot,
) -> None:
    repository = DatabaseAdminRepository(admin_db_factory)
    actor_id = test_slot.persona("empty").user_id
    values: PresetCreateValues = {
        "title": "Official title",
        "summary": "Official summary",
        "body": "Official prompt body",
        "settings": {"enabled_tools": ["send_text_message"], "nested": {"keep": True}},
        "sort_order": 24,
    }

    first = await repository.create_official_preset(values, actor_user_id=actor_id)
    second = await repository.create_official_preset(values, actor_user_id=actor_id)
    patched = await repository.update_official_preset(
        first.id,
        {"sort_order": 5},
        actor_user_id=actor_id,
    )

    assert first.id != second.id
    async with admin_db_factory() as session:
        first_row = await session.get(PromptPresetModel, first.id)
        second_row = await session.get(PromptPresetModel, second.id)
        audits = list(
            (
                await session.scalars(
                    select(AdminAuditLogModel)
                    .where(AdminAuditLogModel.object_id.in_([first.id, second.id]))
                    .order_by(AdminAuditLogModel.created_at, AdminAuditLogModel.action)
                )
            ).all()
        )

    assert first_row is not None and second_row is not None
    assert first_row.slug == f"official_{first.id.hex}"
    assert second_row.slug == f"official_{second.id.hex}"
    assert first_row.owner_id is None and second_row.owner_id is None
    assert first_row.published_at is None and second_row.published_at is None
    assert first_row.is_active is True and second_row.is_active is True
    assert patched.sort_order == 5
    assert patched.title == first.title
    assert patched.summary == first.summary
    assert patched.body == first.body
    assert patched.settings == first.settings
    assert [(audit.action, audit.metadata_) for audit in audits] == [
        (
            "preset.created",
            {"fields": ["body", "settings", "sort_order", "summary", "title"]},
        ),
        ("preset.created", {"fields": ["body", "settings", "sort_order", "summary", "title"]}),
        ("preset.updated", {"fields": ["sort_order"]}),
    ]
    assert all(audit.actor_user_id == actor_id for audit in audits)
    assert all(audit.object_type == "preset" for audit in audits)
    assert all(audit.object_id is not None for audit in audits)
    assert all(
        value not in str(audit.metadata_)
        for audit in audits
        for value in (values["title"], values["summary"], values["body"])
    )


@pytest.mark.asyncio
async def test_preset_list_filters_eligibility_and_escapes_search_wildcards(
    admin_db_factory: async_sessionmaker[Any],
    test_slot: Slot,
) -> None:
    owner_id = test_slot.persona("empty").user_id
    repository = DatabaseAdminRepository(admin_db_factory)
    official_id = uuid4()
    async with admin_db_factory() as session, session.begin():
        session.add(
            PromptPresetModel(
                id=official_id,
                slug=f"official_{official_id.hex}",
                title="Inactive official",
                summary="Official summary",
                body="Official body",
                owner_id=None,
                published_at=None,
                is_active=False,
            )
        )
    hidden_id = await _insert_custom_preset(
        admin_db_factory,
        owner_id=owner_id,
        title="Published 50%_off special",
        active=False,
    )
    similar_id = await _insert_custom_preset(
        admin_db_factory,
        owner_id=owner_id,
        title="Published 50XXoff special",
        active=True,
    )
    private_id = await _insert_custom_preset(
        admin_db_factory,
        owner_id=owner_id,
        title="Private hidden draft",
        published=False,
    )

    official = await repository.list_presets(q="", kind="official", page=1, page_size=100)
    published = await repository.list_presets(q="", kind="published", page=1, page_size=100)
    literal_search = await repository.list_presets(
        q="50%_off",
        kind="published",
        page=1,
        page_size=100,
    )
    hidden_detail = await repository.get_preset(hidden_id)

    assert any(preset.id == official_id and not preset.is_active for preset in official.items)
    assert {preset.id for preset in published.items} >= {hidden_id, similar_id}
    assert private_id not in {preset.id for preset in published.items}
    assert [preset.id for preset in literal_search.items] == [hidden_id]
    assert hidden_detail.is_active is False
    with pytest.raises(AdminNotFoundError):
        await repository.get_preset(private_id)


@pytest.mark.asyncio
async def test_visibility_changes_only_target_and_same_value_is_audited_noop(
    admin_db_factory: async_sessionmaker[Any],
    test_slot: Slot,
) -> None:
    owner_id = test_slot.persona("empty").user_id
    actor_id = test_slot.persona("full").user_id
    target_id = await _insert_custom_preset(
        admin_db_factory,
        owner_id=owner_id,
        title="Target preset",
    )
    other_id = await _insert_custom_preset(
        admin_db_factory,
        owner_id=owner_id,
        title="Untouched preset",
    )
    repository = DatabaseAdminRepository(admin_db_factory)

    hidden = await repository.set_preset_visibility(target_id, False, actor_user_id=actor_id)
    async with admin_db_factory() as session:
        audit_count = await session.scalar(
            select(AdminAuditLogModel.id).where(
                AdminAuditLogModel.action == "preset.visibility_changed",
                AdminAuditLogModel.object_id == target_id,
            )
        )
    same_value = await repository.set_preset_visibility(target_id, False, actor_user_id=actor_id)
    async with admin_db_factory() as session:
        target = await session.get(PromptPresetModel, target_id)
        other = await session.get(PromptPresetModel, other_id)
        audits = list(
            (
                await session.scalars(
                    select(AdminAuditLogModel).where(
                        AdminAuditLogModel.action == "preset.visibility_changed",
                        AdminAuditLogModel.object_id == target_id,
                    )
                )
            ).all()
        )

    assert hidden.is_active is False and same_value.is_active is False
    assert target is not None and target.is_active is False
    assert other is not None and other.is_active is True
    assert len(audits) == 1
    assert audit_count == audits[0].id
    assert audits[0].metadata_ == {"before": True, "after": False}


@pytest.mark.asyncio
async def test_failed_visibility_audit_rolls_back_preset_and_favorite_snapshot(
    admin_db_factory: async_sessionmaker[Any],
    monkeypatch: pytest.MonkeyPatch,
    test_slot: Slot,
) -> None:
    owner_id = test_slot.persona("empty").user_id
    favoriter_id = test_slot.persona("full").user_id
    actor_id = test_slot.persona("flow").user_id
    preset_id = await _insert_custom_preset(
        admin_db_factory,
        owner_id=owner_id,
        title="Must roll back",
    )
    favorite_id: UUID
    async with admin_db_factory() as session, session.begin():
        await session.execute(text("set local role authenticated"))
        await session.execute(
            text("select set_config('request.jwt.claims', :claims, true)"),
            {"claims": f'{{"sub":"{favoriter_id}","role":"authenticated"}}'},
        )
        await session.execute(
            text("select set_config('request.jwt.claim.sub', :user_id, true)"),
            {"user_id": str(favoriter_id)},
        )
        favorite_id = await session.scalar(
            text(
                "insert into public.preset_favorites (owner_id, preset_id) "
                "values (:owner_id, :preset_id) returning id"
            ),
            {"owner_id": favoriter_id, "preset_id": preset_id},
        )
        await session.execute(text("reset role"))
        await session.execute(text("select set_config('request.jwt.claims', '', true)"))
        await session.execute(text("select set_config('request.jwt.claim.sub', '', true)"))

    repository = DatabaseAdminRepository(admin_db_factory)

    async def fail_audit(*_args: object, **_kwargs: object) -> None:
        raise AdminUnavailableError("Audit storage unavailable")

    monkeypatch.setattr(repository, "_append_audit", fail_audit)
    with pytest.raises(AdminUnavailableError):
        await repository.set_preset_visibility(preset_id, False, actor_user_id=actor_id)

    async with admin_db_factory() as session:
        preset = await session.get(PromptPresetModel, preset_id)
        favorite = (
            (
                await session.execute(
                    text(
                        "select preset_id, frozen_title, frozen_summary, frozen_body, "
                        "frozen_settings, frozen_at from public.preset_favorites where id = :id"
                    ),
                    {"id": favorite_id},
                )
            )
            .mappings()
            .one()
        )
        audit_count = await session.scalar(
            select(AdminAuditLogModel.id).where(
                AdminAuditLogModel.object_id == preset_id,
                AdminAuditLogModel.action == "preset.visibility_changed",
            )
        )

    assert preset is not None and preset.is_active is True
    assert favorite["preset_id"] == preset_id
    assert favorite["frozen_title"] is None
    assert favorite["frozen_summary"] is None
    assert favorite["frozen_body"] is None
    assert favorite["frozen_settings"] is None
    assert favorite["frozen_at"] is None
    assert audit_count is None


@pytest.mark.asyncio
async def test_admin_visibility_lock_rechecks_custom_publication_after_waiting(
    db_engine: AsyncEngine,
    test_slot: Slot,
) -> None:
    owner_id = test_slot.persona("empty").user_id
    actor_id = test_slot.persona("full").user_id
    preset_id = uuid4()
    slug = f"u_{preset_id}"
    author_connection: AsyncConnection | None = None
    admin_connection: AsyncConnection | None = None
    author_transaction = None
    admin_transaction = None
    admin_task: asyncio.Task[Any] | None = None
    try:
        author_connection = await db_engine.connect()
        admin_connection = await db_engine.connect()
        assert author_connection is not None and admin_connection is not None
        async with author_connection.begin():
            await author_connection.execute(
                text(
                    "insert into public.prompt_presets "
                    "(id, slug, title, summary, body, owner_id, published_at, is_active) "
                    "values (:id, :slug, 'Concurrent', 'Summary', 'Body', :owner_id, now(), true)"
                ),
                {"id": preset_id, "slug": slug, "owner_id": owner_id},
            )

        admin_transaction = await admin_connection.begin()
        admin_pid = await admin_connection.scalar(text("select pg_backend_pid()"))
        author_transaction = await author_connection.begin()
        await author_connection.execute(
            text("update public.prompt_presets set published_at = null where id = :id"),
            {"id": preset_id},
        )
        repository = DatabaseAdminRepository(
            async_sessionmaker(
                admin_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
        )
        admin_task = asyncio.create_task(
            repository.set_preset_visibility(preset_id, False, actor_user_id=actor_id)
        )

        deadline = asyncio.get_running_loop().time() + 10
        waiting_for_author = False
        while asyncio.get_running_loop().time() < deadline:
            waiting_for_author = bool(
                await author_connection.scalar(
                    text(
                        "select exists (select 1 from pg_stat_activity "
                        "where pid = :pid and wait_event_type = 'Lock')"
                    ),
                    {"pid": admin_pid},
                )
            )
            if waiting_for_author or admin_task.done():
                break
            await asyncio.sleep(0.01)
        task_error: str | None = None
        if admin_task.done():
            try:
                await admin_task
            except Exception as exc:
                task_error = f"{type(exc).__name__}: {exc}"
        activity = (
            await author_connection.execute(
                text(
                    "select pid, state, wait_event_type, wait_event, left(query, 160) "
                    "from pg_stat_activity where pid = :pid"
                ),
                {"pid": admin_pid},
            )
        ).all()
        assert waiting_for_author, (
            "admin query did not wait for the author's row lock; "
            f"task_done={admin_task.done()}, task_error={task_error}, "
            f"admin_pid={admin_pid}, activity_query={activity}"
        )

        await author_transaction.commit()
        author_transaction = None
        with pytest.raises(AdminNotFoundError):
            await asyncio.wait_for(admin_task, timeout=10)
        admin_task = None

        async with async_sessionmaker(
            admin_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )() as session:
            row = await session.get(PromptPresetModel, preset_id)
            audit_count = await session.scalar(
                select(AdminAuditLogModel.id).where(
                    AdminAuditLogModel.object_id == preset_id,
                    AdminAuditLogModel.action == "preset.visibility_changed",
                )
            )
        assert row is not None and row.published_at is None and row.is_active is True
        assert audit_count is None
    finally:
        if author_transaction is not None and author_transaction.is_active:
            with contextlib.suppress(Exception):
                await author_transaction.rollback()
        if admin_task is not None and not admin_task.done():
            admin_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await admin_task
        if admin_connection is not None:
            with contextlib.suppress(Exception):
                if admin_transaction is not None and admin_transaction.is_active:
                    await admin_transaction.rollback()
                else:
                    await admin_connection.rollback()
        if author_connection is not None:
            with contextlib.suppress(Exception):
                async with author_connection.begin():
                    await author_connection.execute(
                        text(
                            "delete from public.admin_audit_log "
                            "where object_type = 'preset' and object_id = :id"
                        ),
                        {"id": preset_id},
                    )
                    await author_connection.execute(
                        text("delete from public.prompt_presets where id = :id"),
                        {"id": preset_id},
                    )
        for connection in (admin_connection, author_connection):
            if connection is not None:
                with contextlib.suppress(Exception):
                    await connection.close()
