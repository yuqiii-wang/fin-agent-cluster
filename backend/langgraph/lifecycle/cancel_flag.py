"""backend.langgraph.lifecycle.cancel_flag -- Redis-backed cancel flags.

Two granularities are supported:

Thread-level  ``{GRAPH_CANCEL_KEY_PREFIX}{thread_id}``
    e.g. ``fin:cancel:abc123``
    Set by ``cancel_thread()``; polled by every delegation poll loop.

Node-level    ``{GRAPH_CANCEL_KEY_PREFIX}node:{node_id}``
    e.g. ``fin:cancel:node:uuid4``
    Set by ``cancel_node()`` when a single parallel node is cancelled via
    the API.  Polled by ``_await_result`` in addition to the thread-level
    flag so the delegation loop exits quickly without waiting for the
    120-second task timeout.

Both key types share the same TTL (``GRAPH_CANCEL_TTL_SECONDS``) and
Redis shard 0.

Public API
----------
:func:`set_cancel_flag`          -- thread-level; called by cancel_thread().
:func:`is_cancel_flag_set`       -- thread-level; polled by task_delegation.
:func:`clear_cancel_flag`        -- thread-level; called on thread completion.
:func:`set_node_cancel_flag`     -- node-level;   called by cancel_node().
:func:`is_node_cancel_flag_set`  -- node-level;   polled by task_delegation.
:func:`clear_node_cancel_flag`   -- node-level;   called on thread cleanup.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Redis shard 0 is used for control-plane signals.
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
    logger.debug("[cancel_flag] set thread_id=%s key=%s", thread_id, key)


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


def _node_cancel_key(node_id: str) -> str:
    """Return the Redis key for the cancel flag of *node_id*."""
    from backend.config import get_settings
    return f"{get_settings().GRAPH_CANCEL_KEY_PREFIX}node:{node_id}"


async def set_node_cancel_flag(node_id: str) -> None:
    """Set the per-node cancel flag for *node_id* in Redis.

    Called by ``cancel_node()`` so the delegation poll loop for that
    node's tasks exits within one poll cycle instead of waiting for the
    full 120-second task timeout.  Idempotent.  Expires after
    ``GRAPH_CANCEL_TTL_SECONDS``.

    Args:
        node_id: Stable node UUID (from ``make_node_id``).
    """
    from backend.config import get_settings
    from backend.db.redis import get_client

    settings = get_settings()
    client = await get_client(_CANCEL_SHARD)
    key = _node_cancel_key(node_id)
    await client.set(key, "1", ex=settings.GRAPH_CANCEL_TTL_SECONDS)
    logger.debug("[cancel_flag] set node_id=%s key=%s", node_id, key)


async def is_node_cancel_flag_set(node_id: str) -> bool:
    """Return ``True`` if the per-node cancel flag for *node_id* is set.

    Args:
        node_id: Stable node UUID.

    Returns:
        ``True`` if the key exists, ``False`` otherwise.
    """
    from backend.db.redis import get_client

    client = await get_client(_CANCEL_SHARD)
    return bool(await client.exists(_node_cancel_key(node_id)))


async def clear_node_cancel_flag(node_id: str) -> None:
    """Delete the per-node cancel flag for *node_id* from Redis.

    Args:
        node_id: Stable node UUID.
    """
    from backend.db.redis import get_client

    client = await get_client(_CANCEL_SHARD)
    await client.delete(_node_cancel_key(node_id))


__all__ = [
    "set_cancel_flag",
    "is_cancel_flag_set",
    "clear_cancel_flag",
    "set_node_cancel_flag",
    "is_node_cancel_flag_set",
    "clear_node_cancel_flag",
]
