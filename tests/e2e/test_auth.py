"""Порт frontend/e2e/auth.spec.ts."""

from __future__ import annotations

import re
from collections.abc import Callable

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import create_test_agent, login_via_form

pytestmark = pytest.mark.e2e


def seed_agents(api: httpx.Client, owner_id: str) -> tuple[str, str]:
    running = create_test_agent(api, owner_id, "Бегущий", "running")
    stopped = create_test_agent(api, owner_id, "Остановленный", "stopped")
    return running, stopped


class TestAuthenticatedNavigation:
    def test_login_redirects_authenticated_to_dashboard(
        self,
        persona_page: Callable[..., Page],
        api: httpx.Client,
        users: dict,
    ) -> None:
        seed_agents(api, users["full"].id)
        page = persona_page("full")
        page.goto("/login")
        expect(page).to_have_url(re.compile(r"/dashboard"))
        expect(page.get_by_role("heading", name="Ваши агенты")).to_be_visible()

    def test_dashboard_lists_agents_with_kpis(
        self,
        persona_page: Callable[..., Page],
        api: httpx.Client,
        users: dict,
    ) -> None:
        running, stopped = seed_agents(api, users["full"].id)
        page = persona_page("full")
        page.goto("/dashboard")
        expect(page.get_by_role("heading", name="Ваши агенты")).to_be_visible()
        expect(page.get_by_test_id(f"agent-card-{running}")).to_be_visible()
        expect(page.get_by_test_id(f"agent-card-{stopped}")).to_be_visible()
        expect(page.get_by_test_id("kpi-card")).to_have_count(4)

    def test_control_button_reflects_state(
        self,
        persona_page: Callable[..., Page],
        api: httpx.Client,
        users: dict,
    ) -> None:
        running, stopped = seed_agents(api, users["full"].id)
        page = persona_page("full")
        page.goto("/dashboard")

        # Вместо пары «Запустить»/«Стоп» — одна кнопка, подпись которой
        # меняется в зависимости от статуса агента (issue #47).
        running_card = page.get_by_test_id(f"agent-card-{running}")
        expect(
            running_card.get_by_role("button", name=re.compile("Запустить|Остановить"))
        ).to_have_count(1)
        expect(running_card.get_by_role("button", name="Остановить")).to_be_enabled()
        expect(running_card.get_by_role("button", name="Запустить")).to_have_count(0)

        stopped_card = page.get_by_test_id(f"agent-card-{stopped}")
        expect(
            stopped_card.get_by_role("button", name=re.compile("Запустить|Остановить"))
        ).to_have_count(1)
        expect(stopped_card.get_by_role("button", name="Запустить")).to_be_enabled()
        expect(stopped_card.get_by_role("button", name="Остановить")).to_have_count(0)


class TestSignOut:
    def test_logout_from_sidebar(
        self,
        persona_page: Callable[..., Page],
        api: httpx.Client,
        users: dict,
    ) -> None:
        # Реальный logout отзывает refresh token: общий storage state
        # «full» здесь использовать нельзя — он станет невалидным для
        # остальных тестов, поэтому логин происходит заново.
        seed_agents(api, users["full"].id)
        page = persona_page("full", fresh=True)
        login_via_form(page, users["full"])
        expect(page).to_have_url(re.compile(r"/dashboard"))
        expect(page.get_by_role("heading", name="Ваши агенты")).to_be_visible()
        page.get_by_role("button", name="Выйти").click()
        expect(page).to_have_url(re.compile(r"/login"))


class TestDashboardWithoutAgents:
    def test_forces_onboarding(self, persona_page: Callable[..., Page]) -> None:
        page = persona_page("empty")
        page.goto("/dashboard")
        expect(page).to_have_url(re.compile(r"/onboarding"))
        expect(page.get_by_test_id("step-indicator")).to_be_visible()


class TestFreshLoginWithRedirect:
    def test_login_lands_on_redirect_target(
        self,
        persona_page: Callable[..., Page],
        api: httpx.Client,
        users: dict,
    ) -> None:
        running = create_test_agent(api, users["full"].id, "Бегущий", "running")
        page = persona_page("full", fresh=True)
        page.goto("/dashboard")
        expect(page).to_have_url(re.compile(r"/login\?redirect=%2Fdashboard"))
        login_via_form(page, users["full"])
        expect(page).to_have_url(re.compile(r"/dashboard"))
        expect(page.get_by_test_id(f"agent-card-{running}").get_by_text("Бегущий")).to_be_visible()
