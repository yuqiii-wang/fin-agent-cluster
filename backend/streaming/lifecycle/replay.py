"""Streaming lifecycle — SSE state replay for late-connecting clients.

When a client opens the SSE stream after query execution has already started
(or finished), it needs the current task list and query status to reconstruct
UI state.  :func:`replay_existing` builds this catch-up event list from
PostgreSQL.

The returned events are injected at the front of the SSE response by the
``GET /stream/{thread_id}`` generator before it begins forwarding live events.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select

from backend.db.postgres.engine import get_session_factory
from backend.db.redis.session.query_phase import get_query_phase
from backend.graph.models import AgentTask
from backend.users.models import UserQuery

logger = logging.getLogger(__name__)


async def replay_existing(thread_id: str) -> tuple[list[dict], str]:
    """Load existing tasks and query status for late-connecting SSE clients.

    Queries the DB for the current ``user_queries.status`` and all
    ``agent_tasks`` rows for *thread_id*, then builds the SSE-ready event list
    that a freshly connecting client needs to reconstruct current UI state.

    For queries still in ``"running"`` or ``"received"`` state the current
    backend phase is fetched from Redis and injected as a ``query_status``
    event so the client immediately displays the correct status label even if
    it missed the original live event.

    For queries still awaiting client ACK (status ``"received"``) the
    ``query_received`` event is re-injected so the client can send its ACK
    without waiting for the drain-cycle timeout to re-emit it.

    Each task in the DB contributes a ``started`` event plus — when terminal —
    a ``completed``/``failed``/``cancelled`` event so the client can fully
    restore the task list without relying on live events.

    Args:
        thread_id: The LangGraph thread UUID.

    Returns:
        A tuple of ``(replay_events, query_status)`` where *replay_events* is a
        list of ``{"event": str, "data": str}`` dicts ready for
        ``EventSourceResponse`` and *query_status* is the current
        ``user_queries.status`` string (e.g. ``"running"``, ``"completed"``).
    """
    factory = get_session_factory()
    events: list[dict] = []
    query_status = "running"

    async with factory() as session:
        uq_row = await session.scalar(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        if uq_row is not None:
            query_status = uq_row.status

        result = await session.execute(
            select(AgentTask)
            .where(AgentTask.thread_id == thread_id)
            .order_by(AgentTask.created_at)
        )
        tasks = result.scalars().all()

    # For still-running or pending-ack queries, inject the current backend
    # phase so that late-connecting SSE clients (who missed the live lifecycle
    # event) can immediately display the correct status label.
    if query_status in ("running", "received"):
        phase = await get_query_phase(thread_id)
        if phase:
            events.append({
                "event": "query_status",
                "data": json.dumps({"event": "query_status", "phase": phase}),
            })

    # For queries still awaiting client ACK, replay query_received so the
    # client can send its ACK without waiting for the drain cycle timeout.
    if query_status == "received":
        events.append({
            "event": "query_received",
            "data": json.dumps({"event": "query_received", "thread_id": thread_id}),
        })

    for task in tasks:
        started_payload = json.dumps({
            "event": "started",
            "task_id": task.id,
            "node_name": task.node_name,
            "task_key": task.task_key,
        })
        events.append({"event": "started", "data": started_payload})

        if task.status in ("completed", "failed", "cancelled"):
            done_payload = json.dumps({
                "event": task.status,
                "task_id": task.id,
                "node_name": task.node_name,
                "task_key": task.task_key,
                "output": task.output if task.output else {},
            })
            events.append({"event": task.status, "data": done_payload})

    logger.debug(
        "[replay_existing] thread_id=%s query_status=%s replay_events=%d",
        thread_id, query_status, len(events),
    )
    return events, query_status


__all__ = ["replay_existing"]
