"""Реальный диалог через дашборд: проверяющий пишет мимику, ответ виден в UI.

Две гонки, которые этот тест ловит сам (и падал на них вживую):

1. ``send_and_wait_reply`` возвращает первое входящее — а агент сначала может
   отправить tool-сообщение (``send_text_message``), и основной ответ приходит
   позже. Tool-текст лента абзацем не рендерится, поэтому текст ответа берём
   из сохранённого турна, а не из чекера.
2. Строки турна пишутся в базу только по его завершении: reload раньше этого
   момента не покажет ни входящее, ни ответ. Перед reload ждём сохранённый
   ответ через API.

Маркер входящего уникален для прогона: в ленте накопились дубли одинаковых
«Привет из реального теста» из прошлых прогонов, и без уникальности ``.first``
находил вчерашний турн.
"""

from __future__ import annotations

import time

import httpx
import pytest
from playwright.sync_api import Browser, expect

from mimic42.testing.real_tg.checker import SyncChecker
from tests.real_tg.frontend.conftest import (
    ACTION_TIMEOUT_MS,
    API_URL,
    APP_URL,
    NAVIGATION_TIMEOUT_MS,
)
from tests.real_tg.frontend.helpers import fetch_token

pytestmark = pytest.mark.real_tg

WAIT_STORED_SECONDS = 180


def _wait_for_stored_reply(agent_id: str, marker: str) -> str:
    """Ждёт, пока турн с маркером сохранится, и возвращает текст ответа."""
    token = fetch_token()
    deadline = time.monotonic() + WAIT_STORED_SECONDS
    while time.monotonic() < deadline:
        response = httpx.get(
            f"{API_URL}/api/v1/agents/{agent_id}/conversation",
            params={"limit": 50},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        response.raise_for_status()
        for turn in response.json().get("turns", []):
            if marker in str(turn.get("incoming") or ""):
                outgoing = str(turn.get("outgoing") or "").strip()
                if outgoing:
                    return outgoing
        time.sleep(2)
    raise AssertionError(f"Турн «{marker}» не сохранился за {WAIT_STORED_SECONDS}с")


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
        marker = f"Привет из реального теста {int(time.time())}"
        reply = sync_checker.send_and_wait_reply(phone, marker, timeout=300)
        assert reply.strip()
        # Текст ответа для ленты — из сохранённого турна: чекер мог поймать
        # tool-сообщение, а reload раньше записи строк ничего не покажет.
        stored_reply = _wait_for_stored_reply(agent_id, marker)
        page.reload()
        expect(page.get_by_text(marker).first).to_be_visible(timeout=180_000)
        expect(page.get_by_text(stored_reply[:40]).first).to_be_visible(timeout=180_000)
    finally:
        context.close()
