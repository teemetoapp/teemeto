"""Base memory store abstraction and schemas."""

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MemoryChunk(BaseModel):
    """Normalized memory chunk with text content and vector embedding."""

    id: UUID = Field(default_factory=uuid4, description="Unique chunk identifier")
    tenant_id: str = Field(..., description="Tenant owning this chunk")
    content: str = Field(..., description="Raw text content of the chunk")
    embedding: list[float] = Field(..., description="Vector embedding representation")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary metadata (e.g. source document, title)"
    )


class MemorySearchResult(BaseModel):
    """Semantic search match containing chunk and similarity score."""

    chunk: MemoryChunk = Field(..., description="Matched memory chunk")
    score: float = Field(
        ...,
        description="Cosine similarity score (1.0 = exact match, 0.0 = orthogonal)",
    )


class MemoryStore(ABC):
    """Abstract interface for storing and querying tenant-isolated vector memories."""

    @abstractmethod
    async def store_chunk(self, chunk: MemoryChunk) -> MemoryChunk:
        """Persists a memory chunk."""
        pass

    @abstractmethod
    async def search_similar(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[MemorySearchResult]:
        """
        Retrieves the top_k most similar memory chunks based on cosine distance.
        Must strictly respect tenant isolation.
        """
        pass

    @abstractmethod
    async def delete_chunk(self, chunk_id: UUID) -> bool:
        """Deletes a chunk by its ID."""
        pass
