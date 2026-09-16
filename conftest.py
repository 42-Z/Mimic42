"""Общие фикстуры. Тесты с маркером db работают против настоящей
базы проекта Mimic42 Dev и занимают слот тестовых аккаунтов."""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from mimic42.integrations.database_session import create_engine, create_session_factory
from mimic42.testing import registry
from mimic42.testing.cleanup import purge_slot_data
from mimic42.testing.env import load_test_env
from mimic42.testing.slots import Slot, acquire_slot, assert_test_project, release_slot

# До сбора тестов: значения из .env/.env.test нужны и фикстурам, и тестовому
# серверу, и они же закрывают заслон от прод-проекта реальными значениями.
load_test_env()


@pytest.fixture(scope="session")
def test_dsn() -> str:
    dsn = os.environ.get("DATABASE_CONNECTION_STRING")
    url = os.environ.get("SUPABASE_URL")
    if not dsn or not url:
        pytest.fail(
            "DATABASE_CONNECTION_STRING/SUPABASE_URL не заданы: "
            "скопируйте .env.example в .env. db-тесты запускаются явно: "
            "`uv run pytest -m db`"
        )
    try:
        # Проверяем и DSN, и адрес проекта: фикстуры пишут и через SQLAlchemy,
        # и через Supabase-подобные вызовы, а заслон должен стоять на входе.
        assert_test_project(dsn, url)
    except RuntimeError as exc:
        pytest.fail(str(exc))
    return dsn


@pytest.fixture(scope="session")
async def test_slot(test_dsn: str) -> AsyncIterator[Slot]:
    holder = f"{socket.gethostname()}:{os.getpid()}"
    slot = await acquire_slot(test_dsn, holder=holder)
    try:
        yield slot
    finally:
        await release_slot(test_dsn, slot, holder=holder)


@pytest.fixture(scope="session")
async def db_engine(test_dsn: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(test_dsn)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def db_session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(db_engine)


@pytest.fixture
async def clean_slot(test_dsn: str, test_slot: Slot) -> AsyncIterator[Slot]:
    """Чистит данные слота ПЕРЕД тестом: после падения остатки видно."""
    await purge_slot_data(test_dsn, test_slot)
    # Внутрипроцессные подделки (телега, сценарии) живут вне базы: без сброса
    # тест зависел бы от порядка запуска соседей.
    registry.reset()
    yield test_slot


def pytest_collection_modifyitems(items: Iterator[pytest.Item]) -> None:
    """Тесты в tests/integration автоматически получают маркер db."""
    for item in items:
        if "/tests/integration/" in str(item.path).replace(os.sep, "/"):
            item.add_marker(pytest.mark.db)
