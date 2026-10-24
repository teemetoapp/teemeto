"""PostgreSQL pgvector implementation of the MemoryStore interface."""

import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.errors import TenantContextError
from packages.shared.memory.base import MemoryChunk, MemorySearchResult, MemoryStore


class PgVectorMemoryStore(MemoryStore):
    """
    Vector memory store backed by PostgreSQL pgvector extension.
    Relies on tenant_session and database RLS to enforce tenant isolation.
    """

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: str,
        table_name: str = "knowledge_chunks",
    ) -> None:
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise TenantContextError("MemoryStore requires a valid tenant_id.")
        self.session = session
        self.tenant_id = tenant_id.strip()
        self.table_name = table_name

    async def store_chunk(self, chunk: MemoryChunk) -> MemoryChunk:
        """Stores a chunk in PostgreSQL with vector embedding."""
        # Enforce tenant_id matches the active store scope
        scoped_chunk = chunk.model_copy(update={"tenant_id": self.tenant_id})

        # Format vector as string for pgvector input: "[0.1, 0.2, ...]"
        vector_str = f"[{','.join(str(f) for f in scoped_chunk.embedding)}]"
        metadata_json = json.dumps(scoped_chunk.metadata)

        stmt = text(f"""
            INSERT INTO {self.table_name} (id, tenant_id, content, embedding, metadata)
            VALUES (:id, :tenant_id, :content, :embedding, CAST(:metadata AS jsonb))
            ON CONFLICT (id) DO UPDATE SET
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata
        """)

        await self.session.execute(
            stmt,
            {
                "id": scoped_chunk.id,
                "tenant_id": self.tenant_id,
                "content": scoped_chunk.content,
                "embedding": vector_str,
                "metadata": metadata_json,
            },
        )
        return scoped_chunk

    async def search_similar(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[MemorySearchResult]:
        """
        Retrieves the top_k closest chunks using cosine distance (<=>).
        Cosine similarity = 1.0 - cosine_distance.
        """
        vector_str = f"[{','.join(str(f) for f in query_embedding)}]"

        stmt = text(f"""
            SELECT id, tenant_id, content, CAST(embedding AS text) AS embedding_str, metadata,
                   (1.0 - (embedding <=> :query_vector)) AS similarity_score
            FROM {self.table_name}
            WHERE (1.0 - (embedding <=> :query_vector)) >= :min_score
            ORDER BY embedding <=> :query_vector ASC
            LIMIT :top_k
        """)

        result = await self.session.execute(
            stmt,
            {
                "query_vector": vector_str,
                "min_score": min_score,
                "top_k": top_k,
            },
        )

        matches: list[MemorySearchResult] = []
        for row in result.mappings().all():
            # Parse embedding from string back to list of floats
            raw_emb = cast(str, row["embedding_str"])
            emb_list = [float(x.strip()) for x in raw_emb.strip("[]").split(",") if x.strip()]

            meta = row["metadata"]
            if isinstance(meta, str):
                meta = json.loads(meta)
            elif meta is None:
                meta = {}

            chunk = MemoryChunk(
                id=row["id"],
                tenant_id=row["tenant_id"],
                content=row["content"],
                embedding=emb_list,
                metadata=meta,
            )
            matches.append(MemorySearchResult(chunk=chunk, score=float(row["similarity_score"])))

        return matches

    async def delete_chunk(self, chunk_id: UUID) -> bool:
        """Deletes a chunk by ID within the tenant scope."""
        stmt = text(f"DELETE FROM {self.table_name} WHERE id = :id AND tenant_id = :tenant_id")
        result = await self.session.execute(
            stmt,
            {"id": chunk_id, "tenant_id": self.tenant_id},
        )
        cursor_result = cast(CursorResult[Any], result)
        return bool(cursor_result.rowcount > 0)
