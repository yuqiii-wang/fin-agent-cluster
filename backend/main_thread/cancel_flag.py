"""backend.main_thread.cancel_flag — Redis-backed per-thread cancel flags.

Cancel signals are written as plain Redis key/value pairs so they survive
across process restarts and are visible to Celery workers that poll them.

Key format:  ``{GRAPH_CANCEL_KEY_PREFIX}{thread_id}``
             e.g. ``fin:cancel:abc123``
TTL:         ``GRAPH_CANCEL_TTL_SECONDS`` (default 600 s) — ensures keys
             expire automatically even if cleanup is skipped.

Public API
----------
:func:`set_cancel_flag`    — called by FastAPI cancel_query().
:func:`is_cancel_flag_set` — polled by Celery workers via task_delegation.
:func:`clear_cancel_flag`  — called on thread completion.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Redis shard 0 is used for control-plane signals; cancel flags are tiny and
# infrequent, so no sharding by thread_id is necessary.
_CANCEL_SHARD = 0


def _cancel_key(thread_id: str) -> str:
    """Return the Redis key for the cancel flag of *thread_id*."""
    from backend.config import get_settings
    return f"{get_settings().GRAPH_CANCEL_KEY_PREFIX}{thread_id}"


async def set_cancel_flag(thread_id: str) -> None:
    """Set the cancel flag for *thread_id* in Redis.

    Idempotent.  The flag expires after ``GRAPH_CANCEL_TTL_SECONDS`` so
    it does not accumulate indefinitely.

    Args:
        thread_id: LangGraph thread UUID.
    """
    from backend.config import get_settings
    from backend.db.redis import get_client

    settings = get_settings()
    client = await get_client(_CANCEL_SHARD)
    key = _cancel_key(thread_id)
    await client.set(key, "1", ex=settings.GRAPH_CANCEL_TTL_SECONDS)
    logger.error("[cancel_flag] set thread_id=%s key=%s", thread_id, key)


async def is_cancel_flag_set(thread_id: str) -> bool:
    """Return ``True`` if the cancel flag for *thread_id* is set in Redis.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        ``True`` if the key exists (flag is set), ``False`` otherwise.
    """
    from backend.db.redis import get_client

    client = await get_client(_CANCEL_SHARD)
    return bool(await client.exists(_cancel_key(thread_id)))


async def clear_cancel_flag(thread_id: str) -> None:
    """Delete the cancel flag for *thread_id* from Redis.

    Called after a thread reaches a terminal state so the key does not
    persist until TTL expiry.

    Args:
        thread_id: LangGraph thread UUID.
    """
    from backend.db.redis import get_client

    client = await get_client(_CANCEL_SHARD)
    await client.delete(_cancel_key(thread_id))


__all__ = ["set_cancel_flag", "is_cancel_flag_set", "clear_cancel_flag"]
