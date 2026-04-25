"""Redis Pub/Sub lifecycle subscriber.

Provides the :func:`read_lifecycle` async context manager that opens a Redis
Pub/Sub subscription on the per-thread lifecycle channel and pumps incoming
messages onto an ``asyncio.Queue``.

Lifecycle events are published directly to Redis Pub/Sub by
:func:`~backend.sse_notifications.channel.publish_lifecycle` — no PostgreSQL
NOTIFY/LISTEN fanout is involved.

Connection budget
-----------------
N active SSE sessions each open one cheap Redis Pub/Sub connection.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

from backend.db.redis.router import get_redis_router

logger = logging.getLogger(__name__)

# Redis Pub/Sub key prefix for per-thread lifecycle channels.
_LIFECYCLE_PREFIX = "lifecycle:"


def lifecycle_pub_channel(thread_id: str) -> str:
    """Return the Redis Pub/Sub channel name for lifecycle events of *thread_id*.

    Args:
        thread_id: LangGraph UUID thread identifier.

    Returns:
        Channel name, e.g. ``"lifecycle:<uuid>"``.
    """
    return f"{_LIFECYCLE_PREFIX}{thread_id}"


@asynccontextmanager
async def read_lifecycle(
    thread_id: str,
) -> AsyncGenerator[asyncio.Queue[str], None]:
    """Async context manager that reads lifecycle events from Redis Pub/Sub.

    Subscribes to ``lifecycle:<thread_id>`` and pumps each JSON message payload
    onto an ``asyncio.Queue``.  Both the Pub/Sub subscription and the Redis
    connection are cleaned up on context-manager exit.

    Events are published directly by
    :func:`~backend.sse_notifications.channel.publish_lifecycle` after each DB
    commit — no fanout task is required.

    Args:
        thread_id: LangGraph thread ID to subscribe for.

    Yields:
        Queue of raw JSON lifecycle event payloads (strings).
    """
    # Connect to the shard that owns this thread_id so the SUBSCRIBE lands on
    # the same Redis node where lifecycle_fanout PUBLISHes this thread's events.
    client = aioredis.from_url(
        get_redis_router().get_url_for_thread(thread_id),
        decode_responses=True,
    )
    pubsub = client.pubsub()
    channel = lifecycle_pub_channel(thread_id)
    queue: asyncio.Queue[str] = asyncio.Queue()

    await pubsub.subscribe(channel)
    logger.debug("[lifecycle_subscriber.read_lifecycle] subscribed channel=%s", channel)

    async def _pump() -> None:
        """Background task — relay Pub/Sub messages onto the queue."""
        msg_count = 0
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                raw: str = message["data"]
                queue.put_nowait(raw)
                msg_count += 1
                if msg_count == 1:
                    try:
                        parsed = json.loads(raw)
                        logger.debug(
                            "[lifecycle_subscriber._pump] first_message event=%s channel=%s",
                            parsed.get("event", "?"),
                            channel,
                        )
                    except Exception:  # noqa: BLE001
                        logger.debug(
                            "[lifecycle_subscriber._pump] first_message channel=%s",
                            channel,
                        )
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[lifecycle_subscriber._pump] error channel=%s: %s", channel, exc
            )

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
        logger.debug(
            "[lifecycle_subscriber.read_lifecycle] unsubscribed channel=%s", channel
        )


__all__ = ["read_lifecycle"]
