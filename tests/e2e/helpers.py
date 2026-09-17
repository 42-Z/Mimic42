"""HTTP-помощники e2e: порт frontend/e2e/helpers.ts на httpx."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import Page

from mimic42.testing.env import load_test_env

ROOT = Path(__file__).resolve().parents[2]
load_test_env()

API_PORT = int(os.environ.get("E2E_API_PORT", "8000"))
APP_PORT = int(os.environ.get("E2E_APP_PORT", "3000"))
API_URL = f"http://127.0.0.1:{API_PORT}"
APP_URL = f"http://127.0.0.1:{APP_PORT}"
AUTH_DIR = Path(__file__).parent / ".auth"


def _post(api: httpx.Client, path: str, payload: dict[str, object]) -> dict[str, object]:
    response = api.post(path, json=payload)
    response.raise_for_status()
    return response.json() if response.content else {}


class E2EUser:
    def __init__(self, key: str, user_id: str, email: str, password: str) -> None:
        self.key = key
        self.id = user_id
        self.email = email
        self.password = password
        self.state_file = AUTH_DIR / f"{key}.json"


def users_from_slot_description(description: dict[str, Any]) -> dict[str, E2EUser]:
    password = os.environ["TEST_USER_PASSWORD"]
    personas = description["personas"]
    assert isinstance(personas, list)
    return {
        persona["key"]: E2EUser(persona["key"], persona["id"], persona["email"], password)
        for persona in personas
    }


def reset_backend(api: httpx.Client, slot: str) -> None:
    _post(api, "/__test__/reset", {"slot": slot})


def create_test_agent(
    api: httpx.Client,
    owner_id: str,
    name: str,
    state: str = "stopped",
    phone_number: str | None = None,
    with_telegram_session: bool = True,
) -> str:
    result = _post(
        api,
        "/__test__/agents",
        {
            "owner_id": owner_id,
            "name": name,
            "state": state,
            "phone_number": phone_number,
            "with_telegram_session": with_telegram_session,
        },
    )
    return str(result["agent_id"])


def deliver_message(api: httpx.Client, agent_id: str, chat_id: int, text: str) -> None:
    _post(api, f"/__test__/telegram/{agent_id}/deliver", {"chat_id": chat_id, "text": text})


def script_agent_reply(api: httpx.Client, agent_id: str, text: str) -> None:
    _post(api, f"/__test__/agents/{agent_id}/script", {"text": text})


def record_agent_event(api: httpx.Client, agent_id: str, event: dict[str, object]) -> None:
    _post(api, f"/__test__/agents/{agent_id}/events", event)


def script_onboarding_login(
    api: httpx.Client, code: str | None, password: str | None = None
) -> None:
    _post(api, "/__test__/telegram/onboarding/script", {"code": code, "password": password})


def reset_onboarding_login(api: httpx.Client) -> None:
    _post(api, "/__test__/telegram/onboarding/reset", {})


def hide_onboarding_drafts(api: httpx.Client, owner_id: str) -> None:
    _post(api, "/__test__/onboarding/drafts/hide", {"owner_id": owner_id})


def current_draft_id(api: httpx.Client, owner_id: str) -> str:
    response = api.get("/__test__/onboarding/drafts/current", params={"owner_id": owner_id})
    response.raise_for_status()
    draft_id = response.json()["id"]
    assert draft_id, f"Нет черновика онбординга для owner_id={owner_id}"
    return str(draft_id)


def login_via_form(page: Page, user: E2EUser) -> None:
    page.goto("/login")
    page.get_by_label("Email").fill(user.email)
    page.get_by_label("Пароль", exact=True).fill(user.password)
    page.get_by_role("button", name="Войти").click()
