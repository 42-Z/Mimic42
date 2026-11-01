from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from telethon import errors, functions

from mimic42.core.telegram_account import (
    TelegramAccountFloodWaitError,
    TelegramCurrentPasswordInvalidError,
    TelegramCurrentPasswordRequiredError,
    TelegramPasswordEmptyError,
    TelegramPasswordHintCollisionError,
    TelegramPasswordUpdate,
    TelegramSessionInvalidError,
    TelegramUsernameInvalidError,
    TelegramUsernameOccupiedError,
    TelegramUsernameUpdate,
    apply_password,
    apply_username,
    normalize_username,
    read_password_state,
)
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramClient


def _authorized_client(
    *, username: str | None = None, password: str | None = None, hint: str | None = None
) -> tuple[FakeTelegramClient, FakeTelegramAccount]:
    account = FakeTelegramAccount()
    account.authorized = True
    account.username = username
    if password is not None:
        account.set_password(password, hint)
    return FakeTelegramClient(account), account


def _password_change(new: str, current: str | None = None) -> TelegramPasswordUpdate:
    return TelegramPasswordUpdate(
        new_password=SecretStr(new),
        current_password=(SecretStr(current) if current is not None else None),
    )


def test_username_is_normalized_to_telegram_rules() -> None:
    assert normalize_username("  @Mimic_42 ") == "Mimic_42"
    assert TelegramUsernameUpdate(username="@valid_name").username == "valid_name"


@pytest.mark.parametrize(
    "value", ["", "@", "abcd", "a" * 33, "имя_агента", "with space", "bad-name"]
)
def test_invalid_username_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_username(value)
    with pytest.raises(ValidationError):
        TelegramUsernameUpdate(username=value)


def test_empty_new_password_is_rejected_before_telegram() -> None:
    with pytest.raises(ValidationError):
        TelegramPasswordUpdate(new_password=SecretStr(""))
    with pytest.raises(ValidationError):
        TelegramPasswordUpdate(new_password=SecretStr("   "))


@pytest.mark.asyncio
async def test_password_state_comes_from_get_password() -> None:
    client, _ = _authorized_client(password="secret")

    state = await read_password_state(client)

    assert state.has_password is True
    assert any(
        isinstance(request, functions.account.GetPasswordRequest) for request in client.requests
    )


@pytest.mark.asyncio
async def test_username_is_set_and_confirmed_by_telegram() -> None:
    client, account = _authorized_client()

    confirmed = await apply_username(client, "@new_name")

    assert confirmed == "new_name"
    assert account.username == "new_name"
    request = next(
        request
        for request in client.requests
        if isinstance(request, functions.account.UpdateUsernameRequest)
    )
    assert request.username == "new_name"


@pytest.mark.asyncio
async def test_username_not_modified_is_a_successful_repeat() -> None:
    client, account = _authorized_client(username="same_name")

    confirmed = await apply_username(client, "same_name")

    assert confirmed == "same_name"
    assert account.username == "same_name"


@pytest.mark.asyncio
async def test_occupied_username_does_not_report_success() -> None:
    client, account = _authorized_client()
    account.occupied_usernames.add("taken_name")

    with pytest.raises(TelegramUsernameOccupiedError):
        await apply_username(client, "taken_name")

    assert account.username is None


@pytest.mark.asyncio
async def test_username_invalid_from_telegram_is_mapped() -> None:
    class InvalidClient(FakeTelegramClient):
        async def __call__(self, request: Any) -> Any:
            if isinstance(request, functions.account.UpdateUsernameRequest):
                raise errors.UsernameInvalidError(request=request)
            return await super().__call__(request)

    client, _ = _authorized_client()
    invalid = InvalidClient(client.account)

    with pytest.raises(TelegramUsernameInvalidError):
        await apply_username(invalid, "valid_name")


@pytest.mark.asyncio
async def test_password_is_set_on_an_account_without_2fa() -> None:
    client, account = _authorized_client()

    await apply_password(client, _password_change("new_secret"))

    assert account.password == "new_secret"
    assert account.password_edits == [(None, "new_secret", "")]


@pytest.mark.asyncio
async def test_password_change_requires_the_current_password() -> None:
    client, account = _authorized_client(password="old_secret")

    with pytest.raises(TelegramCurrentPasswordRequiredError):
        await apply_password(client, _password_change("new_secret"))

    assert account.password == "old_secret"
    assert account.password_edits == []


@pytest.mark.asyncio
async def test_wrong_current_password_keeps_the_account_state() -> None:
    client, account = _authorized_client(password="old_secret")

    with pytest.raises(TelegramCurrentPasswordInvalidError):
        await apply_password(client, _password_change("new_secret", "wrong_secret"))

    assert account.password == "old_secret"
    assert account.password_edits == []


@pytest.mark.asyncio
async def test_password_change_preserves_the_existing_hint() -> None:
    client, account = _authorized_client(password="old_secret", hint="любимый кот")

    await apply_password(client, _password_change("new_secret", "old_secret"))

    assert account.password == "new_secret"
    assert account.password_hint == "любимый кот"
    assert account.password_edits == [("old_secret", "new_secret", "любимый кот")]


@pytest.mark.asyncio
async def test_a_hint_equal_to_the_new_password_is_refused() -> None:
    client, account = _authorized_client(password="old_secret", hint="new_secret")

    with pytest.raises(TelegramPasswordHintCollisionError):
        await apply_password(client, _password_change("new_secret", "old_secret"))

    assert account.password == "old_secret"
    assert account.password_edits == []


@pytest.mark.asyncio
async def test_empty_new_password_reaching_policy_never_calls_edit_2fa() -> None:
    client, account = _authorized_client()
    change = TelegramPasswordUpdate.model_construct(new_password=SecretStr(""))

    with pytest.raises(TelegramPasswordEmptyError):
        await apply_password(client, change)

    assert account.password_edits == []


@pytest.mark.asyncio
async def test_flood_wait_carries_the_seconds_from_telegram() -> None:
    class FloodClient(FakeTelegramClient):
        async def edit_2fa(
            self,
            current_password: str | None = None,
            new_password: str | None = None,
            *,
            hint: str = "",
        ) -> bool:
            raise errors.FloodWaitError(request=None, capture=17)

    client, _ = _authorized_client()
    flood = FloodClient(client.account)

    with pytest.raises(TelegramAccountFloodWaitError) as caught:
        await apply_password(flood, _password_change("new_secret"))

    assert caught.value.seconds == 17


@pytest.mark.asyncio
async def test_dead_session_is_mapped() -> None:
    class DeadSessionClient(FakeTelegramClient):
        async def __call__(self, request: Any) -> Any:
            raise errors.UnauthorizedError(request=request, message="401: Unauthorized")

    client, _ = _authorized_client()
    dead = DeadSessionClient(client.account)

    with pytest.raises(TelegramSessionInvalidError):
        await read_password_state(dead)
