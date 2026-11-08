"""Порт frontend/e2e/auth.spec.ts."""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import quote

import httpx
import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.helpers import API_URL, APP_URL, create_test_agent, login_via_form, reset_backend

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

    def test_switching_accounts_hides_previous_agents_while_loading_and_on_error(
        self,
        page: Page,
        api: httpx.Client,
        users: dict,
        slot_info: tuple[str, str, dict],
    ) -> None:
        reset_backend(api, slot_info[0])
        agent_name = "Личный агент аккаунта A"
        agent_id = create_test_agent(api, users["full"].id, agent_name)
        login_via_form(page, users["full"])
        expect(page).to_have_url(re.compile(r"/dashboard$"), timeout=30_000)
        expect(page.get_by_test_id(f"agent-card-{agent_id}")).to_be_visible()
        document_id = page.evaluate("() => window.__accountSwitchDocument = crypto.randomUUID()")

        page.get_by_role("button", name="Выйти").click()
        expect(page.get_by_role("heading", name="Вход в систему")).to_be_visible()
        page.evaluate(
            """({name, cardId}) => {
                window.__accountSwitchLeaks = [];
                const inspect = (node) => {
                    if ((node.textContent || '').includes(name)
                        || (node.nodeType === Node.ELEMENT_NODE && (
                            node.matches(`[data-testid="${cardId}"]`)
                            || node.querySelector(`[data-testid="${cardId}"]`)
                        ))) {
                        window.__accountSwitchLeaks.push('previous account agent');
                    }
                };
                inspect(document.body);
                new MutationObserver((records) => {
                    for (const record of records) {
                        for (const node of record.addedNodes) inspect(node);
                        for (const node of record.removedNodes) inspect(node);
                        if (record.type === 'characterData') {
                            inspect(record.target);
                            if ((record.oldValue || '').includes(name)) {
                                window.__accountSwitchLeaks.push('previous account text');
                            }
                        }
                    }
                }).observe(document.body, {
                    childList: true,
                    subtree: true,
                    characterData: true,
                    characterDataOldValue: true,
                });
            }""",
            {"name": agent_name, "cardId": f"agent-card-{agent_id}"},
        )

        pending_agents: list[Route] = []
        agents_url = f"{API_URL}/api/v1/agents"
        fail_agents = False

        def fail_agent_request(route: Route) -> None:
            route.fulfill(
                status=503,
                headers={"Access-Control-Allow-Origin": APP_URL},
                json={"detail": "Unavailable"},
            )

        def handle_agents(route: Route) -> None:
            if fail_agents:
                fail_agent_request(route)
            else:
                pending_agents.append(route)

        page.route(agents_url, handle_agents)
        page.get_by_label("Email").fill(users["empty"].email)
        page.get_by_label("Пароль", exact=True).fill(users["empty"].password)
        with (
            page.expect_request(agents_url, timeout=30_000),
            page.expect_response(
                lambda response: (
                    "/auth/v1/token?grant_type=password" in response.url and response.status == 200
                ),
                timeout=30_000,
            ) as signed_in,
        ):
            page.get_by_role("button", name="Войти").click()
        assert signed_in.value.json()["user"]["id"] == users["empty"].id
        expect(page.get_by_test_id("step-indicator")).to_be_visible()
        assert pending_agents
        expect(page.get_by_test_id(f"agent-card-{agent_id}")).to_have_count(0)
        expect(page.get_by_text(agent_name, exact=True)).to_have_count(0)
        assert page.evaluate("window.__accountSwitchLeaks") == []
        assert page.evaluate("window.__accountSwitchDocument") == document_id

        fail_agents = True
        for route in pending_agents:
            with page.expect_response(agents_url) as failed_agents:
                fail_agent_request(route)
            assert failed_agents.value.finished() is None
        page.get_by_role("link", name="Главная", exact=True).click()
        expect(page).to_have_url(f"{APP_URL}/onboarding")
        expect(page.get_by_test_id("step-indicator")).to_be_visible()
        page.evaluate(
            "() => new Promise(resolve => requestAnimationFrame("
            "() => requestAnimationFrame(resolve)))"
        )
        expect(page.get_by_test_id(f"agent-card-{agent_id}")).to_have_count(0)
        expect(page.get_by_text(agent_name, exact=True)).to_have_count(0)
        assert page.evaluate("window.__accountSwitchLeaks") == []
        assert page.evaluate("window.__accountSwitchDocument") == document_id


class TestDashboardWithoutAgents:
    def test_forces_onboarding(self, persona_page: Callable[..., Page]) -> None:
        page = persona_page("empty")
        page.goto("/dashboard")
        expect(page).to_have_url(re.compile(r"/onboarding"))
        expect(page.get_by_test_id("step-indicator")).to_be_visible()


class TestFreshLoginWithRedirect:
    @pytest.mark.parametrize(
        "redirect",
        [
            "javascript:window.__unsafeLoginRedirect=true;void(0)",
            "https://auth-redirect.invalid/",
            "//auth-redirect.invalid/",
        ],
        ids=["javascript", "external", "protocol-relative"],
    )
    def test_login_rejects_unsafe_redirects(
        self,
        persona_page: Callable[..., Page],
        users: dict,
        redirect: str,
    ) -> None:
        page = persona_page("full", fresh=True)
        page.add_init_script("window.__unsafeLoginRedirect = false")
        page.route("**://auth-redirect.invalid/**", lambda route: route.abort())
        login_via_form(page, users["full"], f"/login?redirect={quote(redirect, safe='')}")
        expect(page).to_have_url(f"{APP_URL}/dashboard")
        expect(page.get_by_role("heading", name="Ваши агенты")).to_be_visible()
        assert page.evaluate("window.__unsafeLoginRedirect") is False

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
