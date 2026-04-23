"""Redis Pub/Sub cancel signal — cross-instance asyncio.Task cancellation.

When ``POST /query/{thread_id}/cancel`` is served by any FastAPI instance it
publishes a cancel message to Redis.  Every instance runs a background
subscriber that listens and cancels the local asyncio.Task if it owns it.

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

from backend.config import get_settings

logger = logging.getLogger(__name__)

_CANCEL_PREFIX = "cancel:"


async def publish_cancel(thread_id: str, reason: str) -> None:
    """Publish a cancel signal for *thread_id* to Redis Pub/Sub.

    All FastAPI instances subscribe to the ``cancel:*`` pattern; the one that
    owns the asyncio.Task will cancel it on receipt.

    Args:
        thread_id: LangGraph UUID.
        reason:    Cancellation reason (``"user"`` or ``"timeout"``).
    """
    try:
        settings = get_settings()
        client = aioredis.from_url(settings.DATABASE_REDIS_URL, decode_responses=True)
        try:
            await client.publish(f"{_CANCEL_PREFIX}{thread_id}", reason)
            logger.debug("[cancel_signal] published thread_id=%s reason=%s", thread_id, reason)
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cancel_signal] publish failed thread_id=%s: %s", thread_id, exc)


async def run_cancel_listener(running_tasks: dict) -> None:
    """Subscribe to ``cancel:*`` and cancel local asyncio.Tasks on receipt.

    Designed to run as a long-lived ``asyncio.create_task`` from the FastAPI
    lifespan context.  Reconnects automatically on Redis errors using
    exponential back-off.

    Args:
        running_tasks: The shared ``backend.api.registry.running_tasks`` dict.
                       Tasks registered here will be cancelled when a matching
                       cancel signal arrives.
    """
    settings = get_settings()
    delay = 1.0
    while True:
        client: aioredis.Redis | None = None
        pubsub = None
        try:
            client = aioredis.from_url(settings.DATABASE_REDIS_URL, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.psubscribe(f"{_CANCEL_PREFIX}*")
            logger.info("[cancel_signal] subscribed to cancel:* pattern")
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
                        "[cancel_signal] local_task_cancelled thread_id=%s reason=%s",
                        thread_id, reason,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[cancel_signal] listener error, retrying in %.0fs: %s",
                delay, exc,
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


__all__ = ["publish_cancel", "run_cancel_listener"]
