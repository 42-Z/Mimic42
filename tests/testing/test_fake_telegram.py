from __future__ import annotations

import pytest

from mimic42.core.onboarding import TelegramPasswordRequiredError
from mimic42.testing.telegram import (
    FakeTelegramAccount,
    FakeTelegramAuthClientFactory,
    FakeTelegramClient,
)


async def test_login_then_work_share_one_account() -> None:
    account = FakeTelegramAccount()
    account.script_code("12345")

    auth = FakeTelegramAuthClientFactory(account).build(api_id=1, api_hash="hash")
    await auth.connect()
    await auth.send_code_request("+79990000000")
    await auth.sign_in(phone="+79990000000", code="12345")
    session_string = auth.save_session()

    assert account.authorized is True
    assert session_string

    client = FakeTelegramClient(account)
    assert await client.is_user_authorized() is True
    await client.send_message("42", "привет")
    assert account.sent[-1].chat_id == "42"
    assert account.sent[-1].text == "привет"


async def test_wrong_code_is_rejected() -> None:
    account = FakeTelegramAccount()
    account.script_code("12345")
    auth = FakeTelegramAuthClientFactory(account).build(api_id=1, api_hash="hash")
    await auth.send_code_request("+79990000000")

    with pytest.raises(ValueError):
        await auth.sign_in(phone="+79990000000", code="00000")
    assert account.authorized is False


async def test_two_factor_password_is_requested() -> None:
    account = FakeTelegramAccount()
    account.script_code("12345")
    account.require_password("секрет")
    auth = FakeTelegramAuthClientFactory(account).build(api_id=1, api_hash="hash")
    await auth.send_code_request("+79990000000")

    with pytest.raises(TelegramPasswordRequiredError):
        await auth.sign_in(phone="+79990000000", code="12345")

    await auth.sign_in(phone="+79990000000", code="12345", password="секрет")
    assert account.authorized is True


async def test_incoming_message_reaches_the_registered_handler() -> None:
    account = FakeTelegramAccount()
    account.authorized = True
    client = FakeTelegramClient(account)
    seen: list[str] = []

    client.add_event_handler(lambda event: _remember(seen, event))
    await account.deliver(chat_id=42, text="как дела")

    assert seen == ["как дела"]


async def _remember(seen: list[str], event: object) -> None:
    seen.append(getattr(event, "text", ""))
