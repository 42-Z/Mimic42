from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.config import Settings
from mimic42.core.agent_runtime import AgentRuntimeConfig, AgentRuntimeState
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramAuthClientFactory
from tests.api.admin_fakes import FakeAdminRepository
from tests.api.fakes import FakeAgentManager

if TYPE_CHECKING:
    from mimic42.core.admin import AdminRepository


def _api_settings(
    *,
    database_connection_string: str | None = None,
    supabase_url: str | None = None,
    supabase_service_key: str | None = None,
    restore_running_agents: bool = True,
) -> Settings:
    return Settings(
        database_connection_string=database_connection_string,
        mem0_api_key=None,
        braintrust_api_key=None,
        supabase_url=supabase_url,
        supabase_service_key=supabase_service_key,
        secret_key=None,
        restore_running_agents=restore_running_agents,
    )


class ClosableStorage:
    """Хранилище, которое помнит, что его закрыли."""

    def __init__(self, **_: object) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


async def test_create_app_uses_injected_telegram_factory() -> None:
    account = FakeTelegramAccount()
    app = create_app(
        settings=_api_settings(),
        telegram_factory=FakeTelegramAuthClientFactory(account),
    )
    service = app.state.onboarding_service
    client = service._telegram_factory.build(api_id=1, api_hash="hash")
    await client.send_code_request("+79990000000")
    assert account.phone == "+79990000000"


def test_create_app_defaults_to_telethon() -> None:
    from mimic42.integrations.telegram_auth import TelethonAuthClientFactory

    app = create_app(settings=_api_settings())
    assert isinstance(app.state.onboarding_service._telegram_factory, TelethonAuthClientFactory)


async def test_create_app_serves_health() -> None:
    # Без базы и без lifespan: проверяется маршрутизация самого приложения,
    # а не тестовая обвязка поверх Dev-проекта.
    app = create_app(settings=_api_settings())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_app_closes_the_media_storage_it_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """Открытые соединения хранилища иначе переживают приложение."""
    monkeypatch.setattr("mimic42.api.app.SupabaseMediaStorage", ClosableStorage)
    app = create_app(
        settings=_api_settings(
            supabase_url="https://example.supabase.co",
            supabase_service_key="service-key",
        )
    )
    storage = app.state.media_uploader
    assert isinstance(storage, ClosableStorage)

    async with app.router.lifespan_context(app):
        assert storage.closed is False

    assert storage.closed is True


async def test_app_leaves_an_injected_media_storage_open() -> None:
    """Чужое хранилище закрывает тот, кто его создал."""
    storage = ClosableStorage()
    app = create_app(
        settings=_api_settings(),
        media_uploader=cast(Any, storage),
    )

    async with app.router.lifespan_context(app):
        pass

    assert storage.closed is False


class DisposableEngine:
    def __init__(self) -> None:
        self.dispose_calls = 0

    async def dispose(self) -> None:
        self.dispose_calls += 1


class ShutdownTrackingManager(FakeAgentManager):
    def __init__(self) -> None:
        super().__init__()
        self.shutdown_calls = 0

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


class InjectedService:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _disable_external_lifespan_work(monkeypatch: pytest.MonkeyPatch) -> None:
    async def flush_tracing() -> None:
        return None

    monkeypatch.setattr("mimic42.api.app.setup_tracing", lambda _settings: None)
    monkeypatch.setattr("mimic42.api.app.flush_tracing", flush_tracing)


async def test_injected_database_services_do_not_create_or_dispose_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine_attempts: list[str] = []
    monkeypatch.setattr(
        "mimic42.api.app.create_engine",
        lambda connection_string: engine_attempts.append(connection_string),
    )
    _disable_external_lifespan_work(monkeypatch)

    manager = ShutdownTrackingManager()
    agent_store = InjectedService()
    onboarding_service = InjectedService()
    admin_repository = FakeAdminRepository()
    app = create_app(
        manager=manager,
        agent_store=cast(Any, agent_store),
        onboarding_service=cast(Any, onboarding_service),
        admin_repository=cast("AdminRepository", admin_repository),
        settings=_api_settings(database_connection_string="postgresql+asyncpg://unused"),
    )

    async with app.router.lifespan_context(app):
        assert app.state.admin_repository is admin_repository

    assert engine_attempts == []
    assert agent_store.closed is False
    assert onboarding_service.closed is False
    assert manager.shutdown_calls == 1


