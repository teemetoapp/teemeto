"""Channel-agnostic normalized message schemas and webhook responses."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ChannelType = Literal["telegram", "instagram"]


class NormalizedMessage(BaseModel):
    """
    Channel-agnostic message representation.
    Normalizes Telegram, Instagram, and future channels into a uniform format.
    """

    id: str = Field(default_factory=lambda: str(uuid4()), description="Internal unique message ID")
    tenant_id: str = Field(..., description="Target tenant ID")
    channel: ChannelType = Field(..., description="Channel source")
    external_account_id: str = Field(..., description="Channel account ID (e.g. bot username)")
    conversation_id: str = Field(..., description="Channel conversation or chat ID")
    external_message_id: str = Field(..., description="Unique message ID on external platform")
    idempotency_key: str = Field(..., description="Deterministic idempotency key for deduplication")
    sender_id: str = Field(..., description="External sender ID")
    sender_name: str | None = Field(default=None, description="Display name or username of sender")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Message creation timestamp",
    )
    text: str | None = Field(default=None, description="Extracted plain text content")
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Raw incoming update payload for audit"
    )

    @classmethod
    def generate_idempotency_key(
        cls,
        tenant_id: str,
        channel: ChannelType,
        conversation_id: str,
        external_message_id: str,
    ) -> str:
        """Constructs a deterministic idempotency key."""
        return f"{tenant_id}:{channel}:{conversation_id}:{external_message_id}"


class WebhookResponse(BaseModel):
    """Standardized response returned by webhook ingestion endpoints."""

    status: Literal["accepted", "ignored", "error"] = Field(..., description="Processing status")
    reason: str | None = Field(default=None, description="Explanation when ignored or failed")
    idempotency_key: str | None = Field(default=None, description="Deduplication key")
    message: NormalizedMessage | None = Field(
        default=None, description="Normalized message if accepted"
    )
