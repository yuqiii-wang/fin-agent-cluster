"""Redis router — consistent hash-based key routing across multiple Redis nodes.

Routes all Redis operations to the correct shard using SHA-256 hashing of the
``thread_id`` so every key owned by the same logical session always lands on
the same Redis node regardless of which process computes the route.
This is required for publisher / subscriber consistency: the Celery ingest
worker and the FastAPI SSE subscriber are separate processes; they must resolve
the same ``thread_id`` to the same shard or token delivery silently fails.

Design
------
* **Thread-scoped routing** — callers pass ``thread_id``; the router maps it
  to a shard index via ``SHA-256(thread_id) % node_count``.  All key prefixes
  used in this project (``tokens:``, ``fin:query:phase:``, ``notify_pending:``,
  ``watch:``, ``lifecycle:``, ``cancel:``, ``task_ack:``) are therefore
  co-located per session.

* **Fixed-shard routing** — for global, non-thread-scoped resources (leader
  election locks, Celery broker/backend) callers use ``get_client_at(0)`` to
  pin to shard 0 regardless of node count.

* **Loop-aware client caching** — Celery workers each call ``asyncio.run()``,
  which closes the previous event loop.  The router detects loop changes and
  lazily recreates connection pools, matching the behaviour of the previous
  single-client ``_get_publish_client()`` pattern.

* **Backward compatibility** — if ``DATABASE_REDIS_NODES`` is not set, the
  router falls back to ``DATABASE_REDIS_URL`` as a single-node cluster, so the
  system works without any ``docker-compose.yml`` change until a second node is
  added.

Usage
-----
::

    from backend.db.redis.router import get_redis_router

    router = get_redis_router()

    # Thread-scoped operation
    client = router.get_client_for_thread(thread_id)
    await client.setex(key, ttl, value)

    # Pin to shard 0 (leader locks, Celery)
    client = router.get_client_at(0)
    url = router.get_url_at(0)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Optional

import redis.asyncio as aioredis

from backend.config import get_settings
from backend.db.redis.errors import REDIS_ROUTER_NO_URLS

logger = logging.getLogger(__name__)

__all__ = ["RedisRouter", "get_redis_router"]


class RedisRouter:
    """Routes Redis operations to the correct node via SHA-256 hash of thread_id.

    Attributes:
        node_count: Number of Redis nodes managed by this router.
    """

    def __init__(self, urls: list[str]) -> None:
        """Initialise the router with a list of Redis node URLs.

        Args:
            urls: Ordered list of ``redis://host:port`` URLs.  Index 0 is the
                  canonical "shard 0" used for global/pinned operations.
        """
        if not urls:
            raise ValueError(f"[{REDIS_ROUTER_NO_URLS}] RedisRouter requires at least one Redis URL")
        self._urls: list[str] = urls
        self._clients: list[Optional[aioredis.Redis]] = [None] * len(urls)
        self._loop_id: Optional[int] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reset_on_loop_change(self) -> None:
        """Detect event-loop change and invalidate all cached clients.

        When a Celery worker calls ``asyncio.run()``, the previous event loop
        is closed and all connection pools tied to it become unusable.  This
        method checks the current loop identity and, on mismatch, marks all
        clients for recreation on the next access.
        """
        try:
            current_id = id(asyncio.get_running_loop())
        except RuntimeError:
            return
        if self._loop_id != current_id:
            # Old loop is dead; discard stale clients (no close — old loop gone).
            self._clients = [None] * len(self._urls)
            self._loop_id = current_id

    def _shard_index(self, thread_id: str) -> int:
        """Return the shard index for *thread_id* using SHA-256 modulo routing.

        Deterministic across all processes — the same ``thread_id`` always maps
        to the same shard regardless of which process (FastAPI, Celery worker)
        calls this method.  This is required so that ingest writes and SSE
        subscriber reads always target the same Redis node.

        Args:
            thread_id: LangGraph UUID string.

        Returns:
            Integer shard index in ``[0, node_count)``.
        """
        digest = int(hashlib.sha256(thread_id.encode()).hexdigest(), 16)
        return digest % len(self._urls)

    def _ensure_client(self, idx: int) -> aioredis.Redis:
        """Return (lazily creating if needed) the client at *idx*.

        Args:
            idx: Shard index, must be in ``[0, node_count)``.

        Returns:
            Connected ``redis.asyncio.Redis`` instance.
        """
        if self._clients[idx] is None:
            self._clients[idx] = aioredis.from_url(
                self._urls[idx],
                decode_responses=True,
            )
            logger.debug(
                "[RedisRouter] created client shard=%d url=%s",
                idx,
                self._urls[idx],
            )
        return self._clients[idx]  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Public API — thread-scoped routing
    # ------------------------------------------------------------------

    def get_client_for_thread(self, thread_id: str) -> aioredis.Redis:
        """Return the persistent Redis client responsible for *thread_id*.

        Lazily creates the connection pool on first call per shard per event
        loop.  Safe to call repeatedly — returns the same client until the
        event loop changes.

        Args:
            thread_id: LangGraph UUID used as the hash routing key.

        Returns:
            ``redis.asyncio.Redis`` bound to the correct shard.
        """
        self._reset_on_loop_change()
        return self._ensure_client(self._shard_index(thread_id))

    def get_client_for_stream(self, stream_id: str) -> aioredis.Redis:
        """Return the persistent Redis client responsible for *stream_id*.

        Used for per-stream done-key routing (``fin:stream:ingest:done:{stream_id}``).
        Shards by ``stream_id`` so the key name and its routing key are
        semantically consistent, and so the shard can be derived from
        ``stream_id`` alone even when full stream state is unavailable.

        Args:
            stream_id: Per-stream UUID used as the hash routing key.

        Returns:
            ``redis.asyncio.Redis`` bound to the correct shard.
        """
        self._reset_on_loop_change()
        return self._ensure_client(self._shard_index(stream_id))

    def get_url_for_thread(self, thread_id: str) -> str:
        """Return the Redis URL for the shard responsible for *thread_id*.

        Use this when a caller needs to open a *dedicated* connection (e.g.
        ``XREAD BLOCK`` subscriber, Pub/Sub subscriber) rather than using the
        shared pool client.

        Args:
            thread_id: LangGraph UUID.

        Returns:
            Redis URL string, e.g. ``"redis://redis-0:6379"``.
        """
        return self._urls[self._shard_index(thread_id)]

    # ------------------------------------------------------------------
    # Public API — index-pinned routing (global resources, Celery, locks)
    # ------------------------------------------------------------------

    def get_client_at(self, index: int) -> aioredis.Redis:
        """Return the persistent client at *index* (wraps if >= node_count).

        Use index ``0`` for global resources that must not be sharded (leader
        election locks, Celery broker/backend URLs).

        Args:
            index: Zero-based shard index.

        Returns:
            ``redis.asyncio.Redis`` for the requested shard.
        """
        self._reset_on_loop_change()
        return self._ensure_client(index % len(self._urls))

    def get_url_at(self, index: int) -> str:
        """Return the Redis URL at *index* (wraps if >= node_count).

        Args:
            index: Zero-based shard index.

        Returns:
            Redis URL string.
        """
        return self._urls[index % len(self._urls)]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close_all(self) -> None:
        """Close all open client connections.

        Call during application shutdown to cleanly drain connection pools.
        """
        for i, client in enumerate(self._clients):
            if client is not None:
                try:
                    await client.aclose()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[RedisRouter] close_all error shard=%d: %s", i, exc
                    )
        self._clients = [None] * len(self._urls)

    @property
    def node_count(self) -> int:
        """Number of Redis nodes managed by this router."""
        return len(self._urls)


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_router: Optional[RedisRouter] = None


def get_redis_router() -> RedisRouter:
    """Return the process-wide :class:`RedisRouter`, creating it on first call.

    Reads ``DATABASE_REDIS_NODES`` from settings.  If the list is empty, falls
    back to ``DATABASE_REDIS_URL`` as a single-node cluster so existing
    environments keep working without configuration changes.

    Returns:
        Singleton :class:`RedisRouter` instance.
    """
    global _router
    if _router is None:
        settings = get_settings()
        nodes = settings.DATABASE_REDIS_NODES
        if not nodes:
            nodes = [settings.DATABASE_REDIS_URL]
        _router = RedisRouter(nodes)
        logger.info(
            "[RedisRouter] initialised node_count=%d urls=%s",
            len(nodes),
            nodes,
        )
    return _router
