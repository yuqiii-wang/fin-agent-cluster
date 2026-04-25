"""Redis Pub/Sub cancel signal — cross-instance asyncio.Task cancellation.

When ``POST /query/{thread_id}/cancel`` is served by any FastAPI instance it
publishes a cancel message to the Redis shard that owns the thread.  Every
instance runs background listeners on **all** shards so a cancel originating
on any shard is delivered regardless of which node the task lives on.

Channel: ``cancel:{thread_id}``
Payload: reason string (e.g. ``"user"``, ``"timeout"``)

The cancel endpoint handles the DB update and ``done`` SSE event itself
(instance-agnostic via WHERE-based atomic claim).  The Pub/Sub signal exists
solely to deliver ``task.cancel()`` to whichever instance owns the Task object.
"""

from __future__ import annotations

import asyncio
import logging

import redis.asyncio as aioredis

from backend.db.redis.router import get_redis_router

logger = logging.getLogger(__name__)

_CANCEL_PREFIX = "cancel:"


async def publish_cancel(thread_id: str, reason: str) -> None:
    """Publish a cancel signal for *thread_id* to the correct Redis shard.

    Routes to the shard determined by hashing *thread_id*, matching where
    the session's run_cancel_listener subscription resides.

    Args:
        thread_id: LangGraph UUID.
        reason:    Cancellation reason (``"user"`` or ``"timeout"``).
    """
    try:
        url = get_redis_router().get_url_for_thread(thread_id)
        client = aioredis.from_url(url, decode_responses=True)
        try:
            await client.publish(f"{_CANCEL_PREFIX}{thread_id}", reason)
            logger.debug("[cancel_signal] published thread_id=%s reason=%s", thread_id, reason)
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cancel_signal] publish failed thread_id=%s: %s", thread_id, exc)


async def _listen_on_shard(url: str, running_tasks: dict, shard_index: int) -> None:
    """Subscribe to ``cancel:*`` on a single Redis shard and dispatch cancellations.

    Reconnects automatically on errors using exponential back-off.  Designed to
    run as a long-lived asyncio task.

    Args:
        url:           Redis URL for this shard.
        running_tasks: Shared dict of thread_id → asyncio.Task.
        shard_index:   Zero-based shard index (used only for log labels).
    """
    delay = 1.0
    while True:
        client: aioredis.Redis | None = None
        pubsub = None
        try:
            client = aioredis.from_url(url, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.psubscribe(f"{_CANCEL_PREFIX}*")
            logger.info("[cancel_signal] subscribed shard=%d url=%s", shard_index, url)
            delay = 1.0
            async for msg in pubsub.listen():
                if msg["type"] != "pmessage":
                    continue
                channel: str = msg["channel"]
                reason: str = msg["data"] or "user"
                thread_id = channel.removeprefix(_CANCEL_PREFIX)
                task = running_tasks.get(thread_id)
                if task is not None and not task.done():
                    task.cancel()
                    logger.info(
                        "[cancel_signal] local_task_cancelled thread_id=%s reason=%s shard=%d",
                        thread_id, reason, shard_index,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[cancel_signal] shard=%d error, retrying in %.0fs: %s",
                shard_index, delay, exc,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe()
                except Exception:  # noqa: BLE001
                    pass
            if client is not None:
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001
                    pass


async def run_cancel_listener(running_tasks: dict) -> None:
    """Subscribe to ``cancel:*`` on every Redis shard and cancel local tasks on receipt.

    Spawns one listener task per shard so cancel signals published to any node
    are received regardless of the thread routing.  Designed to run as a
    long-lived ``asyncio.create_task`` from the FastAPI lifespan context.

    Args:
        running_tasks: The shared ``backend.api.registry.running_tasks`` dict.
                       Tasks registered here will be cancelled when a matching
                       cancel signal arrives.
    """
    router = get_redis_router()
    shard_tasks = [
        asyncio.create_task(
            _listen_on_shard(router.get_url_at(i), running_tasks, i),
            name=f"cancel-listener-shard-{i}",
        )
        for i in range(router.node_count)
    ]
    try:
        await asyncio.gather(*shard_tasks)
    except asyncio.CancelledError:
        for t in shard_tasks:
            t.cancel()
        raise


__all__ = ["publish_cancel", "run_cancel_listener"]
