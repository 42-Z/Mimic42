from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.config import Settings
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramAuthClientFactory


async def test_create_app_uses_injected_telegram_factory() -> None:
    account = FakeTelegramAccount()
    app = create_app(
        settings=Settings(database_connection_string=None),
        telegram_factory=FakeTelegramAuthClientFactory(account),
    )
    service = app.state.onboarding_service
    client = service._telegram_factory.build(api_id=1, api_hash="hash")
    await client.send_code_request("+79990000000")
    assert account.phone == "+79990000000"


def test_create_app_defaults_to_telethon() -> None:
    from mimic42.integrations.telegram_auth import TelethonAuthClientFactory

    app = create_app(settings=Settings(database_connection_string=None))
    assert isinstance(app.state.onboarding_service._telegram_factory, TelethonAuthClientFactory)


async def test_create_app_serves_health() -> None:
    # Без базы и без lifespan: проверяется маршрутизация самого приложения,
    # а не тестовая обвязка поверх Dev-проекта.
    app = create_app(settings=Settings(database_connection_string=None))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
