"""Lifecycle event fanout — single PG LISTEN → Redis PUBLISH with leader election.

Runs a single asyncio background task that holds **one** psycopg3 connection
and LISTENs on the shared ``sse_lifecycle`` PostgreSQL channel.  Every
incoming notification is PUBLISH-ed to a per-thread Redis Pub/Sub channel
(``lifecycle:<thread_id>``) so SSE subscribers read from Redis only, without
opening their own PG connections.

This eliminates the O(N) PG connection overhead of the previous per-subscriber
``pg_listen`` architecture.  N active SSE sessions now consume:

  * **1** PG connection (this module)
  * **N** Redis Pub/Sub subscriptions (cheap; multiplexed over the pool)

Leader election
---------------
When multiple FastAPI instances run concurrently, only one should hold the PG
LISTEN connection and PUBLISH to Redis — otherwise every SSE client receives
each lifecycle event twice.  A :class:`~backend.db.redis.lock_manager.redis_lock.RedisLock`
with auto-renewal and parent-task liveness polling ensures exactly one instance
acts as fanout leader at any time.

Lock key: ``lock:lifecycle_fanout``
TTL:      300 s  (renewed every :data:`_RENEWAL_INTERVAL` seconds by the leader).
On leader crash the lock expires and a standby instance takes over within 300 s.

Startup
-------
Call :func:`run_lifecycle_fanout` as an ``asyncio.create_task`` in the FastAPI
lifespan context.  The task runs forever, auto-reconnecting on PG errors with
exponential back-off.

Channel naming
--------------
``lifecycle_pub_channel(thread_id)`` — Redis Pub/Sub channel for a given thread.
The shared PG NOTIFY channel name is the module-level constant imported from
``backend.sse_notifications.channel.SHARED_LIFECYCLE_CHANNEL``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import redis.asyncio as aioredis
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from backend.config import get_settings
from backend.db.redis.lock_manager.redis_lock import RedisLock

logger = logging.getLogger(__name__)

# Redis Pub/Sub key prefix for per-thread lifecycle channels.
_LIFECYCLE_PREFIX = "lifecycle:"

# How long (seconds) psycopg3 waits for a NOTIFY before looping.
# Controls responsiveness to clean cancellation when the channel is quiet.
_NOTIFY_TIMEOUT = 30.0

# Reconnect back-off bounds (seconds).
_RECONNECT_BASE = 1.0
_RECONNECT_MAX = 60.0

# Leader-election lock settings (forwarded to RedisLock).
_FANOUT_LOCK_KEY = "lock:lifecycle_fanout"
_LOCK_TTL = 300         # seconds (5 min); must be > _RENEWAL_INTERVAL * 2
_RENEWAL_INTERVAL = 12  # seconds between lock renewals by the leader
_PARENT_POLL_INTERVAL = 60  # seconds between parent-task liveness checks


def lifecycle_pub_channel(thread_id: str) -> str:
    """Return the Redis Pub/Sub channel name for lifecycle events of *thread_id*.

    Args:
        thread_id: LangGraph UUID thread identifier.

    Returns:
        Channel name, e.g. ``"lifecycle:<uuid>"``.
    """
    return f"{_LIFECYCLE_PREFIX}{thread_id}"


async def _fanout_loop(redis_client: aioredis.Redis) -> None:
    """Hold one PG connection; fan out every notification to Redis PUBLISH.

    Reconnects to PostgreSQL on any error using exponential back-off.
    Never raises — logs warnings and retries indefinitely until cancelled.

    Args:
        redis_client: Connected aioredis client used for PUBLISH operations.
    """
    # Import here to avoid a circular import at module load time.
    from backend.sse_notifications.channel import SHARED_LIFECYCLE_CHANNEL  # noqa: PLC0415

    settings = get_settings()
    delay = _RECONNECT_BASE

    while True:
        conn: Optional[AsyncConnection] = None
        try:
            conn = await AsyncConnection.connect(
                settings.DATABASE_PG_URL,
                connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
                autocommit=True,
                row_factory=dict_row,
            )
            await conn.execute(f'LISTEN "{SHARED_LIFECYCLE_CHANNEL}"')
            logger.info(
                "[lifecycle_fanout] listening pg_channel=%s",
                SHARED_LIFECYCLE_CHANNEL,
            )
            delay = _RECONNECT_BASE  # reset back-off on successful connect

            # Keep looping notifies() on the same connection so that a quiet
            # period (timeout with no notifications) does NOT cause a full PG
            # reconnect.  The inner while-True means a 30 s silence only runs
            # a lightweight SELECT 1 health-check, not a full reconnect.
            while True:
                async for notification in conn.notifies(timeout=_NOTIFY_TIMEOUT):
                    if not notification.payload:
                        continue
                    try:
                        payload = json.loads(notification.payload)
                        thread_id: str | None = payload.get("thread_id")
                        if not thread_id:
                            logger.warning(
                                "[lifecycle_fanout] missing thread_id in payload event=%s",
                                payload.get("event", "?"),
                            )
                            continue
                        channel = lifecycle_pub_channel(thread_id)
                        await redis_client.publish(channel, notification.payload)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[lifecycle_fanout] dispatch error: %s", exc)
                # notifies() timed out; verify connection is still alive before
                # looping back.  A failed health-check raises and the outer
                # except block handles reconnection with back-off.
                await conn.execute("SELECT 1")

        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[lifecycle_fanout] PG connection lost, retrying in %.0fs: %s",
                delay,
                exc,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RECONNECT_MAX)
        finally:
            if conn is not None:
                try:
                    await conn.close()
                except Exception:  # noqa: BLE001
                    pass


async def _run_with_leader_election(redis_client: aioredis.Redis) -> None:
    """Acquire the leader lock then run the fanout loop; retry as standby if lock is held.

    Uses :class:`~backend.db.redis.lock_manager.redis_lock.RedisLock` for
    automatic TTL renewal and parent-task liveness polling.  When the current
    asyncio.Task finishes (e.g. unexpectedly cancelled or crashed) but the
    normal ``__aexit__`` failed to release the lock, RedisLock force-releases
    within one :data:`_PARENT_POLL_INTERVAL` cycle so standby instances are
    not blocked until TTL expiry.

    Args:
        redis_client: Dedicated aioredis client for lock and PUBLISH operations.
    """
    while True:
        lock = RedisLock(
            redis_client,
            _FANOUT_LOCK_KEY,
            ttl=_LOCK_TTL,
            renewal_interval=_RENEWAL_INTERVAL,
            parent_poll_interval=_PARENT_POLL_INTERVAL,
            parent_task=asyncio.current_task(),
        )
        acquired = await lock.acquire()
        if not acquired:
            logger.debug(
                "[lifecycle_fanout] standby — lock held by another instance, retrying in %ds",
                int(_RENEWAL_INTERVAL),
            )
            await asyncio.sleep(_RENEWAL_INTERVAL)
            continue

        logger.info("[lifecycle_fanout] leader_acquired owner=%s", lock.owner)
        try:
            await _fanout_loop(redis_client)
        finally:
            await lock.release()


async def run_lifecycle_fanout() -> None:
    """Start the lifecycle fanout loop with leader election.  Runs until cancelled.

    Creates a dedicated aioredis client isolated from the shared pool so
    PUBLISH and lock operations are independent from subscriber Pub/Sub
    connections.

    Only the FastAPI instance that wins the ``lock:lifecycle_fanout`` Redis
    lock will hold the PG LISTEN connection and PUBLISH notifications.
    Standby instances wait and retry so they take over if the leader crashes.

    Designed to be started via ``asyncio.create_task`` in the FastAPI lifespan::

        _fanout_task = asyncio.create_task(run_lifecycle_fanout())
        yield
        _fanout_task.cancel()
    """
    settings = get_settings()
    client = aioredis.from_url(settings.DATABASE_REDIS_URL, decode_responses=True)
    try:
        await _run_with_leader_election(client)
    except asyncio.CancelledError:
        logger.info("[lifecycle_fanout] cancelled — shutting down")
    finally:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass


__all__ = ["lifecycle_pub_channel", "run_lifecycle_fanout"]
