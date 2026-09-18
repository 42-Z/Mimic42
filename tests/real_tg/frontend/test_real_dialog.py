"""Реальный диалог через дашборд: проверяющий пишет мимику, ответ виден в UI."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, expect

from mimic42.testing.real_tg.checker import SyncChecker
from tests.real_tg.frontend.conftest import (
    ACTION_TIMEOUT_MS,
    APP_URL,
    NAVIGATION_TIMEOUT_MS,
)

pytestmark = pytest.mark.real_tg


def test_dialog_visible_in_dashboard(
    browser: Browser,
    real_auth: str,
    sync_checker: SyncChecker,
    mimic_agents: list[tuple[str, str]],
) -> None:
    agent_id, phone = mimic_agents[0]
    sync_checker.ensure_contact(phone)
    context = browser.new_context(base_url=APP_URL, storage_state=real_auth)
    context.set_default_timeout(ACTION_TIMEOUT_MS)
    context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
    page = context.new_page()
    try:
        page.goto(f"/agent/{agent_id}?tab=logs")
        reply = sync_checker.send_and_wait_reply(phone, "Привет из реального теста", timeout=300)
        assert reply.strip()
        # Лента не обязана обновляться live: перечитываем страницу, как это
        # сделал бы человек, и проверяем, что входящее и ответ видны.
        page.reload()
        # Один и тот же текст встречается в ленте дважды (входящее и блок
        # триггера), поэтому проверяем первый видимый элемент.
        expect(page.get_by_text("Привет из реального теста").first).to_be_visible(timeout=180_000)
        expect(page.get_by_text(reply[:40]).first).to_be_visible(timeout=180_000)
    finally:
        context.close()
