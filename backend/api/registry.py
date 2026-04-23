"""Shared in-process registry of active query background tasks.

Centralises the ``running_tasks`` dict so the query router (writer) and the
stream router (reader) can both access it without a circular import.

All graph queries run as ``asyncio.Task`` objects in the FastAPI event loop.
The :func:`is_task_active` helper checks task liveness and performs lazy GC
so the dict does not grow unbounded.

Multi-instance support
----------------------
``running_tasks`` is process-local and cannot be shared across instances.
To support multi-instance deployments two additional helpers are provided:

* :func:`mark_task_active` — sets a Redis flag ``task_active:{thread_id}``
  when a task starts; called by the query ACK endpoint.
* :func:`clear_task_active` — deletes the flag when the task ends; called by
  the graph runner on all exit paths (completed / cancelled / failed).
* :func:`is_task_active_any_instance` — checks the local dict first, then
  falls back to the Redis flag so any instance can determine whether the query
  is being processed somewhere in the cluster.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Maps thread_id → asyncio.Task (graph execution in the FastAPI event loop).
# Entries are added by the query endpoint and lazily removed by is_task_active().
running_tasks: dict[str, asyncio.Task] = {}

_TASK_ACTIVE_PREFIX = "task_active:"
_TASK_ACTIVE_TTL = 3600  # 1 hour — covers the longest possible query


def is_task_active(thread_id: str) -> bool:
    """Return ``True`` if *thread_id* has a live, not-yet-finished task on this instance.

    Performs lazy GC: when a completed/cancelled entry is encountered it is
    removed from ``running_tasks`` before returning ``False``.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        ``True`` if the task exists locally and has not finished, ``False`` otherwise.
    """
    task: Any = running_tasks.get(thread_id)
    if task is None:
        return False
    if task.done():
        running_tasks.pop(thread_id, None)
        return False
    return True


async def mark_task_active(thread_id: str) -> None:
    """Set the Redis ``task_active:{thread_id}`` flag when a task starts.

    Called by the ACK endpoint immediately after ``asyncio.create_task``.
    Allows any FastAPI instance to determine whether the query is being
    processed via :func:`is_task_active_any_instance`.

    Args:
        thread_id: LangGraph thread UUID.
    """
    try:
        from backend.db.redis.publisher import _get_publish_client  # noqa: PLC0415
        client = await _get_publish_client()
        await client.setex(f"{_TASK_ACTIVE_PREFIX}{thread_id}", _TASK_ACTIVE_TTL, "1")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[registry] mark_task_active failed thread_id=%s: %s", thread_id, exc)


async def clear_all_task_active_flags() -> None:
    """Delete every ``task_active:*`` Redis key left by previous server processes.

    Called once at FastAPI startup — before any task can legitimately be
    active — so orphan detection in the SSE generator correctly identifies
    queries whose server process was killed mid-run.  If the keys are not
    cleared, ``is_task_active_any_instance`` returns ``True`` for stale
    threads and the SSE stream waits forever for a ``done`` event that will
    never arrive (the Redis deadlock caused by orphan tasks on hot switch).
    """
    try:
        from backend.db.redis.publisher import _get_publish_client  # noqa: PLC0415
        client = await _get_publish_client()
        cursor: int = 0
        total = 0
        while True:
            cursor, keys = await client.scan(cursor, match=f"{_TASK_ACTIVE_PREFIX}*", count=100)
            if keys:
                await client.delete(*keys)
                total += len(keys)
            if cursor == 0:
                break
        if total:
            logger.info("[registry] cleared %d stale task_active flag(s) on startup", total)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[registry] clear_all_task_active_flags failed: %s", exc)


async def clear_task_active(thread_id: str) -> None:
    """Delete the Redis ``task_active:{thread_id}`` flag when the task ends.

    Called by the graph runner on all exit paths (completed, cancelled, failed).

    Args:
        thread_id: LangGraph thread UUID.
    """
    try:
        from backend.db.redis.publisher import _get_publish_client  # noqa: PLC0415
        client = await _get_publish_client()
        await client.delete(f"{_TASK_ACTIVE_PREFIX}{thread_id}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[registry] clear_task_active failed thread_id=%s: %s", thread_id, exc)


async def is_task_active_any_instance(thread_id: str) -> bool:
    """Return ``True`` if any FastAPI instance is processing *thread_id*.

    Checks the local ``running_tasks`` dict first (fast path for the owning
    instance), then falls back to the Redis ``task_active:{thread_id}`` flag
    (set by the ACK endpoint, cleared by the runner on completion).

    Used for orphan detection in the SSE generator: a query whose DB status is
    ``'running'`` but whose flag is absent is considered orphaned (all instances
    restarted mid-query).

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        ``True`` if the task is active on any instance, ``False`` if orphaned.
    """
    if is_task_active(thread_id):
        return True
    try:
        from backend.db.redis.publisher import _get_publish_client  # noqa: PLC0415
        client = await _get_publish_client()
        return bool(await client.exists(f"{_TASK_ACTIVE_PREFIX}{thread_id}"))
    except Exception:  # noqa: BLE001
        return False

