"""Database engines and tenant-isolated session context managers."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from packages.shared.config.settings import get_settings
from packages.shared.errors import TenantContextError

_app_engine: AsyncEngine | None = None
_admin_engine: AsyncEngine | None = None
_app_session_factory: async_sessionmaker[AsyncSession] | None = None
_admin_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_app_engine() -> AsyncEngine:
    """Returns the singleton application AsyncEngine (non-superuser, enforces RLS)."""
    global _app_engine
    if _app_engine is None:
        settings = get_settings()
        if settings.environment == "testing":
            _app_engine = create_async_engine(
                settings.database_url,
                echo=False,
                poolclass=NullPool,
            )
        else:
            _app_engine = create_async_engine(
                settings.database_url,
                echo=False,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
            )
    return _app_engine


def get_admin_engine() -> AsyncEngine:
    """Returns the singleton admin AsyncEngine (used only for DDL and test fixtures)."""
    global _admin_engine
    if _admin_engine is None:
        settings = get_settings()
        if settings.environment == "testing":
            _admin_engine = create_async_engine(
                settings.database_admin_url,
                echo=False,
                poolclass=NullPool,
            )
        else:
            _admin_engine = create_async_engine(
                settings.database_admin_url,
                echo=False,
                pool_pre_ping=True,
            )
    return _admin_engine


async def dispose_engines() -> None:
    """Closes all database connections and resets engine singletons."""
    global _app_engine, _admin_engine, _app_session_factory, _admin_session_factory
    if _app_engine is not None:
        await _app_engine.dispose()
        _app_engine = None
    if _admin_engine is not None:
        await _admin_engine.dispose()
        _admin_engine = None
    _app_session_factory = None
    _admin_session_factory = None



def get_app_session_factory() -> async_sessionmaker[AsyncSession]:
    """Returns the async session factory for application operations."""
    global _app_session_factory
    if _app_session_factory is None:
        engine = get_app_engine()
        _app_session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _app_session_factory


def get_admin_session_factory() -> async_sessionmaker[AsyncSession]:
    """Returns the async session factory for administrative operations."""
    global _admin_session_factory
    if _admin_session_factory is None:
        engine = get_admin_engine()
        _admin_session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _admin_session_factory


@asynccontextmanager
async def tenant_session(tenant_id: str) -> AsyncGenerator[AsyncSession, Any]:
    """
    Context manager providing an AsyncSession strictly scoped to a tenant.

    Executes `SET LOCAL app.tenant_id = :tenant_id` at the start of the transaction
    so that PostgreSQL Row Level Security (RLS) policies are automatically enforced.
    """
    if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
        raise TenantContextError(
            "A valid, non-empty tenant_id is strictly required to open a database session."
        )

    clean_tenant_id = tenant_id.strip()
    session_factory = get_app_session_factory()

    async with session_factory() as session:
        async with session.begin():
            # Inject tenant context into PostgreSQL local transaction scope via set_config
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": clean_tenant_id},
            )
            try:
                yield session
            except Exception:
                await session.rollback()
                raise


@asynccontextmanager
async def admin_session() -> AsyncGenerator[AsyncSession, Any]:
    """
    Context manager providing an administrative AsyncSession.
    Bypasses tenant scoping; strictly reserved for DDL, migrations, and test harness setup.
    """
    session_factory = get_admin_session_factory()
    async with session_factory() as session:
        async with session.begin():
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
