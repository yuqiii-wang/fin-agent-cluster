"""Redis Pub/Sub lifecycle subscriber.

Provides the :func:`read_lifecycle` async context manager that opens a Redis
Pub/Sub subscription on the per-thread lifecycle channel and pumps incoming
messages onto an ``asyncio.Queue``.

Replaces the previous ``backend.db.postgres.listener.pg_listen`` approach:
instead of each SSE session holding a dedicated psycopg3 PG connection, every
subscriber creates a single cheap Redis Pub/Sub connection.  The sole PG
connection is held by the fanout task in
:mod:`backend.db.redis.lifecycle_fanout`.

Connection budget (new vs old)
-------------------------------
N active SSE sessions:

  Old: N psycopg3 PG connections (heavy)
  New: 1 PG connection (fanout) + N Redis Pub/Sub connections (lightweight)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

from backend.config import get_settings
from backend.db.redis.lifecycle_fanout import lifecycle_pub_channel

logger = logging.getLogger(__name__)


@asynccontextmanager
async def read_lifecycle(
    thread_id: str,
) -> AsyncGenerator[asyncio.Queue[str], None]:
    """Async context manager that reads lifecycle events from Redis Pub/Sub.

    Subscribes to ``lifecycle:<thread_id>`` and pumps each JSON message payload
    onto an ``asyncio.Queue``.  Both the Pub/Sub subscription and the Redis
    connection are cleaned up on context-manager exit.

    The fanout task (:func:`~backend.db.redis.lifecycle_fanout.run_lifecycle_fanout`)
    must be running for messages to arrive; if it is not running, the queue
    simply stays empty until the drain-cycle timeout recovers missed events.

    Args:
        thread_id: LangGraph thread ID to subscribe for.

    Yields:
        Queue of raw JSON lifecycle event payloads (strings).
    """
    settings = get_settings()
    client = aioredis.from_url(settings.DATABASE_REDIS_URL, decode_responses=True)
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
