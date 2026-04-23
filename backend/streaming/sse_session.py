"""SSE session utilities — watch registry, event replay, and orphan detection.

Extracted from ``backend.api.stream`` to keep the FastAPI router thin.
These helpers are shared across the dual-channel SSE endpoint and any
future session-aware streaming extensions.

Public API
----------
LIFECYCLE_EVENTS        — frozenset of pg_notify SSE event types that must be acked.
register_watch()        — mark a task as the currently expanded task for a thread (async, Redis-backed).
unregister_watch()      — clear the watch registration for a thread (async, Redis-backed).
get_watched_task()      — return the watched task_id or None (async, Redis-backed with local cache).
is_thread_watching()    — predicate: does the thread have an active watch? (async, Redis-backed).
replay_existing()       — load existing tasks/query state for late-connecting clients.
handle_orphaned_query() — mark an orphaned running query as failed/cancelled.

Watch registry is backed by Redis so ``PUT /stream/{id}/watch`` and
``GET /stream/{id}`` can be served by different FastAPI instances.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select, update

from backend.db.postgres.engine import get_session_factory
from backend.db.redis.query_phase import get_query_phase
from backend.db.redis.watch_registry import (
    get_watched_task,
    is_thread_watching,
    register_watch,
    unregister_watch,
)
from backend.graph.models import AgentTask
from backend.users.models import UserQuery

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: SSE event types that travel through the pg_notify path and must be acked.
#: ``query_received`` is included so the pending-notify store entry is cleared
#: when the SSE generator delivers it to the client.
LIFECYCLE_EVENTS: frozenset[str] = frozenset(
    {"started", "completed", "failed", "cancelled", "done", "query_received"}
)

#: Sentinel query text that identifies perf-test sessions for orphan handling.
_PERF_TEST_QUERY = "DO STREAMING PERFORMANCE TEST NOW"

# Watch registry functions are provided by backend.db.redis.watch_registry
# (Redis-backed with in-process cache) and imported above.


# ---------------------------------------------------------------------------
# Event replay
# ---------------------------------------------------------------------------


async def replay_existing(thread_id: str) -> tuple[list[dict], str]:
    """Load existing tasks and query status for late-connecting SSE clients.

    Queries the DB for the current ``user_queries.status`` and all
    ``agent_tasks`` rows for *thread_id*, then builds the SSE-ready event
    list that a freshly connecting client needs to reconstruct current state.

    Args:
        thread_id: The LangGraph thread UUID.

    Returns:
        A tuple of ``(replay_events, query_status)`` where *replay_events* is
        a list of ``{"event": str, "data": str}`` dicts ready for
        ``EventSourceResponse`` and *query_status* is the current
        ``user_queries.status`` string.
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
    # phase so that late-connecting SSE clients (who missed the live pg_notify
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

    return events, query_status


# ---------------------------------------------------------------------------
# Orphan detection
# ---------------------------------------------------------------------------


async def handle_orphaned_query(thread_id: str) -> str:
    """Mark an orphaned running query as failed or cancelled.

    An orphaned query has status ``'running'`` but no active asyncio task in
    the in-memory registry — which happens when the server restarted mid-query.
    Performance-test queries are cancelled (not failed) as they are ephemeral.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        ``'cancelled'`` for perf-test queries, ``'failed'`` otherwise.
    """
    factory = get_session_factory()
    async with factory() as session:
        uq = await session.scalar(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        is_perf_test = uq is not None and uq.query.strip() == _PERF_TEST_QUERY
        if is_perf_test:
            logger.debug("[stream] perf-test orphan cancelled thread_id=%s", thread_id)
            await session.execute(
                update(UserQuery)
                .where(UserQuery.thread_id == thread_id)
                .values(status="cancelled")
            )
        else:
            logger.warning(
                "[stream] orphaned running query detected thread_id=%s", thread_id
            )
            await session.execute(
                update(UserQuery)
                .where(UserQuery.thread_id == thread_id)
                .values(status="failed", error="Server restarted — query interrupted")
            )
        await session.commit()

    return "cancelled" if is_perf_test else "failed"


__all__ = [
    "LIFECYCLE_EVENTS",
    "register_watch",
    "unregister_watch",
    "get_watched_task",
    "is_thread_watching",
    "replay_existing",
    "handle_orphaned_query",
]

