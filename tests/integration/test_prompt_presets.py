"""Справочник пресетов: сид на месте, читать можно, писать нельзя."""

from __future__ import annotations

import json

import asyncpg
import pytest

from mimic42.testing.slots import plain_dsn

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
