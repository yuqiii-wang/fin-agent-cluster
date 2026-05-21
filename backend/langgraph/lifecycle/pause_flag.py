"""backend.langgraph.lifecycle.pause_flag — Redis-backed task pause flags.

Key schema
----------
Pause flag  : ``fin:pause:task:{task_id}``
Snapshot    : ``fin:stream_snapshot:{task_id}``

The pause flag is set by ``pause_task_by_uuid()`` and polled by the Celery
stream worker every 20 tokens.  When the worker detects the flag it breaks out
of the streaming loop and returns ``{"paused": True, ...}`` so the accumulated
thinking content can be saved for a future ``compact_and_continue`` retry.

Unlike thread/node cancel flags these are keyed per-task because only the
specific task's worker should stop.

Public API
----------
:func:`set_task_pause_flag`      — called by pause_task_by_uuid().
:func:`is_task_pause_flag_set`   — polled by the stream Celery worker.
:func:`clear_task_pause_flag`    — called by retry_task before retry dispatch.
:func:`save_task_pause_snapshot` — persist partial stream thinking content.
:func:`get_task_pause_snapshot`  — retrieve saved partial thinking content.
"""

from __future__ import annotations

# Redis shard 0 is used for control-plane signals.
_PAUSE_SHARD = 0

_PAUSE_TASK_KEY_PREFIX = "fin:pause:task:"
_PAUSE_TASK_SNAPSHOT_KEY_PREFIX = "fin:stream_snapshot:"
_PAUSE_TASK_SNAPSHOT_TTL = 86400  # 24 hours


def _task_pause_key(task_id: str) -> str:
    """Return the Redis pause-flag key for *task_id*."""
    return f"{_PAUSE_TASK_KEY_PREFIX}{task_id}"


def _task_snapshot_key(task_id: str) -> str:
    """Return the Redis snapshot key used to persist partial stream content."""
    return f"{_PAUSE_TASK_SNAPSHOT_KEY_PREFIX}{task_id}"


async def set_task_pause_flag(task_id: str) -> None:
    """Set the pause flag for a specific streaming task.

    Called by ``pause_task_by_uuid()`` so the stream worker exits its token
    loop on the next 20-token boundary.  Idempotent.  Expires after 24 h.

    Args:
        task_id: Task UUID.
    """
    from backend.config import get_settings
    from backend.db.redis import get_client

    settings = get_settings()
    client = await get_client(_PAUSE_SHARD)
    await client.set(_task_pause_key(task_id), "1", ex=settings.GRAPH_CANCEL_TTL_SECONDS)


async def is_task_pause_flag_set(task_id: str) -> bool:
    """Return ``True`` if the pause flag for *task_id* is set.

    Polled by the stream Celery worker every 20 tokens.

    Args:
        task_id: Task UUID.

    Returns:
        ``True`` if the flag is set, ``False`` otherwise.
    """
    from backend.db.redis import get_client

    client = await get_client(_PAUSE_SHARD)
    return bool(await client.exists(_task_pause_key(task_id)))


async def clear_task_pause_flag(task_id: str) -> None:
    """Delete the pause flag and snapshot for *task_id* from Redis.

    Called by ``retry_task`` before dispatching the retry worker so the
    new run does not immediately re-pause.

    Args:
        task_id: Task UUID.
    """
    from backend.db.redis import get_client

    client = await get_client(_PAUSE_SHARD)
    await client.delete(_task_pause_key(task_id), _task_snapshot_key(task_id))


async def save_task_pause_snapshot(task_id: str, thinking: str) -> None:
    """Persist the partial stream thinking content for a paused task.

    Written by ``_await_result`` when it detects a paused Celery stream
    result.  Read by ``retry_task`` when ``compact_and_continue`` is requested
    for a task that was paused before producing a full LLM response.

    Args:
        task_id:  Task UUID.
        thinking: Accumulated partial thinking text at the moment of pause.
    """
    from backend.db.redis import get_client

    client = await get_client(_PAUSE_SHARD)
    await client.set(_task_snapshot_key(task_id), thinking, ex=_PAUSE_TASK_SNAPSHOT_TTL)


async def get_task_pause_snapshot(task_id: str) -> str:
    """Return the saved partial stream thinking for *task_id*, or empty string.

    Args:
        task_id: Task UUID.

    Returns:
        Partial thinking string, or ``""`` if no snapshot is stored.
    """
    from backend.db.redis import get_client

    client = await get_client(_PAUSE_SHARD)
    raw = await client.get(_task_snapshot_key(task_id))
    if raw is None:
        return ""
    return raw.decode() if isinstance(raw, bytes) else raw


__all__ = [
    "set_task_pause_flag",
    "is_task_pause_flag_set",
    "clear_task_pause_flag",
    "save_task_pause_snapshot",
    "get_task_pause_snapshot",
]
