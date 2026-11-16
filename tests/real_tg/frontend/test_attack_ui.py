"""Режим атаки в дашборде: черновик, список и правка через настоящий API."""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import re
from uuid import UUID, uuid4

import asyncpg
import pytest
from playwright.sync_api import Browser, expect

from mimic42.testing.slots import plain_dsn
from tests.real_tg.frontend.conftest import (
    ACTION_TIMEOUT_MS,
    APP_URL,
    NAVIGATION_TIMEOUT_MS,
)

pytestmark = pytest.mark.real_tg


def _delete_attack(attack_id: str) -> None:
    async def run() -> None:
        conn = await asyncpg.connect(
            plain_dsn(os.environ["DATABASE_CONNECTION_STRING"]), timeout=30
        )
        try:
            await conn.execute("delete from attacks where id = $1::uuid", UUID(attack_id))
        finally:
            await conn.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(asyncio.run, run()).result(timeout=120)


def test_attack_draft_is_created_and_edited_in_dashboard(browser: Browser, real_auth: str) -> None:
    title = f"Атака UI {uuid4()}"
    edited = f"{title} — правка"
    link = "https://t.me/mimic42_ui/1"
    context = browser.new_context(base_url=APP_URL, storage_state=real_auth)
    context.set_default_timeout(ACTION_TIMEOUT_MS)
    context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
    page = context.new_page()
    attack_id: str | None = None
    try:
        page.goto("/attacks")
        expect(page.get_by_role("heading", name="Атаки")).to_be_visible()
        expect(page.get_by_role("link", name="Создать атаку")).to_be_visible()
        # Прямой переход: клик по Next-ссылке до гидратации иногда остаётся
        # на месте, а проверяется здесь форма и API, не роутер.
        page.goto("/attacks/new")

        expect(page.get_by_role("heading", name="Новая атака")).to_be_visible()
        page.get_by_label("Ссылка на пост").fill(link)
        page.get_by_label("Название").fill(title)
        page.locator("textarea").first.fill("Первый текст из живого дашборда")
        page.get_by_label("Лимит сообщений").fill("2")
        page.get_by_role("button", name="Сохранить черновик").click()

        # Первый переход компилирует /attacks/[id], а middleware проверяет
        # сессию в Supabase: 15 секунд на это не всегда хватает.
        expect(page).to_have_url(re.compile(r"/attacks/[0-9a-f-]+$"), timeout=120_000)
        attack_id = page.url.rsplit("/", 1)[-1]
        expect(page.get_by_role("heading", name=title)).to_be_visible()
        expect(page.get_by_text("Черновик").first).to_be_visible()
        expect(page.get_by_text(link)).to_be_visible()

        page.goto("/attacks")
        active = page.get_by_test_id("active-attacks")
        expect(active.get_by_text(title)).to_be_visible()
        active.get_by_text(title).click()
        expect(page.get_by_role("heading", name=title)).to_be_visible()

        page.get_by_role("button", name="Редактировать").click()
        expect(page.get_by_role("heading", name="Редактирование атаки")).to_be_visible()
        page.get_by_label("Название").fill(edited)
        page.get_by_role("button", name="Сохранить изменения").click()
        expect(page.get_by_role("heading", name=edited)).to_be_visible()
        expect(page.get_by_text("Первый текст из живого дашборда")).to_be_visible()
    finally:
        page.close()
        context.close()
        if attack_id is not None:
            _delete_attack(attack_id)