async def test_only_admin_repository_is_built_when_agent_services_are_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = DisposableEngine()
    session_factory = object()
    engine_calls: list[str] = []
    repository_factories: list[object] = []
    monkeypatch.setattr(
        "mimic42.api.app.create_engine",
        lambda connection_string: engine_calls.append(connection_string) or engine,
    )
    monkeypatch.setattr(
        "mimic42.api.app.create_session_factory",
        lambda created_engine: session_factory if created_engine is engine else pytest.fail(),
    )
    monkeypatch.setattr(
        "mimic42.api.app.DatabaseAdminRepository",
        lambda factory: repository_factories.append(factory) or FakeAdminRepository(),
    )
    monkeypatch.setattr(
        "mimic42.api.app.DatabaseAgentStore",
        lambda *_args, **_kwargs: pytest.fail("agent store must remain injected"),
    )
    monkeypatch.setattr(
        "mimic42.api.app.DatabaseOnboardingRepository",
        lambda *_args, **_kwargs: pytest.fail("onboarding service must remain injected"),
    )
    monkeypatch.setattr(
        "mimic42.api.app.build_mem0_memory",
        lambda *_args, **_kwargs: pytest.fail("agent services must not be built"),
    )
    _disable_external_lifespan_work(monkeypatch)

    manager = ShutdownTrackingManager()
    agent_store = InjectedService()
    onboarding_service = InjectedService()
    app = create_app(
        manager=manager,
        agent_store=cast(Any, agent_store),
        onboarding_service=cast(Any, onboarding_service),
        settings=_api_settings(database_connection_string="postgresql+asyncpg://unused"),
    )

    async with app.router.lifespan_context(app):
        assert app.state.agent_store is agent_store
        assert app.state.onboarding_service is onboarding_service
        assert app.state.admin_repository is not None

    assert len(engine_calls) == 1
    assert len(repository_factories) == 1
    assert repository_factories[0] is session_factory
    assert engine.dispose_calls == 1
    assert manager.shutdown_calls == 1


async def test_agent_and_admin_services_share_one_engine_and_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = DisposableEngine()
    session_factory = object()
    engine_calls: list[str] = []
    session_factory_calls: list[object] = []
    service_factories: dict[str, object] = {}

    monkeypatch.setattr(
        "mimic42.api.app.create_engine",
        lambda connection_string: engine_calls.append(connection_string) or engine,
    )

    def create_factory(created_engine: object) -> object:
        assert created_engine is engine
        session_factory_calls.append(created_engine)
        return session_factory

    monkeypatch.setattr("mimic42.api.app.create_session_factory", create_factory)

    class BuiltAgentStore:
        def __init__(self, factory: object, **_kwargs: object) -> None:
            service_factories["agent_store"] = factory

        async def get_runtime_config(self, _agent_id: UUID) -> AgentRuntimeConfig:
            raise AssertionError("runtime config is not loaded in this test")

        async def update_status(self, _agent_id: UUID, _state: AgentRuntimeState) -> None:
            raise AssertionError("runtime status is not updated in this test")

    class BuiltOnboardingRepository:
        def __init__(self, factory: object) -> None:
            service_factories["onboarding"] = factory

    class BuiltAdminRepository:
        def __init__(self, factory: object) -> None:
            service_factories["admin"] = factory

    class BuiltManager:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.warmup = None
            self.shutdown_calls = 0
            manager_session_factory = kwargs.get("session_factory")
            if manager_session_factory is not None:
                service_factories["manager"] = manager_session_factory

        async def shutdown(self) -> None:
            self.shutdown_calls += 1

    managers: list[BuiltManager] = []

    def build_manager(**kwargs: object) -> BuiltManager:
        manager = BuiltManager(**kwargs)
        managers.append(manager)
        return manager

    monkeypatch.setattr("mimic42.api.app.DatabaseAgentStore", BuiltAgentStore)
    monkeypatch.setattr("mimic42.api.app.DatabaseOnboardingRepository", BuiltOnboardingRepository)
    monkeypatch.setattr("mimic42.api.app.DatabaseAdminRepository", BuiltAdminRepository)
    monkeypatch.setattr("mimic42.api.app.AgentManager", build_manager)
    monkeypatch.setattr("mimic42.api.app.build_mem0_memory", lambda _key: object())
    _disable_external_lifespan_work(monkeypatch)

    app = create_app(
        settings=_api_settings(
            database_connection_string="postgresql+asyncpg://unused",
            restore_running_agents=False,
        )
    )

    async with app.router.lifespan_context(app):
        assert app.state.admin_repository is not None
        assert app.state.agent_store is not None
        assert app.state.onboarding_service is not None

    assert len(engine_calls) == 1
    assert len(session_factory_calls) == 1
    assert service_factories == {
        "agent_store": session_factory,
        "onboarding": session_factory,
        "admin": session_factory,
        "manager": session_factory,
    }
    assert engine.dispose_calls == 1
    assert managers[-1].shutdown_calls == 1
