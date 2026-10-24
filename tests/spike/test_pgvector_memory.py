"""
Spike test for validating pgvector semantic search, HNSW indexing, and multi-tenant isolation.
Acceptance test for Task 0.3.
"""

import math
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from sqlalchemy import text

from packages.shared.db.session import admin_session, dispose_engines, tenant_session
from packages.shared.memory.base import MemoryChunk
from packages.shared.memory.pgvector_store import PgVectorMemoryStore

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS test_knowledge_chunks (
        id UUID PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        content TEXT NOT NULL,
        embedding vector(4) NOT NULL,
        metadata JSONB DEFAULT '{}'::jsonb
    )
    """,
    "ALTER TABLE test_knowledge_chunks ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE test_knowledge_chunks FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS chunks_tenant_policy ON test_knowledge_chunks",
    """
    CREATE POLICY chunks_tenant_policy ON test_knowledge_chunks
        FOR ALL
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
    """,
    "GRANT ALL ON test_knowledge_chunks TO teemeto_app",
    """
    CREATE INDEX IF NOT EXISTS test_knowledge_chunks_hnsw_idx
    ON test_knowledge_chunks USING hnsw (embedding vector_cosine_ops)
    """,
]


@pytest.fixture(autouse=True)
async def setup_and_cleanup_vector_table() -> AsyncGenerator[None, None]:
    """Sets up the test vector table with HNSW index and RLS, truncating between tests."""
    async with admin_session() as session:
        for stmt in DDL_STATEMENTS:
            await session.execute(text(stmt))
        await session.execute(text("TRUNCATE TABLE test_knowledge_chunks;"))
    yield
    await dispose_engines()


@pytest.mark.asyncio
async def test_store_and_search_cosine_similarity() -> None:
    """Verifies storing vector chunks and performing ranked semantic similarity search."""
    tenant_id = "tenant-ai-1"

    async with tenant_session(tenant_id) as session:
        store = PgVectorMemoryStore(session, tenant_id, table_name="test_knowledge_chunks")

        # Normalize vector 2: [1/sqrt(2), 1/sqrt(2), 0, 0] ~ [0.7071, 0.7071, 0, 0]
        val = 1.0 / math.sqrt(2)

        chunk_exact = MemoryChunk(
            id=uuid4(),
            tenant_id=tenant_id,
            content="Python AI Agent Architecture",
            embedding=[1.0, 0.0, 0.0, 0.0],
            metadata={"source": "docs/architecture.md"},
        )
        chunk_close = MemoryChunk(
            id=uuid4(),
            tenant_id=tenant_id,
            content="Python Backend Services",
            embedding=[val, val, 0.0, 0.0],
            metadata={"source": "docs/backend.md"},
        )
        chunk_orthogonal = MemoryChunk(
            id=uuid4(),
            tenant_id=tenant_id,
            content="Italian Pasta Recipe",
            embedding=[0.0, 0.0, 1.0, 0.0],
            metadata={"source": "recipes/pasta.md"},
        )

        await store.store_chunk(chunk_exact)
        await store.store_chunk(chunk_close)
        await store.store_chunk(chunk_orthogonal)

        # Query with [1.0, 0.0, 0.0, 0.0]
        query_vector = [1.0, 0.0, 0.0, 0.0]
        results = await store.search_similar(query_embedding=query_vector, top_k=5, min_score=0.1)

        # Assert results order and scores
        assert len(results) == 2  # Orthogonal chunk has score 0.0, below min_score 0.1
        assert results[0].chunk.id == chunk_exact.id
        assert abs(results[0].score - 1.0) < 1e-4

        assert results[1].chunk.id == chunk_close.id
        assert abs(results[1].score - val) < 1e-3


@pytest.mark.asyncio
async def test_vector_cross_tenant_isolation() -> None:
    """
    Verifies that vector search strictly adheres to tenant boundary:
    Tenant B querying with the exact vector of Tenant A cannot discover Tenant A's data.
    """
    tenant_a = "tenant-vector-alpha"
    tenant_b = "tenant-vector-beta"

    # Tenant A stores proprietary knowledge
    async with tenant_session(tenant_a) as session_a:
        store_a = PgVectorMemoryStore(session_a, tenant_a, table_name="test_knowledge_chunks")
        secret_chunk = MemoryChunk(
            id=uuid4(),
            tenant_id=tenant_a,
            content="Top Secret Financial Roadmap",
            embedding=[0.5, 0.5, 0.5, 0.5],
            metadata={"classified": True},
        )
        await store_a.store_chunk(secret_chunk)

    # Tenant B searches with the exact same vector
    async with tenant_session(tenant_b) as session_b:
        store_b = PgVectorMemoryStore(session_b, tenant_b, table_name="test_knowledge_chunks")
        results_b = await store_b.search_similar(
            query_embedding=[0.5, 0.5, 0.5, 0.5],
            top_k=10,
            min_score=0.0,
        )

        # Assert Tenant B gets ZERO results
        assert len(results_b) == 0, "Vector search leaked cross-tenant embeddings!"


@pytest.mark.asyncio
async def test_delete_chunk() -> None:
    """Verifies chunk deletion within tenant scope."""
    tenant_id = "tenant-del-test"

    async with tenant_session(tenant_id) as session:
        store = PgVectorMemoryStore(session, tenant_id, table_name="test_knowledge_chunks")
        chunk = MemoryChunk(
            id=uuid4(),
            tenant_id=tenant_id,
            content="Temporary Chunk",
            embedding=[0.0, 1.0, 0.0, 0.0],
        )
        await store.store_chunk(chunk)

        # Delete chunk
        deleted = await store.delete_chunk(chunk.id)
        assert deleted is True

        # Search should return nothing
        results = await store.search_similar([0.0, 1.0, 0.0, 0.0], top_k=5)
        assert len(results) == 0
