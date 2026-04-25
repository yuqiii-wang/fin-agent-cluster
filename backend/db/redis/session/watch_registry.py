"""Redis-backed watch registry — instance-agnostic task-watch tracking.

Stores the currently expanded task_id for each active SSE session in Redis so
that ``PUT /stream/{id}/watch`` and ``GET /stream/{id}`` can be served by
different FastAPI instances without losing the watch state.

An in-process cache is kept for the hot path (token filtering inside the SSE
generator).  Cache misses fall back to Redis — this only occurs when the
``PUT /watch`` request was served by a different instance than the SSE generator.

Key:   ``watch:{thread_id}``  (Redis String, integer value)
TTL:   3600 s — covers the longest expected SSE session with margin.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.db.redis.router import get_redis_router

logger = logging.getLogger(__name__)

_WATCH_PREFIX = "watch:"
_WATCH_TTL = 3600

# In-process cache — avoids a Redis round-trip per token in the hot path.
# Populated on register; cleared on unregister; refreshed from Redis on miss.
_local_cache: dict[str, int] = {}


def _watch_key(thread_id: str) -> str:
    """Return the Redis key for the watch registration of *thread_id*."""
    return f"{_WATCH_PREFIX}{thread_id}"


async def register_watch(thread_id: str, task_id: int) -> None:
    """Register *task_id* as the currently watched task for *thread_id*.

    Writes to both the in-process cache and Redis so any FastAPI instance can
    read the current watch state.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   DB primary key of the task the client has expanded.
    """
    _local_cache[thread_id] = task_id
    try:
        client = get_redis_router().get_client_for_thread(thread_id)
        await client.setex(_watch_key(thread_id), _WATCH_TTL, task_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[watch_registry] register failed thread_id=%s: %s", thread_id, exc)
    logger.debug("[watch_registry] registered task_id=%d thread_id=%s", task_id, thread_id)


async def unregister_watch(thread_id: str) -> None:
    """Clear the watch registration for *thread_id*.

    Args:
        thread_id: LangGraph thread UUID.
    """
    _local_cache.pop(thread_id, None)
    try:
        client = get_redis_router().get_client_for_thread(thread_id)
        await client.delete(_watch_key(thread_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[watch_registry] unregister failed thread_id=%s: %s", thread_id, exc)
    logger.debug("[watch_registry] unregistered thread_id=%s", thread_id)


async def get_watched_task(thread_id: str) -> Optional[int]:
    """Return the currently watched task_id, or ``None`` if absent.

    Checks the in-process cache first; falls back to Redis on a cache miss
    (e.g. when ``PUT /watch`` was served by a different instance).

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        The watched ``task_id``, or ``None`` if no task is being watched.
    """
    cached = _local_cache.get(thread_id)
    if cached is not None:
        return cached
    try:
        client = get_redis_router().get_client_for_thread(thread_id)
        val = await client.get(_watch_key(thread_id))
        if val is not None:
            task_id = int(val)
            _local_cache[thread_id] = task_id  # warm local cache for hot path
            return task_id
    except Exception as exc:  # noqa: BLE001
        logger.warning("[watch_registry] get failed thread_id=%s: %s", thread_id, exc)
    return None


async def is_thread_watching(thread_id: str) -> bool:
    """Return ``True`` if *thread_id* has an active watch registration.

    Args:
        thread_id: LangGraph thread UUID.
    """
    return await get_watched_task(thread_id) is not None


__all__ = [
    "register_watch",
    "unregister_watch",
    "get_watched_task",
    "is_thread_watching",
]
