"""Общие фикстуры. Тесты с маркером db работают против настоящей
базы проекта Mimic42 Dev и занимают слот тестовых аккаунтов."""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from mimic42.integrations.database_session import create_engine, create_session_factory
from mimic42.testing.cleanup import purge_slot_data
from mimic42.testing.slots import Slot, acquire_slot, assert_not_prod, release_slot


@pytest.fixture(scope="session")
def test_dsn() -> str:
    dsn = os.environ.get("TEST_DATABASE_CONNECTION_STRING")
    if not dsn:
        pytest.skip("TEST_DATABASE_CONNECTION_STRING не задан: тесты на базе пропущены")
    try:
        assert_not_prod(dsn)
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
        await release_slot(test_dsn, slot)


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
    yield test_slot


def pytest_collection_modifyitems(items: Iterator[pytest.Item]) -> None:
    """Тесты в tests/integration автоматически получают маркер db."""
    for item in items:
        if "/tests/integration/" in str(item.path).replace(os.sep, "/"):
            item.add_marker(pytest.mark.db)
