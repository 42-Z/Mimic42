from __future__ import annotations

from mimic42.core.onboarding import TelegramPasswordRequiredError
from mimic42.testing.telegram.account import FakeTelegramAccount


class FakeTelegramAuthClient:
    def __init__(self, account: FakeTelegramAccount) -> None:
        self._account = account

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def send_code_request(self, phone: str) -> object:
        self._account.phone = phone
        self._account.code_requested = True
        return type("SentCode", (), {"phone_code_hash": "fake-hash"})()

    async def sign_in(
        self,
        *,
        phone: str | None = None,
        code: str | None = None,
        phone_code_hash: str | None = None,
        password: str | None = None,
    ) -> object:
        account = self._account
        if password is not None:
            if password != account.password:
                raise ValueError("Неверный пароль двухфакторной защиты")
            account.password_satisfied = True
            account.authorized = True
            return type("User", (), {"id": 777})()
        if code is None or not code.strip():
            raise ValueError("Код подтверждения не указан")
        if account.expected_code is not None and code != account.expected_code:
            raise ValueError("Неверный код подтверждения")
        if not account.password_satisfied:
            raise TelegramPasswordRequiredError
        account.authorized = True
        return type("User", (), {"id": 777})()

    def save_session(self) -> str:
        # Real Telethon can export a session string once connected, well
        # before sign-in completes (it encodes the auth key, not the login).
        if self._account.phone is None:
            raise RuntimeError("Сессия не создана: клиент ещё не подключался")
        return f"fake-session:{self._account.phone}"


class FakeTelegramAuthClientFactory:
    def __init__(self, account: FakeTelegramAccount) -> None:
        self._account = account
        self.built_with: tuple[int, str] | None = None

    def build(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
    ) -> FakeTelegramAuthClient:
        self.built_with = (api_id, api_hash)
        if session_string:
            self._account.authorized = True
        return FakeTelegramAuthClient(self._account)
