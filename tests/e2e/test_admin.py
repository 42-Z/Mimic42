"""Сквозные сценарии закрытой админки; только тестовые персоны и API-моки."""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import httpx
import pytest
from playwright.sync_api import Page, Request, Response, Route, expect

from tests.e2e.helpers import E2EUser, delete_test_official_preset, set_admin_role

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
REVIEW_DIR = ROOT / ".impeccable" / "review"


def _capture(page: Page, name: str) -> None:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(
        path=str(REVIEW_DIR / name),
        animations="disabled",
    )


def test_guest_is_redirected_to_login_for_admin(page: Page) -> None:
    page.goto("/admin")
    expect(page).to_have_url(re.compile(r"/login\?redirect=%2Fadmin"))


def test_non_admin_without_agents_sees_denial_not_onboarding(
    persona_page: Callable[..., Page],
    admin_role: Callable[[str, bool], AbstractContextManager[None]],
    users: dict[str, E2EUser],
) -> None:
    empty_user = users["empty"]
    with admin_role(empty_user.id, False):
        page = persona_page("empty")
        page.goto("/admin")

        expect(page.get_by_role("heading", name="Нет доступа")).to_be_visible()
        expect(page.get_by_role("link", name="К своим агентам")).to_be_visible()
        expect(page).to_have_url(re.compile(r"/admin$"))
        expect(page.get_by_role("heading", name="Общая статистика")).to_have_count(0)


