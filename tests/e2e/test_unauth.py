"""Порт frontend/e2e/unauth.spec.ts."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _url_is(page: Page, pattern: str) -> None:
    page.wait_for_url(re.compile(pattern))


class TestRedirects:
    def test_dashboard_redirects_to_login(self, page: Page) -> None:
        page.goto("/dashboard")
        _url_is(page, r"/login\?redirect=%2Fdashboard")

    def test_root_redirects_to_login(self, page: Page) -> None:
        page.goto("/")
        _url_is(page, r"/login")

    def test_onboarding_redirects_to_login(self, page: Page) -> None:
        page.goto("/onboarding")
        _url_is(page, r"/login\?redirect=%2Fonboarding")

    def test_agent_page_redirects_to_login(self, page: Page) -> None:
        page.goto("/agent/some-agent")
        _url_is(page, r"/login\?redirect=")


class TestPublicPages:
    def test_login_renders(self, page: Page) -> None:
        page.goto("/login")
        expect(page.get_by_role("heading", name="Вход в систему")).to_be_visible()

    def test_register_renders(self, page: Page) -> None:
        page.goto("/register")
        expect(page.get_by_role("heading", name="Создать аккаунт")).to_be_visible()

    def test_reset_password_renders(self, page: Page) -> None:
        page.goto("/reset-password")
        expect(page.get_by_role("heading", name="Восстановление пароля")).to_be_visible()

    def test_login_to_register_and_back(self, page: Page) -> None:
        page.goto("/login")
        page.get_by_role("link", name="Зарегистрироваться").click()
        _url_is(page, r"/register")
        page.get_by_role("link", name="Войти").click()
        _url_is(page, r"/login")

    def test_login_to_reset_password_and_back(self, page: Page) -> None:
        page.goto("/login")
        page.get_by_role("link", name="Забыли пароль?").click()
        _url_is(page, r"/reset-password")
        page.get_by_role("link", name="Вернуться ко входу").click()
        _url_is(page, r"/login")

    def test_password_visibility_toggle(self, page: Page) -> None:
        page.goto("/login")
        password = page.get_by_label("Пароль", exact=True)
        expect(password).to_have_attribute("type", "password")
        page.get_by_role("button", name="Показать пароль").click()
        expect(password).to_have_attribute("type", "text")
        page.get_by_role("button", name="Скрыть пароль").click()
        expect(password).to_have_attribute("type", "password")

    def test_login_validation_errors(self, page: Page) -> None:
        page.goto("/login")
        page.get_by_role("button", name="Войти").click()
        expect(page.get_by_text("Введите корректный email")).to_be_visible()
        expect(page.get_by_text("Пароль обязателен")).to_be_visible()

    def test_register_mismatch_error(self, page: Page) -> None:
        page.goto("/register")
        page.get_by_label("Email").fill("user@example.com")
        page.get_by_label("Пароль", exact=True).fill("password123")
        page.get_by_label("Повторите пароль").fill("different123")
        page.get_by_role("button", name="Создать аккаунт").click()
        expect(page.get_by_text("Пароли не совпадают")).to_be_visible()

    def test_reset_password_email_validation(self, page: Page) -> None:
        page.goto("/reset-password")
        page.get_by_placeholder("Email").fill("not-an-email")
        page.get_by_role("button", name="Отправить ссылку").click()
        expect(page.get_by_text("Введите корректный email")).to_be_visible()

    def test_update_password_session_check(self, page: Page) -> None:
        page.goto("/update-password")
        expect(page.get_by_text("Проверка сессии...")).to_be_visible()
        expect(page.get_by_placeholder("Новый пароль")).to_have_count(0)

    def test_auth_callback_without_code(self, page: Page) -> None:
        page.goto("/api/auth/callback")
        _url_is(page, r"/login\?error=auth_callback_failed")


class TestSecurityHeaders:
    def test_login_headers_and_csp(self, page: Page) -> None:
        response = page.goto("/login")
        assert response is not None
        assert response.ok
        headers = response.headers
        assert headers["x-frame-options"] == "DENY"
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "default-src 'self'" in headers["content-security-policy"]
        assert "frame-ancestors" in headers["content-security-policy"]
