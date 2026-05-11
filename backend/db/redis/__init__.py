"""backend.db.redis — lazy async Redis clients, one per shard.

Initialisation is deferred to first access so there is no event-loop
dependency at import time.  Clients are keyed by shard index and reused
for the lifetime of the process.

Usage::

    from backend.db.redis import get_client, shard_for_thread

    redis = await get_client(shard_for_thread(thread_id))
    await redis.xadd("fin:llm:tokens:0", {"thread_id": tid, "token": t})
"""

from __future__ import annotations

import asyncio
import hashlib

import redis.asyncio as aioredis

from backend.config import get_settings

# Shard-indexed pool: {shard_index: (redis.asyncio.Redis, loop_id)}
# The loop_id is id(asyncio.get_running_loop()) at creation time.  Celery
# workers call asyncio.run() per task, creating a new event loop each time;
# stale clients whose loop has since been closed are detected by comparing
# ids and discarded so a fresh pool is created for the new loop.
_clients: dict[int, tuple[aioredis.Redis, int]] = {}
_init_lock: asyncio.Lock | None = None
_init_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_lock() -> asyncio.Lock:
    """Return the init lock, creating a fresh one if the current event loop has changed.

    Celery workers call ``asyncio.run()`` per task, creating a new event loop each
    time.  The ``asyncio.Lock`` must belong to the running loop, so we recreate it
    whenever the running loop differs from the one the previous lock was created on.
    """
    global _init_lock, _init_lock_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _init_lock is None or _init_lock_loop is not loop:
        _init_lock = asyncio.Lock()
        _init_lock_loop = loop
    return _init_lock


def shard_for_thread(thread_id: str) -> int:
    """Return the deterministic Redis shard index for *thread_id*.

    Uses SHA-256 modulo the number of configured shard nodes (falls back to 1
    when no ``DATABASE_REDIS_NODES`` are configured, i.e. always shard 0).

    Args:
        thread_id: LangGraph thread UUID used as the sharding key.

    Returns:
        Zero-based shard index matching ``DATABASE_REDIS_NODES``.
    """
    n = len(get_settings().DATABASE_REDIS_NODES) or 1
    return int(hashlib.sha256(thread_id.encode()).hexdigest(), 16) % n


async def get_client(shard: int = 0) -> aioredis.Redis:
    """Return (lazily creating) the shared async Redis client for *shard*.

    Falls back to ``DATABASE_REDIS_URL`` when ``DATABASE_REDIS_NODES`` is
    empty or the requested shard index is out of range.

    Args:
        shard: Zero-based shard index matching ``DATABASE_REDIS_NODES``.

    Returns:
        Shared :class:`redis.asyncio.Redis` instance with connection pooling.
    """
    # Detect stale clients whose event loop has been closed (happens when
    # Celery workers call asyncio.run() per task — each call creates a new
    # event loop with a different id).  redis[asyncio] v5+ no longer stores
    # _loop on the pool, so we track the loop id ourselves at creation time.
    try:
        current_loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        current_loop_id = 0

    if shard in _clients:
        client, stored_loop_id = _clients[shard]
        if stored_loop_id == current_loop_id:
            return client
        # Loop has changed — drop the stale client (do NOT await aclose since
        # its loop is already closed and aclose would fail or hang).
        del _clients[shard]

    async with _get_lock():
        if shard in _clients:
            client, stored_loop_id = _clients[shard]
            if stored_loop_id == current_loop_id:
                return client
            del _clients[shard]
        settings = get_settings()
        nodes = settings.DATABASE_REDIS_NODES
        url = nodes[shard] if nodes and shard < len(nodes) else settings.DATABASE_REDIS_URL
        client = aioredis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
        )
        _clients[shard] = (client, current_loop_id)
        return client


async def close_all() -> None:
    """Close every open Redis client. Only call during application shutdown
    while the event loop is still running."""
    for client, _ in list(_clients.values()):
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass
    _clients.clear()


__all__ = ["get_client", "close_all", "shard_for_thread"]
