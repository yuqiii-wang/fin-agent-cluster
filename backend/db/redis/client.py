"""Lazy async Redis client pool, one client per shard."""

from __future__ import annotations

import asyncio
import hashlib

import redis.asyncio as aioredis

from backend.config import get_settings

# Shard-indexed pool: {shard_index: (redis.asyncio.Redis, loop_id)}
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
    try:
        current_loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        current_loop_id = 0

    if shard in _clients:
        client, stored_loop_id = _clients[shard]
        if stored_loop_id == current_loop_id:
            return client
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
