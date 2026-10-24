"""Telegram webhook ingestion router with atomic Redis idempotency."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Path, status

from packages.shared.redis import check_and_set_idempotency
from packages.shared.schemas.message import NormalizedMessage, WebhookResponse

router = APIRouter(prefix="/webhooks/telegram", tags=["telegram"])


@router.post(
    "/{tenant_id}",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest Telegram webhook updates",
)
async def ingest_telegram_webhook(
    tenant_id: str = Path(..., description="Target tenant identifier"),
    update: dict[str, Any] = ...,  # type: ignore[assignment]
    x_telegram_bot_api_secret_token: str | None = Header(
        default=None, alias="X-Telegram-Bot-Api-Secret-Token"
    ),
) -> WebhookResponse:
    """
    Receives incoming Telegram updates, validates structural integrity,
    normalizes payload to NormalizedMessage, and deduplicates with Redis.
    """
    if not tenant_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A non-empty tenant_id is required.",
        )

    # Extract relevant message payload from update
    msg = update.get("message") or update.get("channel_post") or update.get("edited_message")
    if not msg or not isinstance(msg, dict):
        return WebhookResponse(
            status="ignored",
            reason="unsupported_or_empty_update_type",
        )

    msg_id = msg.get("message_id")
    chat = msg.get("chat", {})
    chat_id = chat.get("id")

    if msg_id is None or chat_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Missing message_id or chat.id in Telegram payload.",
        )

    str_msg_id = str(msg_id)
    str_chat_id = str(chat_id)
    from_user = msg.get("from") or {}
    sender_id = str(from_user.get("id") or str_chat_id)
    sender_name = from_user.get("first_name") or from_user.get("username")

    # Extract date
    date_val = msg.get("date")
    if date_val and isinstance(date_val, (int, float)):
        msg_timestamp = datetime.fromtimestamp(date_val, tz=UTC)
    else:
        msg_timestamp = datetime.now(UTC)

    # Extract text content
    text_content = msg.get("text") or msg.get("caption")

    # Generate unique idempotency key
    idempotency_key = NormalizedMessage.generate_idempotency_key(
        tenant_id=tenant_id,
        channel="telegram",
        conversation_id=str_chat_id,
        external_message_id=str_msg_id,
    )

    # Atomically check and lock key in Redis
    redis_key = f"idempotency:{idempotency_key}"
    is_new = await check_and_set_idempotency(redis_key, ttl_seconds=86400)

    if not is_new:
        return WebhookResponse(
            status="ignored",
            reason="duplicate",
            idempotency_key=idempotency_key,
        )

    # Normalize message
    normalized = NormalizedMessage(
        tenant_id=tenant_id,
        channel="telegram",
        external_account_id=str(chat.get("username") or "telegram_bot"),
        conversation_id=str_chat_id,
        external_message_id=str_msg_id,
        idempotency_key=idempotency_key,
        sender_id=sender_id,
        sender_name=sender_name,
        timestamp=msg_timestamp,
        text=text_content,
        payload=update,
    )

    return WebhookResponse(
        status="accepted",
        idempotency_key=idempotency_key,
        message=normalized,
    )
