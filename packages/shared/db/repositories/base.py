"""Base repository interface implementing standard CRUD operations with tenant scoping."""

from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.errors import TenantContextError


class BaseRepository[ModelType]:
    """
    Generic base repository ensuring all operations are bound to a session and tenant.
    All subclasses inherit standard typed query methods.
    """

    def __init__(self, model_class: type[ModelType], session: AsyncSession, tenant_id: str) -> None:
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise TenantContextError("Repository cannot be initialized without a valid tenant_id.")
        self.model_class = model_class
        self.session = session
        self.tenant_id = tenant_id.strip()

    async def get_by_id(self, item_id: Any) -> ModelType | None:
        """Fetch a single record by primary key."""
        stmt = select(self.model_class).where(self.model_class.id == item_id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[ModelType]:
        """List records with pagination."""
        stmt = select(self.model_class).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, instance: ModelType) -> ModelType:
        """Add and flush a new record."""
        # Ensure tenant_id on model matches repository scope if attribute exists
        if hasattr(instance, "tenant_id"):
            instance.tenant_id = self.tenant_id
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def delete_by_id(self, item_id: Any) -> bool:
        """Delete a record by primary key."""
        stmt = delete(self.model_class).where(self.model_class.id == item_id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        cursor_result = cast(CursorResult[Any], result)
        return bool(cursor_result.rowcount > 0)
