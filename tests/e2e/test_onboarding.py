"""Порт frontend/e2e/onboarding.spec.ts: файл серийный, общий фейк входа.

По умолчанию pytest гоняет один процесс — серийность внутри файла
сохраняется (см. пояснение в TS-версии: общий onboarding-аккаунт).
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import (
    current_draft_id,
    hide_onboarding_drafts,
    reset_onboarding_login,
    script_onboarding_login,
)

pytestmark = pytest.mark.e2e

SOUL_TEXT = "0123456789性格テスト: спокойный помощник, отвечает коротко и по делу каждый день"


def _wait_code_cleared(page: Page, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.evaluate("() => sessionStorage.getItem('_m42_tc_state')") is None:
            return
        time.sleep(0.5)
    raise AssertionError("Код остался в sessionStorage после авторизации")


def _walk_to_credentials(page: Page, name: str, soul: str) -> None:
    page.goto("/onboarding")
    page.get_by_label("Имя агента").fill(name)
    page.get_by_role("button", name="Продолжить →").click()
    page.get_by_label("SOUL.md").fill(soul)
    page.get_by_role("button", name="Продолжить →").click()


class TestWholeFlow:
    def test_walks_the_whole_flow(
        self,
        persona_page: Callable[..., Page],
        api: httpx.Client,
        users: dict,
    ) -> None:
        flow = users["flow"]
        reset_onboarding_login(api)
        script_onboarding_login(api, "12345")
        hide_onboarding_drafts(api, flow.id)
        page = persona_page("flow")

        page.goto("/onboarding")
        expect(page.get_by_role("heading", name="Как зовут вашего агента?")).to_be_visible()

        page.get_by_role("button", name="Продолжить →").click()
        expect(page.get_by_text("Имя агента обязательно")).to_be_visible()
        page.get_by_label("Имя агента").fill("Тест")
        page.get_by_role("button", name="Продолжить →").click()
        expect(page.get_by_role("heading", name="Характер агента")).to_be_visible()

        page.get_by_label("SOUL.md").fill("коротко")
        page.get_by_role("button", name="Продолжить →").click()
        expect(page.get_by_text("Характер должен содержать хотя бы 10 символов")).to_be_visible()
        page.get_by_label("SOUL.md").fill(SOUL_TEXT)
        page.get_by_role("button", name="Продолжить →").click()
        expect(page.get_by_role("heading", name="Подключение Telegram")).to_be_visible()

        draft_id = current_draft_id(api, flow.id)

        page.get_by_label("Номер телефона").fill("123")
        page.get_by_role("button", name="Получить код →").click()
        expect(page.get_by_text("Номер телефона должен быть в формате E.164")).to_be_visible()
        page.get_by_label("Номер телефона").fill("+79990000000")
        page.get_by_role("button", name="Получить код →").click()
        expect(page.get_by_role("heading", name="Код из Telegram")).to_be_visible()

        page.get_by_label("Код подтверждения").fill("12")
        page.get_by_role("button", name="Подтвердить →").click()
        expect(page.get_by_text("Код должен содержать минимум 5 цифр")).to_be_visible()
        page.get_by_label("Код подтверждения").fill("12345")
        page.get_by_role("button", name="Подтвердить →").click()
        expect(page.get_by_role("heading", name="Всё готово!")).to_be_visible()
        _wait_code_cleared(page)

        page.get_by_role("button", name="Создать агента").click()
        page.wait_for_url("**/dashboard", timeout=15_000)
        expect(page.get_by_test_id(f"agent-card-{draft_id}").get_by_text("Тест")).to_be_visible()


class TestTwoFA:
    def test_submits_password_and_clears_code(
        self,
        page_twofa: Page,
        api: httpx.Client,
        users: dict,
    ) -> None:
        twofa = users["twofa"]
        reset_onboarding_login(api)
        hide_onboarding_drafts(api, twofa.id)
        script_onboarding_login(api, "12345", "secret2fa")

        _walk_to_credentials(page_twofa, "Тест 2FA", SOUL_TEXT)
        page_twofa.get_by_label("Номер телефона").fill("+79990000000")
        page_twofa.get_by_role("button", name="Получить код →").click()
        expect(page_twofa.get_by_role("heading", name="Код из Telegram")).to_be_visible()

        page_twofa.get_by_label("Код подтверждения").fill("12345")
        page_twofa.get_by_role("button", name="Подтвердить →").click()
        expect(
            page_twofa.get_by_role("heading", name="Двухфакторная аутентификация")
        ).to_be_visible()

        page_twofa.get_by_role("button", name="Подтвердить →").click()
        expect(page_twofa.get_by_text("2FA пароль обязателен")).to_be_visible()

        page_twofa.get_by_label("Пароль 2FA").fill("secret2fa")
        page_twofa.get_by_role("button", name="Подтвердить →").click()
        expect(page_twofa.get_by_role("heading", name="Всё готово!")).to_be_visible()
        _wait_code_cleared(page_twofa)


class TestStoredStep:
    def test_code_requested_draft_opens_code_step(
        self,
        page_code: Page,
        api: httpx.Client,
        users: dict,
    ) -> None:
        code_user = users["code"]
        reset_onboarding_login(api)
        script_onboarding_login(api, "12345")
        hide_onboarding_drafts(api, code_user.id)

        _walk_to_credentials(page_code, "Тест возврата", SOUL_TEXT)
        page_code.get_by_label("Номер телефона").fill("+79990000000")
        page_code.get_by_role("button", name="Получить код →").click()
        expect(page_code.get_by_role("heading", name="Код из Telegram")).to_be_visible()

        page_code.reload()
        expect(page_code.get_by_role("heading", name="Код из Telegram")).to_be_visible()
        expect(page_code.get_by_test_id("onboarding-step-telegram_credentials")).to_be_visible()

        page_code.get_by_role("button", name="← Назад").click()
        expect(page_code.get_by_role("heading", name="Подключение Telegram")).to_be_visible()
