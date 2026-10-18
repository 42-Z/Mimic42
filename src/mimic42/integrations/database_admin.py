from __future__ import annotations

from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.admin import AdminUnavailableError
from mimic42.integrations.database_models import AdminUserModel


class DatabaseAdminRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def is_admin(self, user_id: UUID) -> bool:
        statement = select(exists().where(AdminUserModel.user_id == user_id))
        try:
            async with self._session_factory() as session:
                return bool(await session.scalar(statement))
        except SQLAlchemyError:
            raise AdminUnavailableError("Administrative storage is unavailable") from None
