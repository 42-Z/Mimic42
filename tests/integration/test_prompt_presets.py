"""Справочник пресетов: сид на месте, читать можно, писать нельзя."""

from __future__ import annotations

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

            # Политики insert нет: SQLSTATE 42501, будь то RLS или отсутствие права.
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with connection.transaction():
                    await connection.execute(
                        "insert into public.prompt_presets (slug, title, summary, body) "
                        "values ('mine', 'Мой', 'мой пресет', 'текст')"
                    )
    finally:
        await connection.close()
