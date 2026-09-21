from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError
from telethon.crypto import AuthKey
from telethon.sessions import StringSession

from mimic42.core.agent_runtime import AgentRuntimeConfig, TelegramAuthorizationRequired
from mimic42.integrations.telethon_client import build_telegram_client


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
    with pytest.raises(TelegramAuthorizationRequired):
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