def test_admin_without_agents_moderates_and_loses_access_after_revoke(
    persona_page: Callable[..., Page],
    admin_role: Callable[[str, bool], AbstractContextManager[None]],
    slot_info: tuple[str, str, dict[str, E2EUser]],
    users: dict[str, E2EUser],
    api: httpx.Client,
) -> None:
    empty_user = users["empty"]
    slot = slot_info[0]
    authorization_headers: list[str] = []
    created_preset_ids: list[str] = []
    page = persona_page("empty")

    def capture_bearer(request: Request) -> None:
        if request.url.endswith("/api/v1/me"):
            authorization = request.headers.get("authorization")
            if authorization:
                authorization_headers.append(authorization)

    def capture_created_preset(response: Response) -> None:
        if (
            response.request.method == "POST"
            and response.url.endswith("/api/v1/admin/presets")
            and response.status == 201
        ):
            created_preset_ids.append(str(response.json()["id"]))

    page.on("request", capture_bearer)
    page.on("response", capture_created_preset)

    with admin_role(empty_user.id, True):
        try:
            # SSR boundary starts closed and reveals the real overview only after /me.
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.goto("/admin", wait_until="domcontentloaded")
            expect(page.get_by_test_id("admin-boundary-loading")).to_be_visible()
            _capture(page, "admin-access-loading-desktop.png")
            expect(page.get_by_role("heading", name="Общая статистика")).to_be_visible()
            expect(page.get_by_role("link", name="Администрирование")).to_be_visible()
            expect(page.get_by_test_id("current-day-note")).to_be_visible()
            expect(page.get_by_test_id("stat-errors")).to_be_visible()
            _capture(page, "admin-overview-desktop.png")
            page.get_by_test_id("activity-chart").scroll_into_view_if_needed()
            _capture(page, "admin-overview-charts-desktop.png")

            page.set_viewport_size({"width": 390, "height": 844})
            page.reload(wait_until="domcontentloaded")
            expect(page.get_by_test_id("admin-boundary-loading")).to_be_visible()
            _capture(page, "admin-access-loading-mobile.png")
            expect(page.get_by_role("heading", name="Общая статистика")).to_be_visible()
            expect(page.get_by_test_id("stat-users")).to_be_visible()
            expect(page.get_by_test_id("stat-errors")).to_be_visible()
            _capture(page, "admin-overview-mobile.png")
            page.get_by_test_id("stat-errors").scroll_into_view_if_needed()
            _capture(page, "admin-overview-metrics-mobile.png")
            page.get_by_test_id("activity-chart").scroll_into_view_if_needed()
            _capture(page, "admin-overview-activity-mobile.png")
            page.get_by_test_id("errors-chart").scroll_into_view_if_needed()
            _capture(page, "admin-overview-errors-mobile.png")

            # Персона пустого слота не владеет агентами, но администратору
            # доступен список профилей и честная строка с нулём мимиков.
            email_search = urlencode({"q": empty_user.email})
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.goto(f"/admin/users?{email_search}")
            expect(page.get_by_role("button", name="Мимики (0)")).to_be_visible()
            expect(page.get_by_text(empty_user.email, exact=True)).to_be_visible()
            _capture(page, "admin-users-desktop.png")

            page.get_by_role("button", name="Мимики (0)").click()
            expect(page.get_by_role("dialog", name="Мимики пользователя")).to_be_visible()
            expect(page.get_by_text("У пользователя пока нет мимиков")).to_be_visible()
            page.set_viewport_size({"width": 390, "height": 844})
            _capture(page, "admin-users-mobile.png")
            page.get_by_role("button", name="Закрыть").click()

            # Для responsive-снимков длинных строк используем только синтетические данные.
            visual_user_id = "55555555-5555-4555-8555-555555555555"
            visual_email = f"visual-{('long-data-' * 8)}@example.test"
            visual_name = "Синтетический профиль с длинным именем " * 2
            visual_profile = {
                "user_id": visual_user_id,
                "email": visual_email,
                "display_name": visual_name,
                "created_at": "2026-10-18T12:00:00Z",
                "agents_total": 6,
                "states": {"running": 1, "stopped": 5},
            }
            visual_agents = [
                {
                    "agent_id": f"{index:08x}-5555-4555-8555-555555555555",
                    "name": f"Тестовый мимик {index}",
                    "llm_model": f"openrouter/{'long-model-name-' * 6}{index}",
                    "state": "running" if index == 6 else "stopped",
                }
                for index in range(1, 7)
            ]

            def mock_visual_user_data(route: Route) -> None:
                parsed = urlsplit(route.request.url)
                if parsed.path == "/api/v1/admin/users":
                    route.fulfill(
                        json={
                            "items": [visual_profile],
                            "total": 1,
                            "page": 1,
                            "page_size": 25,
                        }
                    )
                    return
                if parsed.path == f"/api/v1/admin/users/{visual_user_id}":
                    page_number = int(parse_qs(parsed.query).get("page", ["1"])[0])
                    page_agents = visual_agents[:5] if page_number == 1 else visual_agents[5:]
                    route.fulfill(
                        json={
                            "profile": visual_profile,
                            "agents": {
                                "items": page_agents,
                                "total": len(visual_agents),
                                "page": page_number,
                                "page_size": 5,
                            },
                        }
                    )
                    return
                route.continue_()

            page.route("**/api/v1/admin/users**", mock_visual_user_data)
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.goto("/admin/users?q=visual")
            expect(page.get_by_text(visual_email, exact=True)).to_be_visible()
            _capture(page, "admin-users-long-desktop.png")

            page.set_viewport_size({"width": 390, "height": 844})
            _capture(page, "admin-users-long-mobile.png")
            page.get_by_role("button", name="Мимики (6)").click()
            dialog = page.get_by_role("dialog", name="Мимики пользователя")
            expect(dialog.get_by_text(visual_agents[0]["name"])).to_be_visible()
            page.get_by_role("button", name="Следующая страница").click()
            expect(dialog.get_by_text(visual_agents[-1]["name"])).to_be_visible()
            _capture(page, "admin-users-details-mobile.png")
            page.get_by_role("button", name="Закрыть").click()

            # Ошибка не подменяется пустым успешным списком.
            page.unroute("**/api/v1/admin/users**", mock_visual_user_data)
            page.set_viewport_size({"width": 1440, "height": 1000})

            def failed_users(route: Route) -> None:
                route.fulfill(status=503, json={"detail": "Администрирование временно недоступно"})

            page.route("**/api/v1/admin/users**", failed_users)
            page.goto("/admin/users?q=visual-error")
            users_region = page.get_by_role("region", name="Пользователи")
            expect(users_region.get_by_role("alert")).to_contain_text(
                "Не удалось загрузить пользователей"
            )
            _capture(page, "admin-users-error-desktop.png")
            page.unroute("**/api/v1/admin/users**", failed_users)

            fixture_title = f"E2E admin fixture: {uuid4().hex[:10]}"
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.goto("/admin/presets")
            expect(page.get_by_role("heading", name="Пресеты")).to_be_visible()
            page.get_by_role("button", name="Новый официальный пресет").click()
            editor = page.get_by_role("dialog", name="Новый пресет")
            editor.get_by_label("Название").fill(fixture_title)
            editor.get_by_label("Короткое описание").fill("Synthetic E2E fixture")
            editor.get_by_label("Промпт").fill("Synthetic prompt for the admin test.")
            editor.get_by_test_id("preset-editor-save").click()
            expect(editor).to_be_hidden()

            assert len(created_preset_ids) == 1, (
                "Не удалось захватить UUID созданного fixture-пресета"
            )
            assert authorization_headers, (
                "Не перехватили Authorization header административного API"
            )

            page.get_by_label("Поиск пресетов").fill(fixture_title)
            preset_row = page.get_by_test_id(f"admin-preset-row-{created_preset_ids[0]}")
            expect(preset_row).to_be_visible()
            order_input = preset_row.get_by_role("spinbutton", name=f"Порядок: {fixture_title}")
            order_input.fill("-23")
            preset_row.get_by_role("button", name=f"Сохранить порядок: {fixture_title}").click()
            expect(order_input).to_have_value("-23")
            _capture(page, "admin-presets-desktop.png")

            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.get_by_role("heading", name="Пресеты")).to_be_visible()
            expect(preset_row).to_be_visible()
            _capture(page, "admin-presets-mobile.png")
            preset_row.get_by_role("button", name=f"Скрыть пресет: {fixture_title}").click()
            hide_dialog = page.get_by_role("dialog", name="Скрыть официальный пресет?")
            expect(hide_dialog).to_contain_text("исчезнет из каталога пользователей")
            hide_dialog.get_by_role("button", name="Скрыть пресет").click()
            expect(preset_row.get_by_text("Скрыт")).to_be_visible()
            preset_row.get_by_role("button", name=f"Вернуть в каталог: {fixture_title}").click()
            expect(preset_row.get_by_text("Виден")).to_be_visible()

            telegram_writes: list[dict[str, object]] = []

            def mock_telegram_settings(route: Route) -> None:
                if route.request.method == "GET":
                    route.fulfill(
                        json={
                            "api_id": 12345,
                            "has_api_hash": True,
                            "source": "environment",
                            "updated_at": None,
                            "updated_by": None,
                        }
                    )
                    return
                if route.request.method == "PUT":
                    payload = route.request.post_data_json
                    if not isinstance(payload, dict) or not isinstance(payload.get("api_id"), int):
                        route.fulfill(status=400, json={"detail": "Invalid test payload"})
                        return
                    api_id = payload["api_id"]
                    api_hash = payload.get("api_hash")
                    if not isinstance(api_hash, str):
                        route.fulfill(status=400, json={"detail": "Invalid test payload"})
                        return
                    telegram_writes.append({"api_id": api_id, "api_hash": api_hash})
                    route.fulfill(
                        json={
                            "api_id": api_id,
                            "has_api_hash": True,
                            "source": "database",
                            "updated_at": "2026-10-19T12:00:00Z",
                            "updated_by": empty_user.id,
                        }
                    )
                    return
                route.continue_()

            page.unroute("**/api/v1/admin/users**")
            page.route("**/api/v1/admin/telegram-settings*", mock_telegram_settings)
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.goto("/admin/telegram")
            expect(page.get_by_label("API ID")).to_have_value("12345")
            expect(page.get_by_label("API HASH")).to_be_empty()
            page.get_by_label("API ID").fill("67890")
            page.get_by_label("API HASH").fill("synthetic-route-mocked-hash")
            page.get_by_role("button", name="Сохранить настройки").click()
            expect(page.get_by_text("Настройки Telegram сохранены.")).to_be_visible()
            expect(page.get_by_label("API HASH")).to_be_empty()
            assert telegram_writes == [{"api_id": 67890, "api_hash": "synthetic-route-mocked-hash"}]
            _capture(page, "admin-telegram-desktop.png")

            page.set_viewport_size({"width": 390, "height": 844})
            _capture(page, "admin-telegram-mobile.png")

            set_admin_role(api, slot, empty_user.id, False)
            page.unroute("**/api/v1/admin/telegram-settings*")
            page.reload()
            expect(page.get_by_role("heading", name="Нет доступа")).to_be_visible()
            forbidden = api.get(
                "/api/v1/admin/users",
                headers={"Authorization": authorization_headers[0]},
            )
            assert forbidden.status_code == 403

            page.goto("/onboarding")
            expect(page.get_by_role("heading", name="Как зовут вашего агента?")).to_be_visible()

            regular_user_page = persona_page("full")
            regular_user_page.goto("/presets")
            expect(regular_user_page.get_by_role("heading", name="Пресеты")).to_be_visible()
        finally:
            for preset_id in created_preset_ids:
                delete_test_official_preset(api, preset_id)
