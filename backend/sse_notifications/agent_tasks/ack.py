"""Task-step ack helpers — update is_ack / retry_count in the DB.

When the SSE generator delivers (or retries) a pg_notify lifecycle event it
calls these helpers to keep ``fin_agents.streamings`` in sync:

* :func:`ack_task_step` — called once on successful first delivery; sets
  ``is_ack = TRUE`` and ``ack_at = NOW()``.
* :func:`increment_task_step_retry` — called on each drain-cycle re-emit
  (i.e. before a confirmed ack); increments ``retry_count``.

Both functions are no-ops when:
  - *event_type* is not a lifecycle event with a corresponding task-step status.
  - *task_id* is ``None`` (session-level events such as ``"done"``).

Imports of ``Streaming`` are deferred inside each function to avoid the circular
dependency chain:
  ``sse_notifications`` ← ``backend.graph`` ← agents ← ``sse_notifications``
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from backend.db.postgres.engine import get_session_factory

logger = logging.getLogger(__name__)

#: Maps SSE event_type strings to the corresponding streamings.status values.
#: Values must be valid fin_agents.streaming_status ENUM members.
_EVENT_TO_STEP_STATUS: dict[str, str] = {
    "started": "digesting",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
}


async def ack_task_step(task_id: int | None, event_type: str) -> None:
    """Mark the most recent unacked task_step row as acknowledged.

    Finds the latest ``streamings`` row whose ``task_id`` matches and whose
    ``status`` corresponds to *event_type*, then sets ``is_ack = TRUE`` and
    ``ack_at = NOW()`` (only if ``is_ack`` is currently ``FALSE``).

    Args:
        task_id:    DB task PK.  If ``None`` the function returns immediately
                    (session-level events have no corresponding task_step row).
        event_type: SSE event name, e.g. ``"completed"``.
    """
    if task_id is None:
        return
    step_status = _EVENT_TO_STEP_STATUS.get(event_type)
    if not step_status:
        return

    from backend.graph.models import Streaming  # deferred to avoid circular import

    factory = get_session_factory()
    try:
        async with factory() as session:
            # Subquery: find the most recent unacked step for this task + status.
            subq = (
                select(Streaming.id)
                .where(
                    Streaming.task_id == task_id,
                    Streaming.status == step_status,
                    Streaming.is_ack == False,  # noqa: E712
                )
                .order_by(Streaming.created_at.desc())
                .limit(1)
                .scalar_subquery()
            )
            stmt = (
                update(Streaming)
                .where(Streaming.id == subq)
                .values(is_ack=True, ack_at=datetime.now(timezone.utc))
            )
            await session.execute(stmt)
            await session.commit()
            logger.debug(
                "[ack.ack_task_step] task_id=%s event=%s status=%s",
                task_id, event_type, step_status,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[ack.ack_task_step] failed task_id=%s event=%s: %s",
            task_id, event_type, exc,
        )


async def increment_task_step_retry(task_id: int | None, event_type: str) -> None:
    """Increment ``retry_count`` on the most recent unacked task_step row.

    Called by the SSE drain path each time a lost pg_notify is re-emitted.
    Only updates rows where ``is_ack = FALSE`` (once acked no further retries
    are tracked).

    Args:
        task_id:    DB task PK.  If ``None`` the function returns immediately.
        event_type: SSE event name, e.g. ``"completed"``.
    """
    if task_id is None:
        return
    step_status = _EVENT_TO_STEP_STATUS.get(event_type)
    if not step_status:
        return

    from backend.graph.models import Streaming  # deferred to avoid circular import

    factory = get_session_factory()
    try:
        async with factory() as session:
            subq = (
                select(Streaming.id)
                .where(
                    Streaming.task_id == task_id,
                    Streaming.status == step_status,
                    Streaming.is_ack == False,  # noqa: E712
                )
                .order_by(Streaming.created_at.desc())
                .limit(1)
                .scalar_subquery()
            )
            stmt = (
                update(Streaming)
                .where(Streaming.id == subq)
                .values(retry_count=Streaming.retry_count + 1)
            )
            await session.execute(stmt)
            await session.commit()
            logger.debug(
                "[ack.increment_retry] task_id=%s event=%s status=%s",
                task_id, event_type, step_status,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[ack.increment_retry] failed task_id=%s event=%s: %s",
            task_id, event_type, exc,
        )
