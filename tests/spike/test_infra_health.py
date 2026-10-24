"""
Spike test for validating PostgreSQL + pgvector and Redis infrastructure health.
Part of Task 0.1 acceptance criteria.
"""

import os

import pytest
import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://teemeto_user:teemeto_pass@localhost:5432/teemeto_db"
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


@pytest.mark.asyncio
async def test_redis_connection() -> None:
    """Verifies Redis connection and PING/PONG responsiveness."""
    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        pong = await client.ping()
        assert pong is True
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_postgres_pgvector_extension() -> None:
    """Verifies PostgreSQL connection and the presence of the pgvector extension."""
    engine = create_async_engine(DATABASE_URL, echo=False)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector';")
            )
            row = result.fetchone()
            assert row is not None, "pgvector extension is not installed or enabled in database"
            assert row[0] == "vector"
    finally:
        await engine.dispose()
