from __future__ import annotations

from typing import Any, cast

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from mimic42.core.onboarding import TelegramPasswordRequiredError


class TelethonAuthClient:
    def __init__(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
    ) -> None:
        self._client = TelegramClient(
            StringSession(session_string or ""),
            api_id,
            api_hash,
        )

    async def connect(self) -> None:
        await self._client.connect()

    async def disconnect(self) -> None:
        await self._client.disconnect()

    async def send_code_request(self, phone: str) -> object:
        return await self._client.send_code_request(phone)

    async def sign_in(
        self,
        *,
        phone: str | None = None,
        code: str | None = None,
        phone_code_hash: str | None = None,
        password: str | None = None,
    ) -> object:
        try:
            kwargs: dict[str, Any] = {}
            if phone is not None:
                kwargs["phone"] = phone
            if code is not None:
                kwargs["code"] = code
            if phone_code_hash is not None:
                kwargs["phone_code_hash"] = phone_code_hash
            if password is not None:
                kwargs["password"] = password
            return await self._client.sign_in(
                **kwargs,
            )
        except SessionPasswordNeededError as exc:
            raise TelegramPasswordRequiredError from exc

    def save_session(self) -> str:
        session = self._client.session
        if session is None:
            raise RuntimeError("Telethon session is not initialized")
        return cast(str, session.save())

    async def get_me(self) -> object:
        # Возвращает types.User (или None, если входа ещё не было).
        return await self._client.get_me()


class TelethonAuthClientFactory:
    def build(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
    ) -> TelethonAuthClient:
        return TelethonAuthClient(
            api_id=api_id,
            api_hash=api_hash,
            session_string=session_string,
        )
