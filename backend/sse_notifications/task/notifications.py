"""Task lifecycle SSE notifications — DB writes + Centrifugo publish.

Every public function follows the same pattern:
  1. Write the new task state to ``fin_agents.tasks`` in PostgreSQL.
  2. Commit the transaction.
  3. Publish to Centrifugo so SSE subscribers receive an authoritative,
     durable event payload.
  4. Record the step in the Redis task-ACK store for delivery tracking.

Timestamp invariance
--------------------
All ``*_at_ms`` fields in the published payloads come from the committed
``fin_agents.tasks`` row — not from wall-clock time at emit:

* ``created_at_ms`` — captured in Python before the INSERT so the value is
  available immediately after commit without an extra SELECT.
* ``updated_at_ms`` — same pattern for terminal updates (completed/failed/cancelled).

``task_id`` is the single identifier — ``fin_agents.tasks.task_id`` is
the primary key, eliminating the former numeric ``id`` column.

``AgentTask`` is imported lazily inside each function to break the circular
dependency:
  ``sse_notifications`` ← ``backend.graph`` (package) ← agents ← ``sse_notifications``
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import update

from backend.db.postgres.engine import get_session_factory
from backend.db.redis.session.task_ack_store import record_task_step
from backend.sse_notifications.channel import publish_task_lifecycle

logger = logging.getLogger(__name__)


def _node_name(task_name: str) -> str:
    """Extract the agent node name from a dot-separated task key.

    Args:
        task_name: Full task key, e.g. ``"market_data_collector.ohlcv.15min"``.

    Returns:
        First dot-separated segment, e.g. ``"market_data_collector"``.
    """
    return task_name.split(".")[0]


async def create_task(
    thread_id: str,
    task_name: str,
    node_execution_id: Optional[int] = None,
    provider: Optional[str] = None,
    task_id: str = "",
    extra_payload: Optional[dict] = None,
) -> str:
    """Insert a running task record in DB and emit a ``started`` SSE notification.

    ``task_id`` is the primary key — callers must generate it before calling
    this function (e.g. ``task_id = str(uuid.uuid4())``).

    Records a delivery step in the Redis task-ACK store after commit.

    Args:
        thread_id:         LangGraph thread UUID.
        task_name:          Full dot-separated task key.
        node_execution_id: FK to the parent ``node_executions`` row (optional).
        provider:          LLM provider name for the ``started`` payload (optional).
        task_id:           Required governance UUID — used as primary key in the DB.
        extra_payload:     Additional fields merged into the ``started`` event
                           payload (e.g. ``node_id``, ``stream_id``).

    Returns:
        The ``task_id`` passed in (echoed for call-site convenience).
    """
    from backend.graph.models import AgentTask  # deferred to avoid circular import

    if not task_id:
        raise ValueError("task_id must be provided — it is the primary key for fin_agents.tasks")

    node = _node_name(task_name)
    # Capture created_at in Python so it is available for the payload immediately
    # after commit without an extra SELECT (server_default would require a refresh).
    _created_at = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        task = AgentTask(
            task_id=task_id,
            thread_id=thread_id,
            node_name=node,
            task_name=task_name,
            status="running",
            node_execution_id=node_execution_id,
            created_at=_created_at,
            updated_at=_created_at,
        )
        session.add(task)
        payload: dict = {
            "event": "started",
            "task_id": task_id,
            "node_name": node,
            "task_name": task_name,
            "created_at_ms": int(_created_at.timestamp() * 1000),
        }
        if provider:
            payload["provider"] = provider
        if extra_payload:
            payload.update(extra_payload)
        logger.info(
            "[task] publish event=started task_id=%s task_name=%s node=%s thread_id=%s",
            task_id,
            task_name,
            node,
            thread_id,
        )
        await session.commit()
    await publish_task_lifecycle(thread_id, payload)
    await record_task_step(thread_id, task_id, "digesting")

    logger.info(
        "[task] created task_id=%s key=%s node=%s thread_id=%s",
        task_id,
        task_name,
        node,
        thread_id,
    )
    return task_id


async def complete_task(
    thread_id: str,
    task_id: str,
    task_name: str,
    output: Optional[dict] = None,
) -> None:
    """Mark a task completed in DB and emit a ``completed`` SSE notification.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Primary key of the task row to update.
        task_name:  Full dot-separated task key.
        output:    Optional result dict persisted to ``tasks.output``.
    """
    from backend.graph.models import AgentTask  # deferred to avoid circular import

    node = _node_name(task_name)
    output_val = output or {}
    _updated_at = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(AgentTask)
            .where(AgentTask.task_id == task_id)
            .values(
                status="completed",
                output=output_val,
                updated_at=_updated_at,
            )
        )
        logger.info(
            "[task] publish event=completed task_id=%s task_name=%s node=%s thread_id=%s",
            task_id,
            task_name,
            node,
            thread_id,
        )
        await session.commit()
    await publish_task_lifecycle(
        thread_id,
        {
            "event": "completed",
            "task_id": task_id,
            "node_name": node,
            "task_name": task_name,
            "output": output_val,
            "updated_at_ms": int(_updated_at.timestamp() * 1000),
        },
    )
    await record_task_step(thread_id, task_id, "completed")

    logger.info(
        "[task] completed task_id=%s key=%s node=%s thread_id=%s output_keys=%s",
        task_id,
        task_name,
        node,
        thread_id,
        list(output_val.keys()),
    )


async def fail_task(
    thread_id: str,
    task_id: str,
    task_name: str,
    error: str,
    error_code: str | None = None,
) -> None:
    """Mark a task failed in DB and emit a ``failed`` SSE notification.

    Args:
        thread_id:  LangGraph thread UUID.
        task_id:    Primary key of the task row.
        task_name:   Full dot-separated task key.
        error:      Error message string (truncated to 500 chars in output).
        error_code: Optional structured error code.  When provided the code and
                    its human-readable description are embedded in the SSE payload
                    so the frontend can show a rich tooltip without an extra
                    API round-trip.
    """
    from backend.graph.models import AgentTask  # deferred to avoid circular import
    from backend.streaming.errors import STREAMING_ERRORS  # deferred

    node = _node_name(task_name)
    output_val: dict = {"error": error[:500]}
    if error_code:
        output_val["error_code"] = error_code
        desc = STREAMING_ERRORS.get(error_code)
        if desc:
            output_val["error_description"] = desc
    _updated_at = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(AgentTask)
            .where(AgentTask.task_id == task_id)
            .values(
                status="failed",
                output=output_val,
                updated_at=_updated_at,
            )
        )
        logger.info(
            "[task] publish event=failed task_id=%s task_name=%s node=%s thread_id=%s",
            task_id,
            task_name,
            node,
            thread_id,
        )
        await session.commit()
    await publish_task_lifecycle(
        thread_id,
        {
            "event": "failed",
            "task_id": task_id,
            "node_name": node,
            "task_name": task_name,
            "output": output_val,
            "updated_at_ms": int(_updated_at.timestamp() * 1000),
        },
    )
    await record_task_step(thread_id, task_id, "failed")

    logger.warning(
        "[task] failed task_id=%s key=%s node=%s error=%r thread_id=%s",
        task_id,
        task_name,
        node,
        error[:120],
        thread_id,
    )


async def cancel_task(
    thread_id: str,
    task_id: str,
    task_name: str,
) -> None:
    """Mark a task cancelled in DB and emit a ``cancelled`` SSE notification.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Primary key of the task row.
        task_name:  Full dot-separated task key.
    """
    from backend.graph.models import AgentTask  # deferred to avoid circular import

    node = _node_name(task_name)
    output_val: dict = {}
    _updated_at = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(AgentTask)
            .where(AgentTask.task_id == task_id)
            .values(
                status="cancelled",
                output=output_val,
                updated_at=_updated_at,
            )
        )
        logger.info(
            "[task] publish event=cancelled task_id=%s task_name=%s node=%s thread_id=%s",
            task_id,
            task_name,
            node,
            thread_id,
        )
        await session.commit()
    await publish_task_lifecycle(
        thread_id,
        {
            "event": "cancelled",
            "task_id": task_id,
            "node_name": node,
            "task_name": task_name,
            "output": output_val,
            "updated_at_ms": int(_updated_at.timestamp() * 1000),
        },
    )
    await record_task_step(thread_id, task_id, "cancelled")

    logger.info(
        "[task] cancelled task_id=%s key=%s node=%s thread_id=%s",
        task_id,
        task_name,
        node,
        thread_id,
    )


__all__ = [
    "create_task",
    "complete_task",
    "fail_task",
    "cancel_task",
]
