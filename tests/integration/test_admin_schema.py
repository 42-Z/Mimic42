"""Administrative tables stay inaccessible through client database roles."""

from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from mimic42.integrations.database_models import AdminAuditLogModel
from mimic42.testing.slots import Slot, plain_dsn

ADMIN_TABLES = (
    "admin_users",
    "platform_telegram_settings",
    "admin_audit_log",
)
CLIENT_ROLES = ("public", "anon", "authenticated")
TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)
COLUMN_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "REFERENCES")
SERVICE_ROLE_ALLOWED = {
    "admin_users": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "platform_telegram_settings": {"SELECT", "INSERT", "UPDATE"},
    "admin_audit_log": {"SELECT", "INSERT"},
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

        server_version = int(
            await connection.fetchval("select current_setting('server_version_num')")
        )
        privileges = TABLE_PRIVILEGES + (("MAINTAIN",) if server_version >= 170000 else ())
        for role in CLIENT_ROLES:
            for privilege in privileges:
                granted = await connection.fetchval(
                    "select has_table_privilege($1, $2, $3)",
                    role,
                    relation,
                    privilege,
                )
                assert granted is False, f"{role} unexpectedly has {privilege} on {relation}"

        columns = await connection.fetch(
            "select column_name from information_schema.columns "
            "where table_schema = 'public' and table_name = $1",
            table_name,
        )
        for role in CLIENT_ROLES:
            for column in columns:
                for privilege in COLUMN_PRIVILEGES:
                    granted = await connection.fetchval(
                        "select has_column_privilege($1, $2, $3, $4)",
                        role,
                        relation,
                        column["column_name"],
                        privilege,
                    )
                    assert granted is False, (
                        f"{role} unexpectedly has {privilege} on {relation}.{column['column_name']}"
                    )

        for privilege in privileges:
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


async def test_admin_audit_requires_matching_action_and_object(
    test_dsn: str,
    test_slot: Slot,
) -> None:
    connection = await asyncpg.connect(plain_dsn(test_dsn))
    try:
        async with connection.transaction():
            with pytest.raises(asyncpg.CheckViolationError):
                async with connection.transaction():
                    await connection.execute(
                        "insert into public.admin_audit_log "
                        "(actor_user_id, action, object_type, object_id) "
                        "values ($1, 'preset.created', 'telegram_settings', null)",
                        uuid4(),
                    )
    finally:
        await connection.close()
