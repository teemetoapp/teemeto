"""
Spike test verifying PostgreSQL Row Level Security (RLS) concurrency and data isolation.
Acceptance test for Task 0.2.
"""

import asyncio
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from packages.shared.db.session import admin_session, dispose_engines, tenant_session
from packages.shared.errors import TenantContextError

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS test_tenant_items (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id TEXT NOT NULL,
        name TEXT NOT NULL
    )
    """,
    "ALTER TABLE test_tenant_items ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE test_tenant_items FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation_policy ON test_tenant_items",
    """
    CREATE POLICY tenant_isolation_policy ON test_tenant_items
        FOR ALL
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
    """,
    "GRANT ALL ON test_tenant_items TO teemeto_app",
]


@pytest.fixture(autouse=True)
async def setup_and_cleanup_rls_test_table() -> AsyncGenerator[None, None]:
    """Ensures test table exists and is cleanly truncated for each test."""
    async with admin_session() as session:
        for stmt in DDL_STATEMENTS:
            await session.execute(text(stmt))
        await session.execute(text("TRUNCATE TABLE test_tenant_items;"))
    yield
    await dispose_engines()



@pytest.mark.asyncio
async def test_tenant_session_requires_valid_tenant_id() -> None:
    """Verifies that attempting to open a session without a valid tenant_id immediately raises an error."""
    with pytest.raises(TenantContextError):
        async with tenant_session(""):
            pass

    with pytest.raises(TenantContextError):
        async with tenant_session("   "):
            pass


@pytest.mark.asyncio
async def test_rls_concurrency_and_data_isolation() -> None:
    """
    Verifies that concurrent transactions for different tenants are completely isolated.
    Neither tenant can read, modify, or leak data belonging to the other.
    """
    tenant_a = "tenant-corp-alpha-111"
    tenant_b = "tenant-shop-beta-222"

    async def run_tenant_a_workflow() -> list[str]:
        async with tenant_session(tenant_a) as session:
            # Insert Tenant A record
            await session.execute(
                text("INSERT INTO test_tenant_items (tenant_id, name) VALUES (:t, :n)"),
                {"t": tenant_a, "n": "Alpha Confidential Document"},
            )
            # Query visible records
            result = await session.execute(text("SELECT name FROM test_tenant_items ORDER BY name"))
            return [row[0] for row in result.fetchall()]

    async def run_tenant_b_workflow() -> list[str]:
        async with tenant_session(tenant_b) as session:
            # Insert Tenant B record
            await session.execute(
                text("INSERT INTO test_tenant_items (tenant_id, name) VALUES (:t, :n)"),
                {"t": tenant_b, "n": "Beta Financial Report"},
            )
            # Query visible records
            result = await session.execute(text("SELECT name FROM test_tenant_items ORDER BY name"))
            return [row[0] for row in result.fetchall()]

    # Execute both tenant workflows concurrently
    results_a, results_b = await asyncio.gather(
        run_tenant_a_workflow(),
        run_tenant_b_workflow(),
    )

    # Assert Tenant A only sees Alpha data
    assert results_a == ["Alpha Confidential Document"]
    assert "Beta Financial Report" not in results_a

    # Assert Tenant B only sees Beta data
    assert results_b == ["Beta Financial Report"]
    assert "Alpha Confidential Document" not in results_b


@pytest.mark.asyncio
async def test_rls_blocks_empty_tenant_context() -> None:
    """
    Verifies that querying as application user without app.tenant_id yields zero records,
    preventing any accidental public exposure of tenant data.
    """
    # Insert data via Tenant A
    async with tenant_session("tenant-gamma") as session:
        await session.execute(
            text("INSERT INTO test_tenant_items (tenant_id, name) VALUES ('tenant-gamma', 'Gamma Secret')")
        )

    # Query through raw session without setting app.tenant_id
    from packages.shared.db.session import get_app_session_factory

    factory = get_app_session_factory()
    async with factory() as session:
        result = await session.execute(text("SELECT * FROM test_tenant_items;"))
        rows = result.fetchall()
        assert len(rows) == 0, "Query without tenant context must never return rows"


@pytest.mark.asyncio
async def test_rls_check_violation_on_mismatched_insert() -> None:
    """
    Verifies that an attempt to insert records with a tenant_id different from the
    active session's app.tenant_id is blocked at the database engine level (RLS WITH CHECK).
    """
    active_tenant = "tenant-legit"
    foreign_tenant = "tenant-attacker"

    async with tenant_session(active_tenant) as session:
        with pytest.raises(DBAPIError) as exc_info:
            await session.execute(
                text("INSERT INTO test_tenant_items (tenant_id, name) VALUES (:t, :n)"),
                {"t": foreign_tenant, "n": "Malicious Spoofed Record"},
            )
        # Verify PostgreSQL row-level security policy check failure
        assert "row-level security policy" in str(exc_info.value).lower()
