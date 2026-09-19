"""Порт frontend/e2e/agent.spec.ts."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import (
    create_test_agent,
    deliver_message,
    record_agent_event,
    script_agent_reply,
)

pytestmark = pytest.mark.e2e

PEER_CHAT_ID = 123


def _new_agent(
    api: httpx.Client,
    users: dict,
    name: str,
    state: str = "stopped",
    **kwargs: Any,
) -> str:
    return create_test_agent(api, users["full"].id, name, state, **kwargs)


class TestAgentPage:
    def test_rejects_invalid_id(self, persona_page: Callable[..., Page]) -> None:
        page = persona_page("full")
        page.goto("/agent/!!!")
        expect(page.get_by_text("Недопустимый ID агента")).to_be_visible()

    def test_tabs_switch_via_query(
        self, persona_page: Callable[..., Page], api: httpx.Client, users: dict
    ) -> None:
        agent_id = _new_agent(api, users, "Вкладки", phone_number="+79990000001")
        page = persona_page("full")
        page.goto(f"/agent/{agent_id}")
        expect(page.get_by_test_id("agent-tabs")).to_be_visible()

        page.get_by_test_id("agent-tab-logs").click()
        expect(page).to_have_url(re.compile(r"[?&]tab=logs"))
        expect(page.get_by_test_id("log-filter-full")).to_be_visible()

        page.get_by_test_id("agent-tab-memory").click()
        expect(page).to_have_url(re.compile(r"[?&]tab=memory"))
        expect(page.get_by_text("Память пуста")).to_be_visible()

        page.get_by_test_id("agent-tab-telegram").click()
        expect(page).to_have_url(re.compile(r"[?&]tab=telegram"))
        expect(page.get_by_text("+799******01")).to_be_visible()

    def test_log_filters_narrow_feed(
        self, persona_page: Callable[..., Page], api: httpx.Client, users: dict
    ) -> None:
        agent_id = _new_agent(api, users, "Логи", "running")
        script_agent_reply(api, agent_id, "Здравствуйте!")
        deliver_message(api, agent_id, PEER_CHAT_ID, "Привет")
        record_agent_event(
            api,
            agent_id,
            {
                "event_type": "tool.send_text_message",
                "status": "succeeded",
                "payload": {"turn_id": "turn-ok", "peer": str(PEER_CHAT_ID)},
                "result": {"success": True},
            },
        )
        record_agent_event(
            api,
            agent_id,
            {
                "event_type": "tool.get_dialogs",
                "status": "failed",
                "payload": {"turn_id": "turn-fail", "peer": str(PEER_CHAT_ID)},
                "error": "FloodWait",
            },
        )
        page = persona_page("full")
        page.goto(f"/agent/{agent_id}?tab=logs")
        expect(page.get_by_text("Здравствуйте!")).to_be_visible()
        expect(page.get_by_text("Просмотрел список диалогов")).to_be_visible()

        page.get_by_test_id("log-filter-chat").click()
        expect(page).to_have_url(re.compile(r"[?&]filter=chat"))
        expect(page.get_by_text("Здравствуйте!")).to_be_visible()
        expect(page.get_by_text("Просмотрел список диалогов")).to_have_count(0)

        page.get_by_test_id("log-filter-full").click()
        expect(page).not_to_have_url(re.compile(r"[?&]filter="))
        expect(page.get_by_text("Просмотрел список диалогов")).to_be_visible()

        page.get_by_test_id("log-filter-errors").click()
        expect(page).to_have_url(re.compile(r"[?&]filter=errors"))
        expect(page.get_by_text("Просмотрел список диалогов")).to_be_visible()
        expect(page.get_by_text("Здравствуйте!")).to_have_count(0)

        # The dashboard KPI «Ошибки» deep-links here pre-filtered.
        page.goto(f"/agent/{agent_id}?tab=logs&filter=errors")
        expect(page.get_by_text("Просмотрел список диалогов")).to_be_visible()
        expect(page.get_by_text("Здравствуйте!")).to_have_count(0)

    def test_stop_confirm_dialog(
        self, persona_page: Callable[..., Page], api: httpx.Client, users: dict
    ) -> None:
        agent_id = _new_agent(api, users, "Стоп", "running")
        page = persona_page("full")
        page.goto(f"/agent/{agent_id}?tab=actions")
        page.get_by_role("button", name="Остановить", exact=True).first.click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_text("Остановить агента?")).to_be_visible()
        dialog.get_by_role("button", name="Остановить", exact=True).click()
        expect(page.get_by_test_id("toast-container")).to_contain_text("Агент остановлен")
        expect(page.get_by_label("Статус агента: ОСТАНОВЛЕН")).to_be_visible()

    def test_send_message_modal_posts_trigger(
        self, persona_page: Callable[..., Page], api: httpx.Client, users: dict
    ) -> None:
        agent_id = _new_agent(api, users, "Триггер")
        page = persona_page("full")
        page.goto(f"/agent/{agent_id}?tab=actions")
        page.get_by_role("button", name="Отправить", exact=True).click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_text("Отправить сообщение")).to_be_visible()
        dialog.get_by_label("Получатель (peer)").fill("@someone")
        dialog.get_by_label("Текст сообщения").fill("Тестовый триггер")
        dialog.get_by_role("button", name="Отправить", exact=True).click()
        expect(page.get_by_test_id("toast-container")).to_contain_text("Сообщение отправлено")


class TestEmptyStates:
    def test_memory_empty(
        self, persona_page: Callable[..., Page], api: httpx.Client, users: dict
    ) -> None:
        agent_id = _new_agent(api, users, "Без памяти")
        page = persona_page("full")
        page.goto(f"/agent/{agent_id}?tab=memory")
        expect(page.get_by_text("Память пуста")).to_be_visible()

    def test_logs_empty(
        self, persona_page: Callable[..., Page], api: httpx.Client, users: dict
    ) -> None:
        agent_id = _new_agent(api, users, "Без логов")
        page = persona_page("full")
        page.goto(f"/agent/{agent_id}?tab=logs")
        expect(page.get_by_text("Нет записей")).to_be_visible()

    def test_telegram_missing_session(
        self, persona_page: Callable[..., Page], api: httpx.Client, users: dict
    ) -> None:
        agent_id = _new_agent(api, users, "Без сессии", with_telegram_session=False)
        page = persona_page("full")
        page.goto(f"/agent/{agent_id}?tab=telegram")
        expect(page.get_by_text("Telegram сессия не найдена")).to_be_visible()
