"""Справочник пресетов: сид на месте, читать можно, писать нельзя."""

from __future__ import annotations

import json
from uuid import UUID

import asyncpg
import pytest

from mimic42.testing.slots import SLOTS, plain_dsn

EXPECTED_SLUGS = {"rage_comments", "sasavot_fan", "magnum_normie", "battalion"}


async def test_presets_are_seeded(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        rows = await connection.fetch(
            "select slug, title, summary, body, sort_order "
            "from public.prompt_presets where is_active order by sort_order"
        )
    finally:
        await connection.close()

    assert {row["slug"] for row in rows} == EXPECTED_SLUGS
    assert [row["sort_order"] for row in rows] == [1, 2, 3, 4]
    for row in rows:
        assert row["title"].strip()
        assert row["summary"].strip()
        # Тексты пресетов длинные: короткая строка означает обрезанный сид.
        assert len(row["body"]) > 300


async def test_authenticated_reads_but_cannot_write(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        async with connection.transaction():
            await connection.execute("set local role authenticated")

            assert await connection.fetchval("select count(*) from public.prompt_presets") == 4

            # asyncpg по умолчанию отдаёт jsonb строкой — разбираем её сами.
            rage = json.loads(
                await connection.fetchval(
                    "select settings from public.prompt_presets where slug = 'rage_comments'"
                )
            )
            assert "send_text_message" in rage["enabled_tools"]

            # Политики insert нет: SQLSTATE 42501, будь то RLS или отсутствие права.
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with connection.transaction():
                    await connection.execute(
                        "insert into public.prompt_presets (slug, title, summary, body) "
                        "values ('mine', 'Мой', 'мой пресет', 'текст')"
                    )
    finally:
        await connection.close()


async def test_rage_comments_defines_tool_allowlist(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        settings = json.loads(
            await connection.fetchval(
                "select settings from public.prompt_presets where slug = 'rage_comments'"
            )
        )
    finally:
        await connection.close()

    assert isinstance(settings, dict)
    enabled = settings["enabled_tools"]
    assert set(enabled) == {
        "get_dialogs",
        "get_messages",
        "search_messages",
        "get_discussion_messages",
        "join_channel_discussion",
        "view_image",
        "send_text_message",
        "send_chat_action",
        "send_reaction",
        "get_message_reactions",
        "mark_chat_as_read",
        "get_chat_info",
        "check_admin_permissions",
        "get_message_buttons",
        "click_inline_button",
        "start_bot",
    }
    # Разрушительное администрирование и приватность комментатору недоступны.
    assert "delete_channel" not in enabled
    assert "set_privacy_settings" not in enabled


def _persona(key: str) -> UUID:
    """Готовый auth-аккаунт персоны слота: его auth.users и профиль уже в базе."""
    return SLOTS[0].persona(key).user_id


async def _act_as_user(connection: asyncpg.Connection, user_id: UUID) -> None:
    """Роль authenticated + клеймы пользователя — как их видит PostgREST."""
    await connection.execute("set local role authenticated")
    await connection.execute(
        "select set_config('request.jwt.claims', $1, true)",
        f'{{"sub":"{user_id}","role":"authenticated"}}',
    )
    await connection.execute("select set_config('request.jwt.claim.sub', $1, true)", str(user_id))


# RLS-отказ (42501) и raise в триггере (P0001) для клиента выглядят одинаково.
DENIED = (asyncpg.RaiseError, asyncpg.InsufficientPrivilegeError)


async def _cleanup_personas(connection: asyncpg.Connection, *user_ids: UUID) -> None:
    """Убрать пресеты персон: персоны общие, мусор в них копиться не должен."""
    for user_id in user_ids:
        await connection.execute("delete from public.prompt_presets where owner_id = $1", user_id)


async def test_owner_creates_draft_and_reads_it(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        owner = _persona("empty")
        async with connection.transaction():
            await _act_as_user(connection, owner)
            preset_id = await connection.fetchval(
                "insert into public.prompt_presets (title, summary, body) "
                "values ('Мой пресет', 'мой характер', 'текст характера') "
                "returning id"
            )
            row = await connection.fetchrow(
                "select owner_id, published_at, slug, is_active "
                "from public.prompt_presets where id = $1",
                preset_id,
            )
            assert row["owner_id"] == owner
            assert row["published_at"] is None
            assert row["is_active"] is True
            assert row["slug"].startswith("u_")
    finally:
        await _cleanup_personas(connection, owner)
        await connection.close()


async def test_official_rows_are_untouchable(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        async with connection.transaction():
            await _act_as_user(connection, _persona("empty"))
            # RLS не кидает ошибку, а тихо сужает выборку: официальная строка
            # не изменится и не удалится, сколько клиент ни старается.
            status = await connection.execute(
                "update public.prompt_presets set title = 'взломано' where slug = 'rage_comments'"
            )
            assert status == "UPDATE 0"
            status = await connection.execute(
                "delete from public.prompt_presets where slug = 'rage_comments'"
            )
            assert status == "DELETE 0"
            # slug не выдан поколоночным грантом — отказ ещё на праве колонки.
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(
                    "update public.prompt_presets set slug = 'my_own' where slug = 'rage_comments'"
                )
    finally:
        await connection.close()


async def test_draft_is_hidden_from_others(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        draft_ids: list[UUID] = []
        async with connection.transaction():
            await _act_as_user(connection, _persona("empty"))
            draft_ids.append(
                await connection.fetchval(
                    "insert into public.prompt_presets (title, summary, body) "
                    "values ('Секретный', 'черновик', 'текст') returning id"
                )
            )
        async with connection.transaction():
            await _act_as_user(connection, _persona("full"))
            count = await connection.fetchval(
                "select count(*) from public.prompt_presets where title = 'Секретный'"
            )
            assert count == 0
    finally:
        await _cleanup_personas(connection, _persona("empty"))
        await connection.close()


async def test_publish_makes_preset_visible_and_editable(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        preset_id: UUID | None = None
        async with connection.transaction():
            await _act_as_user(connection, _persona("empty"))
            preset_id = await connection.fetchval(
                "insert into public.prompt_presets (title, summary, body) "
                "values ('Витринный', 'для всех', 'старый текст') returning id"
            )
            await connection.execute(
                "update public.prompt_presets set published_at = now() where id = $1",
                preset_id,
            )
        async with connection.transaction():
            await _act_as_user(connection, _persona("full"))
            body = await connection.fetchval(
                "select body from public.prompt_presets where id = $1", preset_id
            )
            assert body == "старый текст"
            count = await connection.fetchval(
                "select count(*) from public.prompt_presets where published_at is not null"
            )
            # Виден ровно один выложенный пресет — только что наш.
            assert count == 1
        async with connection.transaction():
            await _act_as_user(connection, _persona("empty"))
            await connection.execute(
                "update public.prompt_presets set body = 'новый текст' where id = $1",
                preset_id,
            )
        async with connection.transaction():
            await _act_as_user(connection, _persona("full"))
            body = await connection.fetchval(
                "select body from public.prompt_presets where id = $1", preset_id
            )
            assert body == "новый текст"
    finally:
        await _cleanup_personas(connection, _persona("empty"))
        await connection.close()


async def test_owner_cannot_reassign_owner_or_slug(test_dsn: str) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        async with connection.transaction():
            await _act_as_user(connection, _persona("empty"))
            preset_id = await connection.fetchval(
                "insert into public.prompt_presets (title, summary, body) "
                "values ('Переезд', 'трой', 'текст') returning id"
            )
        # Каждый отказ — в своей транзакции: после abort транзакция мертва.
        async with connection.transaction():
            await _act_as_user(connection, _persona("empty"))
            # Смена owner_id нарушает with check политики (42501).
            with pytest.raises(DENIED):
                await connection.execute(
                    "update public.prompt_presets set owner_id = gen_random_uuid() where id = $1",
                    preset_id,
                )
        async with connection.transaction():
            await _act_as_user(connection, _persona("empty"))
            # slug не в поколоночном гранте — отказ ещё на праве колонки.
            with pytest.raises(DENIED):
                await connection.execute(
                    "update public.prompt_presets set slug = 'hand_made' where id = $1",
                    preset_id,
                )
    finally:
        await _cleanup_personas(connection, _persona("empty"))
        await connection.close()
