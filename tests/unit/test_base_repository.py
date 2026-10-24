"""Unit tests for BaseRepository generic operations and tenant scoping."""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import Column, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

from packages.shared.db.repositories.base import BaseRepository
from packages.shared.db.session import dispose_engines, tenant_session
from packages.shared.errors import TenantContextError

Base = declarative_base()


class SampleItem(Base):  # type: ignore[valid-type, misc]
    """Sample declarative model for testing repository CRUD."""

    __tablename__ = "test_repo_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String, nullable=False)
    name = Column(String, nullable=False)


@pytest.fixture(autouse=True)
async def setup_repo_table() -> AsyncGenerator[None, None]:

    """Creates the test_repo_items table with RLS."""
    from packages.shared.db.session import get_admin_engine

    engine = get_admin_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        stmts = [
            "GRANT ALL ON test_repo_items TO teemeto_app",
            "ALTER TABLE test_repo_items ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE test_repo_items FORCE ROW LEVEL SECURITY",
            "DROP POLICY IF EXISTS repo_tenant_policy ON test_repo_items",
            """CREATE POLICY repo_tenant_policy ON test_repo_items
               FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
               WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))""",
        ]
        for stmt in stmts:
            await conn.execute(text(stmt))
    yield
    await dispose_engines()


@pytest.mark.asyncio
async def test_base_repository_requires_tenant_id() -> None:
    """Verifies repository initialization fails without valid tenant_id."""
    async with tenant_session("tenant-repo-valid") as session:
        with pytest.raises(TenantContextError):
            BaseRepository(SampleItem, session, "")


@pytest.mark.asyncio
async def test_base_repository_crud() -> None:
    """Verifies create, get_by_id, list_all, and delete_by_id through repository."""
    tenant_id = "tenant-repo-1"

    async with tenant_session(tenant_id) as session:
        repo = BaseRepository(SampleItem, session, tenant_id)

        # 1. Create
        item = SampleItem(name="First Item")
        created = await repo.create(item)
        assert created.id is not None
        assert created.tenant_id == tenant_id

        # 2. Get by ID
        fetched = await repo.get_by_id(created.id)
        assert fetched is not None
        assert fetched.name == "First Item"

        # 3. List
        items = await repo.list_all()
        assert len(items) == 1
        assert items[0].id == created.id

        # 4. Delete
        deleted = await repo.delete_by_id(created.id)
        assert deleted is True

        # 5. Verify deleted
        fetched_after = await repo.get_by_id(created.id)
        assert fetched_after is None
