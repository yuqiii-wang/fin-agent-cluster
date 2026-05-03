"""Task-step ack helpers — delivery tracking via the Redis task-ACK store.

Thin wrappers that delegate to
:mod:`backend.db.redis.task_ack_store` so callers (the SSE generator in
:mod:`backend.api.stream`) do not need to import the Redis store directly.

* :func:`ack_task_step` — called once on successful first delivery.
* :func:`increment_task_step_retry` — called on each drain-cycle re-emit.

Both functions are no-ops when *task_id* is ``None`` or empty (session-level
events such as ``"done"``) or when *event_type* has no matching step status.
"""

from __future__ import annotations

from typing import Optional

from backend.db.redis.session.task_ack_store import (
    ack_task_step as _ack_task_step,
    increment_task_step_retry as _increment_task_step_retry,
)


async def ack_task_step(
    thread_id: str,
    task_id: Optional[str],
    event_type: str,
) -> None:
    """Mark the task step as acknowledged in the Redis task-ACK store.

    Args:
        thread_id:  LangGraph UUID.
        task_id:  Task primary key.  If ``None`` or empty returns immediately.
        event_type: SSE event name, e.g. ``"completed"``.
    """
    await _ack_task_step(thread_id, task_id, event_type)


async def increment_task_step_retry(
    thread_id: str,
    task_id: Optional[str],
    event_type: str,
) -> None:
    """Increment retry counter for an unacked task step in the Redis task-ACK store.

    Args:
        thread_id:  LangGraph UUID.
        task_id:  Task primary key.  If ``None`` or empty returns immediately.
        event_type: SSE event name, e.g. ``"completed"``.
    """
    await _increment_task_step_retry(thread_id, task_id, event_type)


__all__ = ["ack_task_step", "increment_task_step_retry"]
