"""Administrative tables stay inaccessible through client database roles."""

from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from mimic42.integrations.database_models import AdminAuditLogModel
from mimic42.testing.slots import plain_dsn

ADMIN_TABLES = (
    "admin_users",
    "platform_telegram_settings",
    "admin_audit_log",
)
CLIENT_ROLES = ("anon", "authenticated")
TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE")
SERVICE_ROLE_ALLOWED = {
    "admin_users": TABLE_PRIVILEGES,
    "platform_telegram_settings": ("SELECT", "INSERT", "UPDATE"),
    "admin_audit_log": ("SELECT", "INSERT"),
}


@pytest.mark.parametrize("table_name", ADMIN_TABLES)
async def test_admin_tables_have_rls_and_no_client_grants(
    test_dsn: str,
    table_name: str,
) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        relation = f"public.{table_name}"
        row = await connection.fetchrow(
            "select to_regclass($1) as relation, "
            "(select relrowsecurity from pg_class where oid = to_regclass($1)) as rls_enabled",
            relation,
        )
        assert row is not None
        assert row["relation"] is not None
        assert row["rls_enabled"] is True

        for role in CLIENT_ROLES:
            for privilege in TABLE_PRIVILEGES:
                granted = await connection.fetchval(
                    "select has_table_privilege($1, $2, $3)",
                    role,
                    relation,
                    privilege,
                )
                assert granted is False, f"{role} unexpectedly has {privilege} on {relation}"

        for privilege in TABLE_PRIVILEGES:
            granted = await connection.fetchval(
                "select has_table_privilege('service_role', $1, $2)",
                relation,
                privilege,
            )
            assert granted is (privilege in SERVICE_ROLE_ALLOWED[table_name]), (
                f"service_role has an unexpected {privilege} grant on {relation}"
            )
    finally:
        await connection.close()


async def test_admin_db_factory_commit_stays_inside_outer_transaction(
    admin_db_factory: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
) -> None:
    audit_id = uuid4()
    async with admin_db_factory() as session:
        session.add(
            AdminAuditLogModel(
                id=audit_id,
                actor_user_id=uuid4(),
                action="telegram.settings_updated",
                object_type="telegram_settings",
                object_id=None,
                metadata_={"credentials_replaced": True},
            )
        )
        await session.commit()

    async with db_engine.connect() as observer:
        row = await observer.scalar(
            select(AdminAuditLogModel.id).where(AdminAuditLogModel.id == audit_id)
        )

    assert row is None
