from __future__ import annotations

from mimic42.core.agent_runtime import TelegramProxyConfig
from mimic42.core.onboarding import TelegramPasswordRequiredError
from mimic42.core.telegram_proxy import TelegramProxyUnavailableError
from mimic42.testing.telegram.account import FakeTelegramAccount


class FakeTelegramAuthClient:
    def __init__(
        self,
        account: FakeTelegramAccount,
        *,
        proxy: TelegramProxyConfig | None = None,
    ) -> None:
        self._account = account
        self._proxy = proxy
        self._connect_error: Exception | None = None

    def fail_next_connect(self, error: Exception) -> None:
        """Один раз упасть на подключении — как настоящий прокси."""
        self._connect_error = error

    async def connect(self) -> None:
        if self._connect_error is not None:
            error, self._connect_error = self._connect_error, None
            raise error

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

    async def get_me(self) -> object:
        # Как у Telethon: без входа пользователь неизвестен (None),
        # а у аккаунта может не быть @username.
        if not self._account.authorized:
            return None
        return type("User", (), {"id": 777, "username": self._account.username})()

    def save_session(self) -> str:
        # Real Telethon can export a session string once connected, well
        # before sign-in completes (it encodes the auth key, not the login).
        if self._account.phone is None:
            raise RuntimeError("Сессия не создана: клиент ещё не подключался")
        return f"fake-session:{self._account.phone}"


class FakeTelegramAuthClientFactory:
    def __init__(
        self,
        account: FakeTelegramAccount,
        *,
        broken_proxies: set[tuple[str, int]] | None = None,
        transient_failures: int = 0,
    ) -> None:
        self._account = account
        self._broken_proxies = set(broken_proxies or ())
        self._transient_failures = transient_failures
        self.built_with: tuple[int, str] | None = None
        self.proxies: list[TelegramProxyConfig | None] = []

    def build(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
        proxy: TelegramProxyConfig | None = None,
    ) -> FakeTelegramAuthClient:
        self.built_with = (api_id, api_hash)
        self.proxies.append(proxy)
        client = FakeTelegramAuthClient(self._account, proxy=proxy)
        if proxy is not None and (proxy.host, proxy.port) in self._broken_proxies:
            client.fail_next_connect(TelegramProxyUnavailableError("он не пропускает Telegram"))
        elif self._transient_failures > 0:
            self._transient_failures -= 1
            client.fail_next_connect(TelegramProxyUnavailableError("он не пропускает Telegram"))
        if session_string:
            self._account.authorized = True
        return client
