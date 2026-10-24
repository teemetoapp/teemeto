"""
Spike test validating Telegram webhook ingestion, message normalization, and Redis idempotency.
Acceptance test for Task 0.4.
"""

from collections.abc import AsyncGenerator

import httpx
import pytest
from main import app

from packages.shared.redis import close_redis, get_redis_client


@pytest.fixture(autouse=True)
async def cleanup_redis_keys() -> AsyncGenerator[None, None]:
    """Cleans up idempotency keys in Redis before and after each test."""
    client = get_redis_client()
    # Flush or delete test keys
    keys = await client.keys("idempotency:*")
    if keys:
        await client.delete(*keys)
    yield
    keys = await client.keys("idempotency:*")
    if keys:
        await client.delete(*keys)
    await close_redis()


@pytest.mark.asyncio
async def test_telegram_webhook_idempotency_and_normalization() -> None:
    """
    Verifies that:
    1. First incoming message is accepted and properly normalized.
    2. Exact duplicate message is detected via Redis and ignored.
    3. New message with different ID is accepted.
    """
    tenant_id = "tenant-coffee-shop"

    update_payload_1 = {
        "update_id": 99901,
        "message": {
            "message_id": 1001,
            "from": {
                "id": 888123,
                "is_bot": False,
                "first_name": "Ali",
                "username": "ali_customer",
            },
            "chat": {
                "id": 777456,
                "type": "private",
                "username": "ali_customer",
            },
            "date": 1729780000,
            "text": "سلام، منوی قیمت قهوه رو می‌خواستم",
        },
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. First webhook delivery
        resp1 = await client.post(
            f"/webhooks/telegram/{tenant_id}",
            json=update_payload_1,
        )
        assert resp1.status_code == 200
        data1 = resp1.json()

        assert data1["status"] == "accepted"
        assert data1["reason"] is None
        assert data1["idempotency_key"] == f"{tenant_id}:telegram:777456:1001"
        assert data1["message"] is not None
        assert data1["message"]["tenant_id"] == tenant_id
        assert data1["message"]["channel"] == "telegram"
        assert data1["message"]["conversation_id"] == "777456"
        assert data1["message"]["external_message_id"] == "1001"
        assert data1["message"]["sender_id"] == "888123"
        assert data1["message"]["sender_name"] == "Ali"
        assert data1["message"]["text"] == "سلام، منوی قیمت قهوه رو می‌خواستم"

        # 2. Second webhook delivery with identical message_id (Simulated duplicate delivery)
        resp2 = await client.post(
            f"/webhooks/telegram/{tenant_id}",
            json=update_payload_1,
        )
        assert resp2.status_code == 200
        data2 = resp2.json()

        assert data2["status"] == "ignored"
        assert data2["reason"] == "duplicate"
        assert data2["idempotency_key"] == f"{tenant_id}:telegram:777456:1001"
        assert data2["message"] is None

        # 3. Third webhook delivery with different message_id
        update_payload_2 = {
            "update_id": 99902,
            "message": {
                "message_id": 1002,
                "from": {"id": 888123, "first_name": "Ali"},
                "chat": {"id": 777456, "type": "private"},
                "date": 1729780010,
                "text": "و ساعت کاری شعبه مرکزی؟",
            },
        }

        resp3 = await client.post(
            f"/webhooks/telegram/{tenant_id}",
            json=update_payload_2,
        )
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert data3["status"] == "accepted"
        assert data3["message"]["external_message_id"] == "1002"
        assert data3["message"]["text"] == "و ساعت کاری شعبه مرکزی؟"


@pytest.mark.asyncio
async def test_unsupported_update_type_ignored() -> None:
    """Verifies that empty or unsupported update types are gracefully ignored."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/telegram/tenant-test",
            json={"update_id": 99999, "poll": {"id": "p1"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ignored"
        assert data["reason"] == "unsupported_or_empty_update_type"


@pytest.mark.asyncio
async def test_invalid_payload_rejected() -> None:
    """Verifies that malformed messages missing message_id or chat return 422."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/telegram/tenant-test",
            json={"update_id": 123, "message": {"text": "No ID or chat"}},
        )
        assert resp.status_code == 422
