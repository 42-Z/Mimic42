"""Integration-test helpers that isolate administrator writes in Dev."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from mimic42.testing.slots import Slot


@pytest.fixture
async def admin_db_factory(
    db_engine: AsyncEngine,
    test_slot: Slot,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Share one repeatable-read transaction across committed repository sessions."""
    async with db_engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="REPEATABLE READ")
        transaction = await connection.begin()
        try:
            yield async_sessionmaker(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
        finally:
            await transaction.rollback()
