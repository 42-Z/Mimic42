from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError
from telethon import TelegramClient, errors
from telethon.crypto import AuthKey
from telethon.sessions import StringSession

from mimic42.core.agent_runtime import AgentRuntimeConfig, TelegramAuthorizationRequired
from mimic42.integrations.telethon_client import MimicTelegramClient, build_telegram_client


def _config(session_string: str | None) -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_api_id=12345,
        telegram_api_hash="hash",
        telegram_session_string=session_string,
        system_prompt="system",
        soul_prompt="soul",
    )


def _valid_session_string() -> str:
    session = StringSession()
    session.set_dc(2, "149.154.167.51", 443)
    session.auth_key = AuthKey(bytes(range(256)))
    return session.save()


def test_missing_session_string_raises_before_creating_client() -> None:
    with pytest.raises(TelegramAuthorizationRequired, match="не привязана"):
        build_telegram_client(_config(None))


def test_empty_session_string_rejected_by_validation() -> None:
    with pytest.raises(ValidationError):
        _config("")


def test_string_session_used_when_present() -> None:
    payload = _valid_session_string()
    client = build_telegram_client(_config(payload))
    assert isinstance(client.session, StringSession)
    assert client.session.save() == payload


def test_flood_waits_are_not_slept_through_by_telethon() -> None:
    """По умолчанию Telethon сам засыпает на флуд-ошибках короче 60 с, а
    SlowModeWaitError — флуд-ошибка. Такой сон прошёл бы внутри send_message
    под trigger_lock: ждать или нет решает окно отправки, а не библиотека."""
    client = build_telegram_client(_config(_valid_session_string()))
    assert client.flood_sleep_threshold == 0


@pytest.mark.asyncio
async def test_peer_flood_on_any_request_is_reported_and_still_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = build_telegram_client(_config(_valid_session_string()))
    assert isinstance(client, MimicTelegramClient)
    reported: list[str] = []

    async def handler() -> None:
        reported.append("flood")

    async def flooded(self: object, request: object, **_kwargs: object) -> object:
        raise errors.PeerFloodError(request=request)

    client.peer_flood_handler = handler
    monkeypatch.setattr(TelegramClient, "__call__", flooded)

    with pytest.raises(errors.PeerFloodError):
        await client(object())

    assert reported == ["flood"]


@pytest.mark.asyncio
async def test_other_errors_and_successes_pass_through_without_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = build_telegram_client(_config(_valid_session_string()))
    assert isinstance(client, MimicTelegramClient)
    reported: list[str] = []

    async def handler() -> None:
        reported.append("flood")

    client.peer_flood_handler = handler

    async def ok(self: object, request: object, **_kwargs: object) -> object:
        return "ответ"

    monkeypatch.setattr(TelegramClient, "__call__", ok)
    assert await client(object()) == "ответ"

    async def other(self: object, request: object, **_kwargs: object) -> object:
        raise errors.FloodWaitError(request=request, capture=30)

    monkeypatch.setattr(TelegramClient, "__call__", other)
    with pytest.raises(errors.FloodWaitError):
        await client(object())

    assert reported == []
