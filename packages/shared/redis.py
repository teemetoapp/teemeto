"""Redis client utilities and atomic idempotency operations."""

from typing import Any

import redis.asyncio as aioredis

from packages.shared.config.settings import get_settings

_redis_client: aioredis.Redis | None = None


def get_redis_client() -> aioredis.Redis:
    """Returns the singleton async Redis client."""
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    """Closes active Redis connection."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def check_and_set_idempotency(
    key: str,
    ttl_seconds: int = 86400,
    client: Any = None,
) -> bool:
    """
    Atomically checks if a key exists; if not, sets it with an expiration.

    Returns:
        bool: True if key was newly set (first time seen),
              False if key was already present (duplicate message).
    """
    redis_conn = client or get_redis_client()
    # SET key 1 NX EX ttl_seconds
    is_new = await redis_conn.set(
        name=key,
        value="1",
        nx=True,
        ex=ttl_seconds,
    )
    return bool(is_new)
