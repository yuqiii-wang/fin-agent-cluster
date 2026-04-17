"""Redis Pub/Sub helpers for streaming graph task events.

Replaces the previous PostgreSQL LISTEN/NOTIFY implementation.
Messages are published to a per-thread Redis channel and consumed
by SSE subscribers in real-time without polling.

Publish path (``notify``):
    Uses a shared Redis client backed by a connection pool so that
    high-frequency token events do not open a new connection per call.

Subscribe path (``listen``):
    Each SSE subscriber opens a dedicated Pub/Sub connection.  A background
    asyncio task pumps incoming messages onto an ``asyncio.Queue`` so the
    SSE generator can use the same ``await queue.get()`` interface as before.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any

import redis.asyncio as aioredis

from backend.config import get_settings

logger = logging.getLogger(__name__)

# Shared client (connection pool) reused across all publish calls.
_publish_client: aioredis.Redis | None = None


def _channel(thread_id: str) -> str:
    """Return a Redis channel name derived from the thread UUID.

    Args:
        thread_id: LangGraph UUID thread identifier.

    Returns:
        Channel name, e.g. ``stream:<uuid>``.
    """
    return f"stream:{thread_id}"


async def _get_publish_client() -> aioredis.Redis:
    """Return (or lazily create) the shared publish Redis client.

    Returns:
        A connected ``redis.asyncio.Redis`` instance backed by a pool.
    """
    global _publish_client
    if _publish_client is None:
        settings = get_settings()
        _publish_client = aioredis.from_url(
            settings.DATABASE_REDIS_URL,
            decode_responses=True,
        )
    return _publish_client


async def notify(thread_id: str, payload: dict) -> None:
    """Publish *payload* to the thread's Redis Pub/Sub channel.

    Args:
        thread_id: LangGraph thread ID that identifies the channel.
        payload:   Dict to JSON-encode as the message payload.
    """

    def _default(obj: Any) -> str:
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    try:
        client = await _get_publish_client()
        channel = _channel(thread_id)
        await client.publish(channel, json.dumps(payload, default=_default))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[streaming.notify] failed thread_id=%s: %s", thread_id, exc)


@asynccontextmanager
async def listen(
    thread_id: str,
) -> AsyncGenerator[asyncio.Queue[str], None]:
    """Async context manager that subscribes to the thread's Redis channel.

    Opens a dedicated Redis Pub/Sub connection per subscriber and spawns a
    background task that pumps incoming messages onto an ``asyncio.Queue``.
    Both are cleaned up on context-manager exit.

    Args:
        thread_id: LangGraph thread ID to subscribe to.

    Yields:
        Queue of raw JSON message payloads.
    """
    settings = get_settings()
    client: aioredis.Redis = aioredis.from_url(
        settings.DATABASE_REDIS_URL,
        decode_responses=True,
    )
    pubsub: aioredis.client.PubSub = client.pubsub()
    channel = _channel(thread_id)
    queue: asyncio.Queue[str] = asyncio.Queue()

    await pubsub.subscribe(channel)
    logger.debug("[streaming.listen] subscribed channel=%s", channel)

    async def _pump() -> None:
        """Background task — relay Pub/Sub messages onto the queue."""
        try:
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    queue.put_nowait(msg["data"])
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("[streaming._pump] error channel=%s: %s", channel, exc)

    pump_task: asyncio.Task[None] = asyncio.create_task(_pump())

    try:
        yield queue
    finally:
        pump_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(pump_task), timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception:  # noqa: BLE001
            pass
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass
        logger.debug("[streaming.listen] unsubscribed channel=%s", channel)
